import csv
import io

import pytest

import config

from app import create_app

N_ROWS = sum(1 for _ in open(config.SAMPLE_CSV_PATH, newline="")) - 1  # minus header


@pytest.fixture()
def client(demo_db):
    _, path = demo_db
    app = create_app(path)
    app.testing = True
    return app.test_client()


def test_index_and_health(client):
    assert client.get("/").status_code == 200
    assert b"transactionTable" in client.get("/").data
    assert client.get("/api/health").get_json() == {"status": "ok"}


def test_transactions_default_and_shape(client):
    body = client.get("/api/transactions").get_json()
    assert body["limit"] == 100 and len(body["transactions"]) == 100 and body["total"] == N_ROWS
    t = body["transactions"][0]
    assert set(t) == {"id", "step", "type", "amount", "origin", "destination",
                      "flagged", "risk_level", "reasons", "rule_codes"}
    assert [x["id"] for x in body["transactions"]] == sorted((x["id"] for x in body["transactions"]), reverse=True)


def test_transactions_pagination_no_overlap(client):
    a = client.get("/api/transactions?limit=10&offset=0").get_json()["transactions"]
    b = client.get("/api/transactions?limit=10&offset=10").get_json()["transactions"]
    assert not {x["id"] for x in a} & {x["id"] for x in b}


def test_filters(client):
    high = client.get("/api/transactions?risk_level=high&limit=1000").get_json()
    assert high["total"] > 0 and all(t["risk_level"] == "HIGH" and t["flagged"] for t in high["transactions"])
    low = client.get("/api/transactions?risk_level=LOW&limit=50").get_json()
    assert all(not t["flagged"] and t["reasons"] == [] for t in low["transactions"])
    flagged = client.get("/api/transactions?flagged_only=true&limit=1000").get_json()
    summary = client.get("/api/reports/summary").get_json()
    assert flagged["total"] == summary["flagged_transactions"]
    assert all(t["reasons"] for t in flagged["transactions"])


@pytest.mark.parametrize(
    "qs",
    ["limit=0", "limit=-5", "limit=abc", "limit=100000", "offset=-1", "risk_level=EXTREME"],
)
def test_invalid_params_return_400(client, qs):
    r = client.get("/api/transactions?" + qs)
    assert r.status_code == 400 and "error" in r.get_json()


def test_alerts_endpoint(client):
    body = client.get("/api/alerts?limit=1000").get_json()
    assert body["total"] == len(body["transactions"]) > 0
    assert all(t["flagged"] for t in body["transactions"])
    assert client.get("/api/alerts?risk_level=LOW").status_code == 400


def test_summary_consistency(client):
    s = client.get("/api/reports/summary").get_json()
    assert s["total_transactions"] == N_ROWS
    assert sum(s["by_risk_level"].values()) == s["total_transactions"]
    assert s["flagged_transactions"] == s["by_risk_level"]["HIGH"] + s["by_risk_level"]["MEDIUM"]
    assert set(s["by_rule"]) == {"HIGH_VALUE", "REPEATED_ACTIVITY", "ACCOUNT_DRAINED", "RAPID_PASS_THROUGH"}
    assert s["last_monitoring_run"]["alerts_created"] == s["flagged_transactions"]
    assert s["unmonitored_transactions"] == 0


def test_csv_export(client):
    r = client.get("/api/reports/flagged.csv")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    assert "attachment" in r.headers["Content-Disposition"]
    rows = list(csv.DictReader(io.StringIO(r.get_data(as_text=True))))
    summary = client.get("/api/reports/summary").get_json()
    assert len(rows) == summary["flagged_transactions"]
    assert rows[0]["risk_level"] == "HIGH"
    only_high = list(csv.DictReader(io.StringIO(client.get("/api/reports/flagged.csv?risk_level=HIGH").get_data(as_text=True))))
    assert len(only_high) == summary["by_risk_level"]["HIGH"]
    assert client.get("/api/reports/flagged.csv?risk_level=LOW").status_code == 400


def test_csv_formula_injection_neutralised(demo_db):
    conn, path = demo_db
    conn.execute(
        "INSERT INTO transactions (step, transaction_type, amount, origin_account, destination_account)"
        " VALUES (1, 'TRANSFER', 500000, '=HYPERLINK(\"http://x\")', 'D')")
    conn.commit()
    from services.monitoring_service import run_monitoring
    run_monitoring(conn)
    app = create_app(path)
    text = app.test_client().get("/api/reports/flagged.csv").get_data(as_text=True)
    assert "'=HYPERLINK" in text
    assert ",=HYPERLINK" not in text


def test_empty_database_is_handled(tmp_path):
    from database.db import get_connection, init_db
    p = tmp_path / "e.db"
    c = get_connection(p); init_db(c); c.close()
    client = create_app(p).test_client()
    assert client.get("/api/transactions").get_json()["total"] == 0
    s = client.get("/api/reports/summary").get_json()
    assert s["total_transactions"] == 0 and s["last_monitoring_run"] is None


def test_unknown_route_json_404_and_headers(client):
    r = client.get("/nope")
    assert r.status_code == 404 and r.get_json() == {"error": "Not found"}
    assert client.get("/api/health").headers["X-Content-Type-Options"] == "nosniff"


def test_csv_upload_imports_and_runs_monitoring(client):
    payload = {
        "file": (io.BytesIO(
            b"step,type,amount,nameOrig,oldbalanceOrg,newbalanceOrig,nameDest,oldbalanceDest,newbalanceDest\n"
            b"1,TRANSFER,250000,C1,300000,50000,C2,0,250000\n"
            b"2,PAYMENT,25,C3,100,75,M1,0,25\n"
        ), "transactions.csv")
    }
    r = client.post("/api/import", data=payload, content_type="multipart/form-data")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["imported_transactions"] == 2
    assert body["monitoring"]["transactions_scanned"] == 2592 + 2
    assert body["monitoring"]["alerts_created"] > 0


def test_csv_upload_replace_replaces_existing_data(client):
    payload = {
        "file": (io.BytesIO(
            b"step,type,amount,nameOrig,oldbalanceOrg,newbalanceOrig,nameDest,oldbalanceDest,newbalanceDest\n"
            b"1,PAYMENT,25,C3,100,75,M1,0,25\n"
        ), "replacement.csv"),
        "replace": "true",
    }
    r = client.post("/api/import", data=payload, content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json()["replaced_existing_data"] is True
    assert client.get("/api/reports/summary").get_json()["total_transactions"] == 1


def test_csv_upload_rejects_invalid_file(client):
    payload = {"file": (io.BytesIO(b"hello"), "transactions.txt")}
    r = client.post("/api/import", data=payload, content_type="multipart/form-data")
    assert r.status_code == 400
    assert "CSV" in r.get_json()["error"]


def test_csv_upload_rejects_missing_columns(client):
    payload = {"file": (io.BytesIO(b"step,type,amount\n1,PAYMENT,10\n"), "bad.csv")}
    r = client.post("/api/import", data=payload, content_type="multipart/form-data")
    assert r.status_code == 400
    assert "missing required columns" in r.get_json()["error"]
