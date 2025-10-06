from pathlib import Path
import psycopg2
import pandas as pd
# https://pygrametl.org
from pygrametl.datasources import CSVSource, SQLSource
from tqdm import tqdm
import logging


# Connect to the PostgreSQL source
path = Path("db_conf.txt")
if not path.is_file():
    raise FileNotFoundError(f"Database configuration file '{path.absolute()}' not found.")
try:
    parameters = {}
    # Read the database configuration from the provided txt file, line by line
    with open(path, 'r') as f:
        lines = f.readlines()
        for line in lines:
            parameters[line.split('=', 1)[0]] = line.split('=', 1)[1].strip()
    conn = psycopg2.connect(
        dbname=parameters['dbname'],
        user=parameters['user'],
        password=parameters['password'],
        host=parameters['ip'],
        port=parameters['port']
    )
except psycopg2.Error as e:
    print(e)
    raise ValueError(f"Unable to connect to the database: {parameters}")
except Exception as e:
    print(e)
    raise ValueError(f"Database configuration file '{path.absolute()}' not properly formatted (check file 'db_conf.example.txt'.")


# TODO: Implement here all the extracting functions

flightsource = SQLSource(connection=conn,
                        query='select * from "AIMS".flights f;',
                        names=('id', 'aircraftregistration','scheduleddeparture','scheduledarrival','kind','flightid','departureairport','arrivalairport','actualdeparture','actualarrival','cancelled','delaycode','passengers','cabincrew','flightcrew') )

manteinancesource = SQLSource(connection=conn,
                        query='select * from "AIMS".maintenance m;',
                        names=('id', 'aircraftregistration','scheduleddeparture','scheduledarrival','kind','programmed') )

slotssource = SQLSource(connection=conn,
                        query='select * from "AIMS".slots s ;',
                        names=('id', 'aircraftregistration','scheduleddeparture','scheduledarrival','kind') )

logbooksource = SQLSource(connection=conn,
                        query='select * from "AMOS".technicallogbookorders t;',
                        names=('workerid','aircraftregistration','executiondate','executionplace','workpackage','kind','reporteurclass','reporteurid','reportingdate','due','deferred','mel') )

manufacturerinfosource = CSVSource(open('aircraft-manufaturerinfo-lookup.csv', 'r'), delimiter=',')
# aircraft_reg_code,manufacturer_serial_number,aircraft_model,aircraft_manufacturer
personnelsource = CSVSource(open('maintenance_personnel.csv', 'r'), delimiter=',')
# reporteurid,airport

for i in flightsource:
    print(i["id"])


# ====================================================================================================================================
# Baseline queries
def get_aircrafts_per_manufacturer() -> dict[str, list[str]]:
    # TODO: Implement a function to generate a dictionary with one entry per manufacturer and a list of aircraft identifiers as values
    result: dict[str, list[str]] = {}
    for row in manufacturerinfosource:
        # row is a dict-like object: row['aircraft_reg_code'], row['aircraft_manufacturer'], etc.
        reg = row.get('aircraft_reg_code')
        manufacturer = row.get('aircraft_manufacturer')
        if reg is None or manufacturer is None:
            # skip or log
            print('AAAAAAAAAAAAAAAAAAAAAAA')
            continue
        # Insert into the list
        if manufacturer not in result:
            result[manufacturer] = []
        result[manufacturer].append(reg)
    return result


