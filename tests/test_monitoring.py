"""The SQL monitoring pass must agree with an independent brute-force implementation."""
import csv
import json

import config
from services.monitoring_service import run_monitoring
from services.rule_engine import RuleConfig, evaluate_transaction


def reference_results(rules: RuleConfig):
    """Naive O(n^2) Python version, written separately from the SQL implementation."""
    with open(config.SAMPLE_CSV_PATH, newline="") as fh:
        rows = [
            {
                "step": int(r["step"]), "transaction_type": r["type"], "amount": float(r["amount"]),
                "origin": r["nameOrig"], "dest": r["nameDest"],
                "old_balance_origin": float(r["oldbalanceOrg"]),
            }
            for r in csv.DictReader(fh)
        ]
    out = {}
    for i, t in enumerate(rows, start=1):  # transaction_id == insertion order
        recent = sum(
            1 for o in rows
            if o["origin"] == t["origin"] and t["step"] - rules.lookback_steps <= o["step"] < t["step"]
        )
        inbound = any(
            o["dest"] == t["origin"] and o["transaction_type"] == "TRANSFER"
            and t["step"] - rules.pass_through_steps <= o["step"] <= t["step"] and o is not t
            for o in rows
        )
        res = evaluate_transaction(
            t, {"recent_count": recent, "inbound_transfer_recent": inbound}, rules
        )
        if res["flagged"]:
            out[i] = (res["risk_level"], res["rule_codes"])
    return out


def test_sql_monitoring_matches_reference(demo_db):
    conn, _ = demo_db
    expected = reference_results(RuleConfig())
    actual = {
        r["transaction_id"]: (r["risk_level"], json.loads(r["rule_codes"]))
        for r in conn.execute("SELECT * FROM alerts")
    }
    assert actual == expected
    assert len(actual) > 0


def test_every_rule_fires_on_sample_data(demo_db):
    conn, _ = demo_db
    codes = {
        r[0] for r in conn.execute("SELECT DISTINCT j.value FROM alerts, json_each(alerts.rule_codes) j")
    }
    assert codes == {"HIGH_VALUE", "REPEATED_ACTIVITY", "ACCOUNT_DRAINED", "RAPID_PASS_THROUGH"}


def test_monitoring_is_idempotent(demo_db):
    conn, _ = demo_db
    before = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    run_monitoring(conn)
    after = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert before == after
    assert conn.execute("SELECT COUNT(*) FROM monitoring_runs").fetchone()[0] == 2


def test_lookback_window_edges(empty_db):
    conn, _ = empty_db
    rows = [  # same origin A: steps 76 (inside window of 100), 75 (outside), 100 (same step, excluded)
        (76, "PAYMENT", 10, "A", 1000, 990, "M1", 0, 10),
        (75, "PAYMENT", 10, "A", 1000, 990, "M2", 0, 10),
        (99, "PAYMENT", 10, "A", 1000, 990, "M3", 0, 10),
        (100, "PAYMENT", 10, "A", 1000, 990, "M4", 0, 10),
        (100, "PAYMENT", 10, "A", 1000, 990, "M5", 0, 10),
    ]
    conn.executemany(
        "INSERT INTO transactions (step, transaction_type, amount, origin_account, old_balance_origin,"
        " new_balance_origin, destination_account, old_balance_dest, new_balance_dest)"
        " VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    run_monitoring(conn, RuleConfig(repeated_count=2, lookback_steps=24))
    flagged = {r["transaction_id"] for r in conn.execute("SELECT transaction_id FROM alerts")}
    # step 99 sees steps 75 and 76 (window [75,98]) -> 2; the two step-100 rows see 76 and 99
    # (window [76,99]; step 75 is excluded; each other's step 100 is excluded) -> 2 each
    assert flagged == {3, 4, 5}
    # With a threshold of 3, step 75 being wrongly included would flag the step-100 rows.
    run_monitoring(conn, RuleConfig(repeated_count=3, lookback_steps=24))
    assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 0


def test_unmonitored_rows_tracked(demo_db):
    conn, _ = demo_db
    from services.report_service import build_summary
    assert build_summary(conn)["unmonitored_transactions"] == 0
    conn.execute(
        "INSERT INTO transactions (step, transaction_type, amount, origin_account, destination_account)"
        " VALUES (1, 'PAYMENT', 5, 'X', 'Y')")
    conn.commit()
    assert build_summary(conn)["unmonitored_transactions"] == 1
