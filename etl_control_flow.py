from dw import DW
import extract
import transform
import load


if __name__ == '__main__':
    dw = DW(create=True)
    print("CREATED DW")
    # TODO: Write the control flow
    raw_data = extract.run_all_sources()
    print("GOT RAW DATA")
    transformed_data = transform.run_all_transformations(raw_data)
    print("GOT TRANSFORMED TABLES")
    #print(transformed_data)
    load.run_all_loads(dw, transformed_data)
    print("LOADED THEM INTO DUCKDB")
    #print(dw.query_test())
    dw.close()
