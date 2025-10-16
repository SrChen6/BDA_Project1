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
        CREATE TABLE dim_date (
            date DATE PRIMARY KEY,
            day INTEGER,
            month INTEGER,
            year INTEGER
        );

        CREATE TABLE dim_aircraft (
            aircraft TEXT PRIMARY KEY,
            model TEXT,
            manufacturer TEXT
        );

        CREATE TABLE dim_airport (
            airport_id INTEGER PRIMARY KEY,
            airport_code TEXT,
            airport_name TEXT,
            country TEXT
        );

        CREATE TABLE dim_personnel (
            personnel_id INTEGER PRIMARY KEY,
            name TEXT,
            role TEXT, -- 'Pilot' or 'Maintenance'
            airport_id INTEGER,
            FOREIGN KEY (airport_id) REFERENCES dim_airport(airport_id)
        );

        CREATE TABLE fact_utilization (
            aircraft TEXT,
            date DATE,
            FH DOUBLE,  -- Flight Hours
            "TO" INTEGER, -- Take-Offs
            ADIS DOUBLE,
            ADOS DOUBLE,
            DYR DOUBLE,
            CNR DOUBLE,
            PRIMARY KEY (aircraft, date),
            FOREIGN KEY (aircraft) REFERENCES dim_aircraft(aircraft),
            FOREIGN KEY (date) REFERENCES dim_date(date)
        );

        CREATE TABLE fact_reporting (
            report_id INTEGER PRIMARY KEY,
            aircraft TEXT,
            personnel_id INTEGER,
            date DATE,
            RRh DOUBLE,
            RRc DOUBLE,
            PRRh DOUBLE,
            PRRc DOUBLE,
            MRRh DOUBLE,
            MRRc DOUBLE,
            FOREIGN KEY (aircraft) REFERENCES dim_aircraft(aircraft),
            FOREIGN KEY (personnel_id) REFERENCES dim_personnel(personnel_id),
            FOREIGN KEY (date ) REFERENCES dim_date(date )
        );
        """)

    # =========================================================================================================
    def _declare_tables(self):
        self.dim_date = CachedDimension(
            name='dim_date',
            key='date ',
            attributes=['date','day', 'month', 'year'],
            lookupatts=['date']
        )

        self.dim_aircraft = CachedDimension(
            name='dim_aircraft',
            key='aircraft',
            attributes=['registration_code', 'manufacturer_code', 'model', 'manufacturer'],
            lookupatts=['registration_code']
        )

        self.dim_airport = CachedDimension(
            name='dim_airport',
            key='airport_id',
            attributes=['airport_code', 'airport_name', 'country'],
            lookupatts=['airport_code']
        )

        self.dim_personnel = CachedDimension(
            name='dim_personnel',
            key='personnel_id',
            attributes=['name', 'role', 'airport_id'],
            lookupatts=['name']
        )

        self.fact_utilization = FactTable(
            name='fact_utilization',
            keyrefs=['aircraft', 'date '],
            measures=['FH', 'TO', 'ADIS', 'ADOS', 'DYR', 'CNR']
        )

        self.fact_reporting = FactTable(
            name='fact_reporting',
            keyrefs=['aircraft', 'personnel_id', 'date '],
            measures=['RRh', 'RRc', 'PRRh', 'PRRc', 'MRRh', 'MRRc']
        )


    # TODO: Rewrite the queries exemplified in "extract.py"
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