def query_utilization_baseline():
    aircrafts = get_aircrafts_per_manufacturer()
    cur = conn.cursor()
    cur.execute(f"""
        WITH atomic_data AS (
            SELECT f.aircraftregistration,
                CASE 
                    WHEN f.aircraftregistration in ('{"','".join(aircrafts.get("Airbus", []))}') THEN 'Airbus'
                    WHEN f.aircraftregistration in ('{"','".join(aircrafts.get("Boeing", []))}') THEN 'Boeing'
                    ELSE f.aircraftregistration
                    END AS manufacturer, 
                DATE_PART('year', f.scheduleddeparture)::text AS year,
                CASE WHEN f.cancelled 
                    THEN 0
                    ELSE EXTRACT(EPOCH FROM f.actualarrival-f.actualdeparture) / 3600
                    END AS flightHours,
                CASE WHEN f.cancelled 
                    THEN 0
                    ELSE 1
                    END AS flightCycles,
                CASE WHEN f.cancelled
                    THEN 1
                    ELSE 0
                    END AS cancellations,
                CASE WHEN f.cancelled
                    THEN 0
                    ELSE CASE WHEN EXTRACT(EPOCH FROM f.actualarrival - f.scheduledarrival) / 60 > 15
                        THEN 1
                        ELSE 0
                        END
                    END AS delays,
                CASE WHEN f.cancelled
                    THEN 0
                    ELSE CASE WHEN EXTRACT(EPOCH FROM f.actualarrival - f.scheduledarrival) / 60 > 15
                        THEN EXTRACT(EPOCH FROM f.actualarrival - f.scheduledarrival) / 60
                        ELSE 0
                        END
                    END AS delayedMinutes,
                0 AS scheduledOutOfService,
                0 AS unScheduledOutOfService
            FROM "AIMS".flights f
            UNION ALL
            SELECT m.aircraftregistration,           
                CASE 
                    WHEN m.aircraftregistration in ('{"','".join(aircrafts.get("Airbus", []))}') THEN 'Airbus'
                    WHEN m.aircraftregistration in ('{"','".join(aircrafts.get("Boeing", []))}') THEN 'Boeing'
                    ELSE m.aircraftregistration
                    END AS manufacturer, 
                DATE_PART('year', m.scheduleddeparture)::text AS year,
                0 AS flightHours,
                0 AS flightCycles,
                0 AS cancellations,
                0 AS delays,
                0 AS delayedMinutes,
                CASE WHEN m.programmed
                    THEN EXTRACT(EPOCH FROM m.scheduledarrival-m.scheduleddeparture)/(24*3600)
                    ELSE 0
                    END AS scheduledOutOfService,
                CASE WHEN m.programmed
                    THEN 0
                    ELSE EXTRACT(EPOCH FROM m.scheduledarrival-m.scheduleddeparture)/(24*3600)
                    END AS unScheduledOutOfService
            FROM "AIMS".maintenance m
            )
        SELECT a.manufacturer, a.year, 
            ROUND(SUM(a.flightHours)/COUNT(DISTINCT a.aircraftregistration), 2) AS FH,
            ROUND(SUM(a.flightCycles)/COUNT(DISTINCT a.aircraftregistration), 2) AS TakeOff,
            ROUND(SUM(a.scheduledOutOfService)/COUNT(DISTINCT a.aircraftregistration), 2) AS ADOSS,
            ROUND(SUM(a.unscheduledOutOfService)/COUNT(DISTINCT a.aircraftregistration), 2) AS ADOSU,
            ROUND((SUM(a.scheduledOutOfService)+SUM(a.unscheduledOutOfService))/COUNT(DISTINCT a.aircraftregistration), 2) AS ADOS,
            365-ROUND((SUM(a.scheduledOutOfService)+SUM(a.unscheduledOutOfService))/COUNT(DISTINCT a.aircraftregistration), 2) AS ADIS, -- This assumes a period of one year (as in the group by)
            ROUND(ROUND(SUM(a.flightHours)/COUNT(DISTINCT a.aircraftregistration), 2)/((365-ROUND((SUM(a.scheduledOutOfService)+SUM(a.unscheduledOutOfService))/COUNT(DISTINCT a.aircraftregistration), 2))*24), 2) AS DU,
            ROUND(ROUND(SUM(a.flightCycles)/COUNT(DISTINCT a.aircraftregistration), 2)/(365-ROUND((SUM(a.scheduledOutOfService)+SUM(a.unscheduledOutOfService))/COUNT(DISTINCT a.aircraftregistration), 2)), 2) AS DC,
            100*ROUND(SUM(delays)/ROUND(SUM(a.flightCycles), 2), 4) AS DYR,
            100*ROUND(SUM(a.cancellations)/ROUND(SUM(a.flightCycles), 2), 4) AS CNR,
            100-ROUND(100*(SUM(delays)+SUM(cancellations))/SUM(a.flightCycles), 2) AS TDR,
            100*ROUND(SUM(delayedMinutes)/SUM(delays),2) AS ADD
        FROM atomic_data a
        GROUP BY a.manufacturer, a.year
        ORDER BY a.manufacturer, a.year;
        """)
    result = cur.fetchall()
    cur.close()
    return result

