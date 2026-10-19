"""Sostituto di prova del client Baserow del portale: i dati stanno in memoria (vedi tests/baserow_finto.py)."""

BASEROW_URL = "http://baserow.test"
HEADERS = {"Authorization": "Token prova"}
NEGOZI = []


def get_table_rows(table_id):
    return {"results": NEGOZI}


def get_table_rows_named(table_id):
    return {"results": []}


def create_row(table_id, data):
    raise NotImplementedError


def update_row(table_id, row_id, data):
    raise NotImplementedError


def delete_row(table_id, row_id):
    raise NotImplementedError


def upload_user_file(f):
    return {"name": f"up_{f.name}", "visible_name": f.name}
