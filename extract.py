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



flightsource = SQLSource(connection=conn,
                        query='select * from "AIMS".flights f;',
                        names=('id', 'aircraftregistration','scheduleddeparture','scheduledarrival','kind','flightid','departureairport','arrivalairport','actualdeparture','actualarrival','cancelled','delaycode','passengers','cabincrew','flightcrew') )

manteinancesource = SQLSource(connection=conn,
                        query='select * from "AIMS".maintenance m;',
                        names=('id', 'aircraftregistration','scheduleddeparture','scheduledarrival','kind','programmed') )

logbooksource = SQLSource(connection=conn,
                        query='select * from "AMOS".technicallogbookorders t;',
                        names=('workerid','aircraftregistration','executiondate','executionplace','workpackage','kind','reporteurclass','reporteurid','reportingdate','due','deferred','mel') )

postflightreportssource = SQLSource(connection=conn,
                        query='select * from "AMOS".technicallogbookorders t;',
                        names=('pfrid','aircraftregistration','reportingdate','reporteurid','reporteurclass','description','tlborder') )

manufacturerinfosource = CSVSource(open('aircraft-manufaturerinfo-lookup.csv', 'r'), delimiter=',')
# aircraft_reg_code,manufacturer_serial_number,aircraft_model,aircraft_manufacturer
personnelsource = CSVSource(open('maintenance_personnel.csv', 'r'), delimiter=',')
# reporteurid,airport



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
    return f"{date.year}-{str(date.month).zfill(2)}"


def create_dim_aircraft():
    aircraft_lst = []
    for aircraft in manufacturerinfosource:
            aircraft_lst.append([aircraft['aircraft_reg_code'], aircraft['aircraft_model'], aircraft['aircraft_manufacturer']])
    aircraftdim = pd.DataFrame(aircraft_lst, columns=['aircraft', 'model', 'manufacturer'])
    return aircraftdim

def create_dim_time():
    time_lst = []
    for date in pd.date_range("2023-01-01", "2024-12-31"):
        time_lst.append([date, date.day, date.month, date.year])
    timedim = pd.DataFrame(time_lst, columns=['date', 'day', 'month', 'year'])
    print(timedim.head())
    return timedim
        

def extract_flight():
    prev_flight = None

    flightinfo_lst = []
    delay_lst = []
    for flight in tqdm(flightsource):
        if flight["cancelled"] == 0:
            if prev_flight is not None:
                if (prev_flight['aircraftregistration'] == flight['aircraftregistration']) and (prev_flight['actualarrival'] > flight['actualdeparture']):
                    # Business rule 2: if two flights are overlaping, ignore the first one
                    logging.info(f"BR-21: Ignored overlapping flight {prev_flight['flightid']} ({prev_flight['aircraftregistration']}) overlapping with {flight['flightid']}")
                    flightinfo_lst.pop()
            prev_flight = flight
            # Business rule 1: arrival can not be posterior to departure
            if flight["actualarrival"] <= flight["actualdeparture"]:
                logging.info(f"BR-23: Swapped actualArrival and actualDeparture for flight {flight['flightid']} ({flight['aircraftregistration']})")
                # flight["actualarrival"], flight["actualdeparture"] = flight["actualdeparture"], flight["actualarrival"] si queremos el swap

            FH = abs(flight["actualarrival"] - flight["actualdeparture"]).total_seconds()/3600
            flightinfo_lst.append([flight['aircraftregistration'],build_dateCode(flight['actualdeparture']),FH, 1])

            delay_time = flight['actualdeparture']-flight['scheduleddeparture']
            if (delay_time > pd.Timedelta(minutes=15)) and (delay_time < pd.Timedelta(hours=6)):
                # The flight has been delayed
                delay_lst.append([flight['aircraftregistration'],build_monthCode(flight['actualdeparture']),1,0,delay_time/pd.Timedelta(minutes=1),1])
            else:
                delay_lst.append([flight['aircraftregistration'],build_monthCode(flight['actualdeparture']),0,0,0,1])
        else:
            # The flight has been cancelled
            delay_lst.append([flight['aircraftregistration'],build_monthCode(flight['scheduleddeparture']),0,1,0,1])

        

    flightinfo = pd.DataFrame(flightinfo_lst, columns=['aircraft', 'date', 'FH', 'TO'])
    flightinfo = flightinfo.groupby(['aircraft', 'date'], as_index=False).agg({'FH': 'sum', 'TO': 'sum'})

    delayinfo = pd.DataFrame(delay_lst, columns = ['aircraft', 'date', 'DYR', 'CNR', 'ADD', 'TO'])
    delayinfo = delayinfo.groupby(['aircraft', 'date'], as_index=False).agg({'DYR': 'sum', 'CNR': 'sum', 'ADD': 'sum', 'TO': 'sum'})
    #TODO: how to obtain TO for a certain month and aircraft
    delayinfo['TDR'] = 100-((delayinfo['CNR']+delayinfo['DYR'])/delayinfo['TO'])*100
    delayinfo['DYR'] = delayinfo['DYR']/delayinfo['TO']*100
    delayinfo['CNR'] = delayinfo['CNR']/delayinfo['TO']*100
    # TODO: add and compute TDR
    print(flightinfo.head())
    print(delayinfo.head())
    return flightinfo, delayinfo

