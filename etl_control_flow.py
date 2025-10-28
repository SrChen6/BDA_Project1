from dw import DW
import extract
import transform
import load
from logger_setup import log_screen, log_file

if __name__ == '__main__':
    log_screen.info("Initializing DataWarehouse, create = True")
    dw = DW(create=True)
    log_screen.info("DataWarehouse initialized")
    # TODO: Write the control flow
    raw_data = extract.run_all_sources()
    log_screen.info("Extracted raw data from all sources")
    transformed_data = transform.run_all_transformations(raw_data)
    log_screen.info("Transformed table into DW schema")
    #print(transformed_data)
    load.run_all_loads(dw, transformed_data)
    log_screen.info("Loaded ALL tables into duck.db")
    #print(dw.query_test())
    dw.close()
