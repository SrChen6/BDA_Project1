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
            MR DOUBLE,
            PR DOUBLE,
            FH DOUBLE,
            "TO" INTEGER,
            PRIMARY KEY (aircraft, date),
            FOREIGN KEY (aircraft) REFERENCES dim_plane(aircraft),
            FOREIGN KEY (date) REFERENCES dim_date_month(date)
        );

        CREATE TABLE fact_reports_airport (
            aircraft TEXT,
            airport TEXT,
            MR DOUBLE,
            FH DOUBLE,
            "TO" INTEGER,
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
            measures=['MR', 'PR', 'FH', 'TO']
        )

        self.fact_reports_airport = FactTable(
            name='fact_reports_airport',
            keyrefs=['aircraft', 'airport'],
            measures=['MR', 'FH', 'TO']
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
        WITH yearly_per_aircraft AS (
            SELECT
                d.year,
                f.aircraft,
                SUM(f.FH) AS total_FH_aircraft,
                SUM(f.TO) AS total_TO_aircraft
            FROM fact_flight_daily f, dim_date_day d
            WHERE f.date = d.date
            GROUP BY d.year, f.aircraft
        )
        SELECT
            a.manufacturer,
            y.year,
            AVG(total_FH_aircraft) AS avg_FH_per_aircraft,
            AVG(total_TO_aircraft) AS avg_TO_per_aircraft
        FROM yearly_per_aircraft y, dim_plane a
        WHERE y.aircraft = a.aircraft
        GROUP BY manufacturer, year
        ORDER BY manufacturer, year;
        """).fetchall()
        return result

    def query_reporting(self):
        result = self.conn_duckdb.execute("""
            SELECT
            a.manufacturer,
            d.year,
            SUM(f.RRh) AS RRh,
            SUM(f.RRc) AS RRc
            FROM fact_reports_monthly f, dim_date_month d, dim_plane a
            where f.date = d.date and f.aircraft = a.aircraft
            GROUP BY a.manufacturer, d.year
            ORDER BY a.manufacturer, d.year
            """).fetchall()
        return result

    def query_reporting_per_role(self):
        result = self.conn_duckdb.execute("""
            SELECT
            a.manufacturer,
            d.year,
            SUM(f.PRRh) AS PIREP_RRh,
            SUM(f.MRRh) AS MAREP_RRh,
            SUM(f.PRRc) AS PIREP_RRc,
            SUM(f.MRRc) AS MAREP_RRc
            FROM fact_reports_monthly f, dim_date_month d, dim_plane a
            where f.date = d.date and f.aircraft = a.aircraft
            GROUP BY a.manufacturer, d.year
            ORDER BY a.manufacturer, d.year
            """).fetchall()
        return result

    def close(self):
        self.conn_pygrametl.commit()
        self.conn_pygrametl.close()
