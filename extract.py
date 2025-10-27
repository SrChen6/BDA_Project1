from pathlib import Path
import psycopg2
import pandas as pd
# https://pygrametl.org
from pygrametl.datasources import CSVSource, SQLSource
from tqdm import tqdm
import logging

logging.basicConfig(
    filename='cleaning.log',
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)

def connect_postgres(config_path: str = 'db_conf.txt'):
    # Connect to the PostgreSQL source
    path = Path(config_path)
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
    return conn

def extract_from_postgres(conn):
    flightsource = SQLSource(connection=conn,
                            query='select * from "AIMS".flights f;',
                            names=('id', 'aircraftregistration','scheduleddeparture','scheduledarrival','kind','flightid','departureairport','arrivalairport','actualdeparture','actualarrival','cancelled','delaycode','passengers','cabincrew','flightcrew') )

    maintenancesource = SQLSource(connection=conn,
                            query='select * from "AIMS".maintenance m;',
                            names=('id', 'aircraftregistration','scheduleddeparture','scheduledarrival','kind','programmed') )

    logbooksource = SQLSource(connection=conn,
                            query='select * from "AMOS".technicallogbookorders t;',
                            names=('workerid','aircraftregistration','executiondate','executionplace','workpackage','kind','reporteurclass','reporteurid','reportingdate','due','deferred','mel') )

    postflightreportssource = SQLSource(connection=conn,
                            query='select * from "AMOS".postflightreports p;',
                            names=('pfrid','aircraftregistration','reportingdate','reporteurid','reporteurclass','description','tlborder') )
    return {"flights": flightsource, "maintenance": maintenancesource, "logbook": logbooksource, "postflight": postflightreportssource}


def extract_from_csv():
    manufacturerinfosource = CSVSource(open('aircraft-manufaturerinfo-lookup.csv', 'r'), delimiter=',')
    # aircraft_reg_code,manufacturer_serial_number,aircraft_model,aircraft_manufacturer
    personnelsource = CSVSource(open('maintenance_personnel.csv', 'r'), delimiter=',')
    # reporteurid,airport
    return {'manufacturerinfo': manufacturerinfosource, 'personnel': personnelsource}

def run_all_sources():
    conn = connect_postgres()
    sql_data = extract_from_postgres(conn)
    csv_data = extract_from_csv()
    return {**sql_data, **csv_data}

# ====================================================================================================================================
# Baseline queries
def get_aircrafts_per_manufacturer() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for row in CSVSource(open('aircraft-manufaturerinfo-lookup.csv', 'r'), delimiter=','):
        # row is a dict-like object: row['aircraft_reg_code'], row['aircraft_manufacturer'], etc.
        reg = row.get('aircraft_reg_code')
        manufacturer = row.get('aircraft_manufacturer')
        if reg is None or manufacturer is None:
            # skip or log
            continue
        # Insert into the list
        if manufacturer not in result:
            result[manufacturer] = []
        result[manufacturer].append(reg)
    return result

def query_utilization_baseline():
    aircrafts = get_aircrafts_per_manufacturer()
    conn = connect_postgres()
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
    conn = connect_postgres()
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
            f1.counter,
            f2.flightHours,
            f2.flightCycles,
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
    conn = connect_postgres()
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
