import duckdb
from tqdm import tqdm


def load_dataframe(con, table_name, df):
    if df is None or df.empty:
        return

    # normalize aircraft codes if present (simple and safe)
    if 'aircraft' in df.columns:
        df = df.copy()
        df['aircraft'] = df['aircraft'].astype(str).str.strip().str.upper()

    # register DataFrame so CREATE TABLE AS SELECT * FROM __tmp WHERE FALSE works
    con.register("__tmp", df)

    # Create table if it doesn’t exist, then append
    con.execute(f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM __tmp WHERE FALSE;")
    con.execute(f"INSERT INTO {table_name} BY NAME SELECT * FROM __tmp;")
    con.unregister("__tmp")

    # make sure inserted rows are visible to following operations
    try:
        con.commit()
    except Exception:
        pass

    print(f"Loaded {len(df)} rows into {table_name}")


def run_all_loads(dw, data_dict):
    con = dw.conn_duckdb
    mapping = {
        "flight_daily": "fact_flight_daily",
        "flight_monthly": "fact_flight_monthly",
        "reports_monthly": "fact_reports_monthly",
        "reports_airport": "fact_reports_airport",
        "aircraft": "dim_plane",
        "airport": "dim_airport",
        "daily": "dim_date_day",
        "monthly": "dim_date_month"
    }
    for key, df in tqdm(data_dict.items(),desc="Loading tables"):
        if key in mapping:
            print(key)
            load_dataframe(con, mapping[key], df)

            result = con.sql(f"""SELECT *
            FROM {mapping[key]}
            """)
            print(key)
            print(result)
            if key == "aircraft":
                result = con.sql(f"""SELECT *
                FROM {mapping[key]} a
                WHERE a.aircraft == 'XY-ACK'
                """)
                print(key)
                print(result)
