from openpyxl import Workbook

from app.services.spreadsheets import iter_xlsx_rows


def test_iter_xlsx_rows_skips_blank_rows_after_header(tmp_path):
    workbook = Workbook()
    ws = workbook.active
    ws.title = "Main"
    ws.append(["Relatório de exemplo"])
    ws.append(["Matrícula", "Número", "Data"])
    ws.append([None, None, None])
    ws.append([None, None, None])
    ws.append(["BB-69-TE", 1682, "22/06/2026"])
    ws.append([None, None, None])
    ws.append(["BB-69-TE", 1608, "25/05/2026"])

    path = tmp_path / "sample.xlsx"
    workbook.save(path)

    rows = list(iter_xlsx_rows(path))

    assert len(rows) == 2
    assert rows[0][2] == 5
    assert rows[0][3][0] == "BB-69-TE"
    assert rows[1][2] == 7
    assert rows[1][3][1] == 1608
