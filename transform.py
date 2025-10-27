from tqdm import tqdm
import logging
import pandas as pd


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


## Aircraft
def create_dim_aircraft(manufacturerinfosource):
    aircraft_lst = []
    for aircraft in manufacturerinfosource:
        aircraft_lst.append([aircraft['aircraft_reg_code'], aircraft['aircraft_model'], aircraft['aircraft_manufacturer']])
    aircraftdim = pd.DataFrame(aircraft_lst, columns=['aircraft', 'model', 'manufacturer'])
    return aircraftdim

## Airport
def create_dim_airport(personnelsource):
    personnel_lst = list(personnelsource)
    personnel = pd.DataFrame(personnel_lst[1:], columns=personnel_lst[0])
    personnel['reporteurid'] = personnel['reporteurid'].apply(int)
    return personnel


## Daily
def create_dim_daily():
    time_lst = []
    for date in pd.date_range("2023-01-01", "2024-12-31"):
        time_lst.append([date, date.day, date.month, date.year])
    timedim = pd.DataFrame(time_lst, columns=['date', 'day', 'month', 'year'])
    return timedim

## Monthly
def create_dim_monthly():
    time_lst = []
    for date in pd.date_range("2023-01-01", "2024-12-31", freq="MS"):
        time_lst.append([build_monthCode(date), date.month, date.year])
    timedim = pd.DataFrame(time_lst, columns=['date', 'month', 'year'])
    return timedim


def transform_flights(flightsource, manteinancesource):
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

    flightdaily = pd.DataFrame(flightinfo_lst, columns=['aircraft', 'date', 'FH', 'TO'])
    flightdaily = flightdaily.groupby(['aircraft', 'date'], as_index=False).agg({'FH': 'sum', 'TO': 'sum'})

    delayinfo = pd.DataFrame(delay_lst, columns = ['aircraft', 'date', 'DYR', 'CNR', 'ADD', 'TO'])
    delayinfo = delayinfo.groupby(['aircraft', 'date'], as_index=False).agg({'DYR': 'sum', 'CNR': 'sum', 'ADD': 'sum', 'TO': 'sum'})
    delayinfo['TDR'] = 100-((delayinfo['CNR']+delayinfo['DYR'])/delayinfo['TO'])*100
    delayinfo['DYR'] = delayinfo['DYR']/delayinfo['TO']*100
    delayinfo['CNR'] = delayinfo['CNR']/delayinfo['TO']*100

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
    ADO = ADO.groupby(['aircraft', 'date'], as_index=False).agg({'ADOS': 'sum', 'ADOSS': 'sum', 'ADOSU': 'sum'})
    ADO['ADIS'] = 365-ADO['ADOS']

    flightmonthly = pd.merge(ADO, delayinfo, on= ["aircraft", "date"])

    return flightdaily[['aircraft', 'date', 'FH', 'TO']], flightmonthly[['aircraft', 'date', 'ADIS', 'ADOS', 'ADOSS', 'ADOSU', 'DYR', 'CNR', 'TDR', 'ADD', 'TO']]

def transform_logbook(FH, postflight, personnel, airdimset):
    # FH = FH.copy()
    FH["date"] = pd.to_datetime(FH["date"], format="%Y-%m-%d")
    FH['date'] = FH['date'].apply(build_dateCode) #applies the change row by row
    # FH = FH.groupby(['aircraft', 'date'], as_index=False).agg({'FH': 'sum', 'TO': 'sum'})

    reports_lst = [] # aircraft, date, pirep count, marep count
    for report in tqdm(postflight):
        # business rule 3: Check if aircraft registration in airdim set
        if report['aircraftregistration'] in airdimset:
            if report['reporteurclass'] == 'MAREP':
                reports_lst.append([report['aircraftregistration'], build_dateCode(report['reportingdate']), 1, 0, report['reporteurid']])
            else:
                reports_lst.append([report['aircraftregistration'], build_dateCode(report['reportingdate']), 0, 1, report['reporteurid']])
        else:
            logging.info(f"BR-3: {report['aircraftregistration']} is not on the aircraft dimension. Ignoring row {report} ")

    reports = pd.DataFrame(reports_lst, columns=['aircraft', 'date', 'MR', 'PR', 'reporteurid'])
    reports2 = reports.groupby(['aircraft', 'date'], as_index=False).agg({'MR': 'sum', 'PR': 'sum'})
    print("REPORTS 2")
    print(reports2)
    print("FH") 
    print(FH)
    print(type(reports2['date']))
    print(type(FH['date']))
    
    reports_date = pd.merge(reports2, FH)
    reports_date2 = pd.merge(reports, FH)
    print(reports_date)

    reports_airport = pd.merge(reports_date2, personnel, on="reporteurid")



    reports_airport = reports_airport.groupby(['aircraft', 'airport'], as_index=False).agg({'MR': 'sum', 'PR': 'sum', 'FH': 'sum', 'TO': 'sum'})

    reports_date["date"] = pd.to_datetime(reports_date["date"], format="%Y-%m-%d")
    reports_date['date'] = reports_date['date'].apply(build_monthCode) #applies the change row by row
    reports_date = reports_date.groupby(['aircraft', 'date'], as_index=False).agg({'MR': 'sum', 'PR': 'sum', 'FH': 'sum', 'TO': 'sum'})

    return reports_date[['aircraft', 'date', 'MR', 'PR', 'FH', 'TO']], reports_airport[['aircraft', 'airport', 'MR', 'FH', 'TO']]
"""
airdim = create_dim_aircraft()
# TODO:rule 3: Check if aircraft registration in airdim set
airdimset = set(airdim['aircraft'])
timedim = create_dim_time()
FH, DYR = extract_flight()
ADOS = extractADOS()
RR = extract_logbook(FH)
"""


def run_all_transformations(raw_data: dict):
    airdim = create_dim_aircraft(raw_data["manufacturerinfo"])
    airport = create_dim_airport(raw_data["personnel"])
    dailydim = create_dim_daily()
    monthlydim = create_dim_monthly()

    airdimset = set(airdim['aircraft'])

    flight_daily, flight_monthly = transform_flights(raw_data['flights'], raw_data['maintenance'])
    reports_monthly, reports_airport = transform_logbook(flight_daily, raw_data['postflight'],airport, airdimset)
    """print("ALL TABLES\n++++++++++++++++++++++++++++++++++++++")
    print(airdim)
    print(airport)
    print(dailydim)
    print(monthlydim)
    print(flight_daily)
    print(flight_monthly)
    print(reports_monthly)
    print(reports_airport)"""
    return {"aircraft": airdim,
            "airport": pd.DataFrame({'airport': airport["airport"].unique()}),
            "daily": dailydim,
            "monthly": monthlydim,
            'flight_daily': flight_daily,
            'flight_monthly': flight_monthly,
            'reports_monthly': reports_monthly,
            'reports_airport': reports_airport}
