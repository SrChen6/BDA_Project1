from dw import DW
import extract
import transform
import load


if __name__ == '__main__':
    dw = DW(create=True)

    # TODO: Write the control flow
    raw_data = extract.run_all_sources()
    transformed_data = transform.run_all_transformations(raw_data)
    load.run_all_loads(dw, transformed_data)

    dw.close()