def extractADOS():
    # ADOS, ADOSS, ADOSU
    ADO_lst = []
    for maint in tqdm(manteinancesource):
        #Converting days & hours to days with decimals
        maint_H = (maint['scheduledarrival']-maint['scheduleddeparture'])/pd.Timedelta(days=1)
        if maint['programmed'] == 1:
            #The date corresponds to the departure
            #If programmed, then it counts as ADOSS
            ADO_lst.append([maint['aircraftregistration'], build_monthCode(maint['scheduleddeparture']), 
                            maint_H, maint_H, 0])
        else:
            #If not programmed, then it counts as ADOSU
            ADO_lst.append([maint['aircraftregistration'], build_monthCode(maint['scheduleddeparture']), 
                            maint_H, 0, maint_H])
    ADO = pd.DataFrame(ADO_lst, columns=['aircraft', 'date', 'ADOS', 'ADOSS', 'ADOSU'])
    #TODO: ara mateix date està només en mesos, com ho afegim a la taula de dates, que inclou els dies?
    ADO = ADO.groupby(['aircraft', 'date'], as_index=False).agg({'ADOS': 'sum', 'ADOSS': 'sum', 'ADOSU': 'sum'})
    ADO['ADIS'] = 365-ADO['ADOS']
    print(ADO.head())
    return ADO

def extract_logbook(FH):
    FH = FH.copy()
    FH["date"] = pd.to_datetime(FH["date"], format="%Y-%m-%d")
    FH['date'] = FH['date'].apply(build_monthCode) #applies the change row by row
    FH = FH.groupby(['aircraft', 'date'], as_index=False).agg({'FH': 'sum', 'TO': 'sum'})

    reports_lst = [] # aircraft, date, pirep count, marep count
    for report in tqdm(logbooksource):
        if report['reporteurclass'] == 'MAREP':
            reports_lst.append([report['aircraftregistration'], build_monthCode(report['executiondate']), 0, 1, report['reporteurid']])
        else:
            reports_lst.append([report['aircraftregistration'], build_monthCode(report['executiondate']), 1, 0, report['reporteurid']])
    reports = pd.DataFrame(reports_lst, columns=['aircraft', 'date', 'MR', 'PR', 'reporteurid'])


    personnel_lst = list(personnelsource)
    personnel = pd.DataFrame(personnel_lst[1:], columns=personnel_lst[0])
    personnel['reporteurid'] = personnel['reporteurid'].apply(int)    
    reports = pd.merge(reports, personnel)
    reports = reports.groupby(['aircraft', 'date'], as_index=False).agg({'MR': 'sum', 'PR': 'sum'})
    reports['R'] = reports['MR'] + reports['PR']
    print(reports)
    reports_date = pd.merge(reports, FH)
    reports_date['RRh'] = 1000*reports_date['R']/reports_date['FH']
    reports_date['RRc'] = 100*reports_date['R']/reports_date['TO']
    reports_date['PRRh'] = 1000*reports_date['PR']/reports_date['FH']
    reports_date['PRRc'] = 100*reports_date['PR']/reports_date['TO']
    reports_date['MRRh'] = 1000*reports_date['MR']/reports_date['FH']
    reports_date['MRRc'] = 100*reports_date['MR']/reports_date['TO']
    print(reports_date[['aircraft', 'date', 'RRh', 'RRc', 'PRRh', 'PRRc', 'MRRh', 'MRRc']])
    # TODO: sus output for MRR's

    # TODO: compute MRRh and MRRc for aircraft and airport
    reports_airport = reports.groupby(['aircraft', 'airport'], as_index=False)
    print(reports_airport)
    return reports
    

airdim = create_dim_aircraft()
# TODO:rule 3: Check if aircraft registration in airdim set
airdimset = set(airdim['aircraft'])
timedim = create_dim_time()
FH, DYR = extract_flight()
ADOS = extractADOS()
RR = extract_logbook(FH)


#####################################################################################################

from dw import DW
import duckdb

dw = DW(create=True)
con = duckdb.connect('dw.duckdb')
con = dw.conn_duckdb
con.register('timedim', timedim)
con.sql("INSERT INTO dim_date BY NAME SELECT * FROM timedim")
con.register('airdim', airdim)
con.sql("INSERT INTO dim_aircraft BY NAME SELECT * FROM airdim")

con.register('fact_util', FH)
con.sql("INSERT INTO fact_utilization BY NAME SELECT * FROM fact_util")
#TODO: anadir ADOSS, ADOSU a dw.py


byyear = con.sql("""SELECT
  a.aircraft,
  a.model,
  a.manufacturer,
  d.day,
  d.month,
  d.year,
  SUM(f.FH) AS FH_hours,
  SUM(f.TO) AS TO_count
FROM fact_utilization f, dim_date d, dim_aircraft a
where f.date = d.date and f.aircraft = a.aircraft
GROUP BY ROLLUP(a.manufacturer, a.model, a.aircraft, d.year, d.month, d.day)
ORDER BY a.manufacturer, a.model, a.aircraft, d.year, d.month, d.day""")
print("YEAR")
print(byyear)
