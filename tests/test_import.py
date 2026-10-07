import pytest

from scripts.import_data import import_transactions

HEADER = "step,type,amount,nameOrig,oldbalanceOrg,newbalanceOrig,nameDest,oldbalanceDest,newbalanceDest\n"


def test_import_valid_csv_and_limit(tmp_path, empty_db):
    conn, _ = empty_db
    f = tmp_path / "t.csv"
    f.write_text(HEADER + "1,PAYMENT,10,C1,100,90,M1,0,10\n2,TRANSFER,20,C2,50,30,C3,0,20\n3,CASH_OUT,5,C1,90,85,C9,0,5\n")
    assert import_transactions(conn, f, limit=2) == 2
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


def test_import_missing_columns(tmp_path, empty_db):
    conn, _ = empty_db
    f = tmp_path / "bad.csv"
    f.write_text("step,type,amount\n1,PAYMENT,10\n")
    with pytest.raises(ValueError, match="missing required columns"):
        import_transactions(conn, f)


def test_import_bad_row_rolls_back(tmp_path, empty_db):
    conn, _ = empty_db
    f = tmp_path / "bad.csv"
    f.write_text(HEADER + "1,PAYMENT,10,C1,100,90,M1,0,10\n2,TRANSFER,oops,C2,50,30,C3,0,20\n")
    with pytest.raises(ValueError, match="line 3"):
        import_transactions(conn, f)
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_sql_is_parameterised(tmp_path, empty_db):
    conn, _ = empty_db
    f = tmp_path / "inj.csv"
    f.write_text(HEADER + "1,PAYMENT,10,\"C1'); DROP TABLE transactions;--\",100,90,M1,0,10\n")
    import_transactions(conn, f)
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
