import os
import sys
import duckdb  # https://duckdb.org
import pygrametl  # https://pygrametl.org
from pygrametl.tables import CachedDimension, SnowflakedDimension, FactTable


duckdb_filename = 'dw.duckdb'


class DW:
    def __init__(self, create=False):
        if create and os.path.exists(duckdb_filename):
            os.remove(duckdb_filename)
        try:
            self.conn_duckdb = duckdb.connect(duckdb_filename)
            print("Connection to the DW created successfully")
        except duckdb.Error as e:
            print(f"Unable to connect to DuckDB database '{duckdb_filename}':", e)
            sys.exit(1)

        if create:
            try:
                self._create_schema()
                print("DW schema created successfully")
            except duckdb.Error as e:
                print("Error creating the DW tables:", e)
                sys.exit(2)

        # Link DuckDB and pygrametl
        self.conn_pygrametl = pygrametl.ConnectionWrapper(self.conn_duckdb)
        self._declare_tables()
        # ======================================================================================================= Dimension and fact table objects

    def _create_schema(self):
        self.conn_duckdb.execute("""
        CREATE TABLE dim_date_day (
            date DATE PRIMARY KEY,
            day INTEGER,
            month INTEGER,
            year INTEGER
        );
        CREATE TABLE dim_date_month (
            date TEXT PRIMARY KEY,
            month INTEGER,
            year INTEGER
        );
        CREATE TABLE dim_plane (
            aircraft TEXT PRIMARY KEY,
            model TEXT,
            manufacturer TEXT
        );

        CREATE TABLE dim_airport (
            airport TEXT PRIMARY KEY
        );

        CREATE TABLE fact_flight_daily (
            aircraft TEXT,
            date DATE,
            PRIMARY KEY (aircraft, date),
            FH DOUBLE,  -- Flight Hours
            "TO" INTEGER, -- Take-Offs
            FOREIGN KEY (aircraft) REFERENCES dim_plane(aircraft),
            FOREIGN KEY (date) REFERENCES dim_date_day(date)

        );

        CREATE TABLE fact_flight_monthly (
            aircraft TEXT,
            date TEXT,
            ADIS DOUBLE,
            ADOS DOUBLE,
            ADOSS DOUBLE,
            ADOSU DOUBLE,
            DYR DOUBLE,
            CNR DOUBLE,
            TDR DOUBLE,
            ADD DOUBLE,
            "TO" INTEGER,
            PRIMARY KEY (aircraft, date),
            FOREIGN KEY (aircraft) REFERENCES dim_plane(aircraft),
            FOREIGN KEY (date) REFERENCES dim_date_month(date)
        );

        CREATE TABLE fact_reports_monthly (
            aircraft TEXT,
            date TEXT,
            RRh DOUBLE,
            RRc DOUBLE,
            PRRh DOUBLE,
            PRRc DOUBLE,
            MRRh DOUBLE,
            MRRc DOUBLE,
            PRIMARY KEY (aircraft, date),
            FOREIGN KEY (aircraft) REFERENCES dim_plane(aircraft),
            FOREIGN KEY (date) REFERENCES dim_date_month(date)
        );

        CREATE TABLE fact_reports_airport (
            aircraft TEXT,
            airport TEXT,
            MRRh DOUBLE,
            MRRc DOUBLE,
            PRIMARY KEY (aircraft, airport),
            FOREIGN KEY (aircraft) REFERENCES dim_plane(aircraft),
            FOREIGN KEY (airport) REFERENCES dim_airport(airport)
        );
        """)

    # =========================================================================================================
    def _declare_tables(self):
        # Dimension tables
        self.dim_date_day = CachedDimension(
            name='dim_date_day',
            key='date',
            attributes=['date', 'day', 'month', 'year'],
            lookupatts=['date']
        )

        self.dim_date_month = CachedDimension(
            name='dim_date_month',
            key='date',
            attributes=['date', 'month', 'year'],
            lookupatts=['date']
        )

        self.dim_plane = CachedDimension(
            name='dim_plane',
            key='aircraft',
            attributes=['aircraft', 'model', 'manufacturer'],
            lookupatts=['aircraft']
        )

        self.dim_airport = CachedDimension(
            name='dim_airport',
            key='airport',
            attributes=['airport'],
            lookupatts=['airport']
        )

        # Fact tables
        self.fact_flight_daily = FactTable(
            name='fact_flight_daily',
            keyrefs=['aircraft', 'date'],
            measures=['FH', 'TO']
        )

        self.fact_flight_monthly = FactTable(
            name='fact_flight_monthly',
            keyrefs=['aircraft', 'date'],
            measures=[
                'ADIS', 'ADOS', 'ADOSS', 'ADOSU',
                'DYR', 'CNR', 'TDR', 'ADD', 'TO'
            ]
        )

        self.fact_reports_monthly = FactTable(
            name='fact_reports_monthly',
            keyrefs=['aircraft', 'date'],
            measures=['RRh', 'RRc', 'PRRh', 'PRRc', 'MRRh', 'MRRc']
        )

        self.fact_reports_airport = FactTable(
            name='fact_reports_airport',
            keyrefs=['aircraft', 'airport'],
            measures=['MRRh', 'MRRc']
        )


    # TODO: Rewrite the queries exemplified in "extract.py"

    def query_test(self):
        result = self.conn_duckdb.execute("""SELECT
        a.aircraft,
        a.model,
        a.manufacturer,
        d.day,
        d.month,
        d.year,
        SUM(f.FH) AS FH_hours,
        SUM(f.TO) AS TO_count
        FROM fact_flight_daily f, dim_date_day d, dim_plane a
        where f.date = d.date and f.aircraft = a.aircraft
        GROUP BY ROLLUP(a.manufacturer, a.model, a.aircraft, d.year, d.month, d.day)
        ORDER BY a.manufacturer, a.model, a.aircraft, d.year, d.month, d.day""").fetchall()
        return result

    def query_utilization(self):
        result = self.conn_duckdb.execute("""
            SELECT ...
            """).fetchall()
        return result

    def query_reporting(self):
        result = self.conn_duckdb.execute("""
            SELECT ...
            """).fetchall()
        return result

    def query_reporting_per_role(self):
        result = self.conn_duckdb.execute("""
            SELECT ...
            """).fetchall()
        return result

    def close(self):
        self.conn_pygrametl.commit()
        self.conn_pygrametl.close()