def query_reporting_baseline():
    aircrafts = get_aircrafts_per_manufacturer()
    cur = conn.cursor()
    cur.execute(f"""
        WITH 
            atomic_data_utilization AS (
                SELECT
                    CASE 
                        WHEN f.aircraftregistration in ('{"','".join(aircrafts.get("Airbus", []))}') THEN 'Airbus'
                        WHEN f.aircraftregistration in ('{"','".join(aircrafts.get("Boeing", []))}') THEN 'Boeing'
                        ELSE f.aircraftregistration
                        END AS manufacturer, 
                    DATE_PART('year', f.scheduleddeparture)::text AS year,
                    CAST(SUM(CASE WHEN f.cancelled 
                        THEN 0
                        ELSE EXTRACT(EPOCH FROM f.actualarrival-f.actualdeparture) / 3600
                        END) AS numeric) AS flightHours,
                    CAST(SUM(CASE WHEN f.cancelled 
                        THEN 0
                        ELSE 1
                        END) AS numeric) AS flightCycles
                FROM "AIMS".flights f
                GROUP BY manufacturer, YEAR
                ),
            atomic_data_reporting AS (
                SELECT
                    CASE 
                        WHEN f.aircraftregistration in ('{"','".join(aircrafts.get("Airbus", []))}') THEN 'Airbus'
                        WHEN f.aircraftregistration in ('{"','".join(aircrafts.get("Boeing", []))}') THEN 'Boeing'
                        ELSE f.aircraftregistration
                        END AS manufacturer, 
                    DATE_PART('year', f.reportingdate)::text AS year,
                    COUNT(*) AS counter
                FROM "AMOS".postflightreports f
                GROUP BY manufacturer, YEAR
                )
        SELECT f1.manufacturer, f1.year,
            1000*ROUND(f1.counter/f2.flightHours, 3) AS RRh,
            100*ROUND(f1.counter/f2.flightCycles, 2) AS RRc               
        FROM atomic_data_reporting f1
            JOIN atomic_data_utilization f2 ON f2.manufacturer = f1.manufacturer AND f1.year = f2.year
        ORDER BY f1.manufacturer, f1.YEAR;
        """)
    result = cur.fetchall()
    cur.close()
    return result

def query_reporting_per_role_baseline():
    aircrafts = get_aircrafts_per_manufacturer()
    cur = conn.cursor()
    cur.execute(f"""
        WITH 
            atomic_data_utilization AS (
                SELECT
                    CASE 
                        WHEN f.aircraftregistration in ('{"','".join(aircrafts.get("Airbus", []))}') THEN 'Airbus'
                        WHEN f.aircraftregistration in ('{"','".join(aircrafts.get("Boeing", []))}') THEN 'Boeing'
                        ELSE f.aircraftregistration
                        END AS manufacturer, 
                    DATE_PART('year', f.scheduleddeparture)::text AS year,
                    CAST(SUM(CASE WHEN f.cancelled 
                        THEN 0
                        ELSE EXTRACT(EPOCH FROM f.actualarrival-f.actualdeparture) / 3600
                        END) AS numeric) AS flightHours,
                    CAST(SUM(CASE WHEN f.cancelled 
                        THEN 0
                        ELSE 1
                        END) AS numeric) AS flightCycles
                FROM "AIMS".flights f
                GROUP BY manufacturer, YEAR
                ),
            atomic_data_reporting AS (
                SELECT
                    CASE 
                        WHEN f.aircraftregistration in ('{"','".join(aircrafts.get("Airbus", []))}') THEN 'Airbus'
                        WHEN f.aircraftregistration in ('{"','".join(aircrafts.get("Boeing", []))}') THEN 'Boeing'
                        ELSE f.aircraftregistration
                        END AS manufacturer, 
                    DATE_PART('year', f.reportingdate)::text AS year,
                    f.reporteurclass AS role,
                    COUNT(*) AS counter
                FROM "AMOS".postflightreports f
                GROUP BY manufacturer, year, role
                )
        SELECT f1.manufacturer, f1.year, f1.role,
            1000*ROUND(f1.counter/f2.flightHours, 3) AS RRh,
            100*ROUND(f1.counter/f2.flightCycles, 2) AS RRc              
        FROM atomic_data_reporting f1
            JOIN atomic_data_utilization f2 ON f2.manufacturer = f1.manufacturer AND f1.year = f2.year
        ORDER BY f1.manufacturer, f1.year, f1.role;
        """)
    result = cur.fetchall()
    cur.close()
    return result

##################################################################################################################
# Transform
# Configure logging
logging.basicConfig(
    filename='cleaning.log',           # Log file name
    level=logging.INFO,           # Logging level
    format='%(message)s'  # Log message format
)

def build_dateCode(date) -> str:
    return f"{date.year}-{date.month}-{date.day}"


def build_monthCode(date) -> str:
    return f"{date.year}{str(date.month).zfill(2)}"

from datetime import datetime

def diff_seconds(dt1, dt2) -> float:
    delta = dt2 - dt1
    return delta.total_seconds()


#flightinfo = pd.DataFrame(columns=['plane', 'time', 'FH', 'TO'])
# TODO: hay Null-values en actualdeparture
print("pandas created")
for flight in flightsource:
    print("started iter")
    print(flight["actualdeparture"])
    FH = diff_seconds(flight["actualdeparture"], flight["actualarrival"])
    print("computes FH")
    #flightinfo.add('a', 'b', FH, 'd')
    print("adds to pandas")
    print(FH)
    print("ended iter")

