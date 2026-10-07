"""Summary statistics and CSV export of flagged transactions."""
from __future__ import annotations

import csv
import io
import json
import sqlite3

from services.rule_engine import RULE_DESCRIPTIONS

CSV_COLUMNS = [
    "alert_id", "transaction_id", "step", "type", "amount",
    "origin_account", "destination_account", "risk_level", "rules", "reasons",
]


def build_summary(connection: sqlite3.Connection) -> dict:
    total = connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    by_risk = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    for r in connection.execute("SELECT risk_level, COUNT(*) AS n FROM alerts GROUP BY risk_level"):
        by_risk[r["risk_level"]] = r["n"]
    flagged = by_risk["MEDIUM"] + by_risk["HIGH"]
    by_risk["LOW"] = total - flagged

    by_rule = {code: 0 for code in RULE_DESCRIPTIONS}
    for r in connection.execute(
        "SELECT j.value AS code, COUNT(*) AS n FROM alerts, json_each(alerts.rule_codes) j "
        "GROUP BY j.value"
    ):
        by_rule[r["code"]] = r["n"]

    flagged_amount = connection.execute(
        "SELECT COALESCE(SUM(t.amount), 0) FROM alerts a "
        "JOIN transactions t ON t.transaction_id = a.transaction_id"
    ).fetchone()[0]

    top_accounts = [
        {"account": r["origin_account"], "alerts": r["n"]}
        for r in connection.execute(
            "SELECT t.origin_account, COUNT(*) AS n FROM alerts a "
            "JOIN transactions t ON t.transaction_id = a.transaction_id "
            "GROUP BY t.origin_account ORDER BY n DESC, t.origin_account LIMIT 5"
        )
    ]

    run = connection.execute(
        "SELECT * FROM monitoring_runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    last_run = None
    unmonitored = total
    if run:
        unmonitored = connection.execute(
            "SELECT COUNT(*) FROM transactions WHERE transaction_id > ?",
            (run["max_transaction_id"],),
        ).fetchone()[0]
        last_run = {
            "run_at": run["run_at"],
            "transactions_scanned": run["transactions_scanned"],
            "alerts_created": run["alerts_created"],
            "rule_config": json.loads(run["rule_config"]),
        }

    return {
        "total_transactions": total,
        "flagged_transactions": flagged,
        "by_risk_level": by_risk,
        "by_rule": by_rule,
        "rule_descriptions": RULE_DESCRIPTIONS,
        "flagged_amount_total": flagged_amount,
        "top_origin_accounts": top_accounts,
        "unmonitored_transactions": unmonitored,
        "last_monitoring_run": last_run,
    }


def _safe_cell(value):
    """Neutralise spreadsheet formula injection in text cells."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def flagged_csv(connection: sqlite3.Connection, risk_level: str | None = None) -> str:
    sql = (
        "SELECT a.alert_id, t.transaction_id, t.step, t.transaction_type, t.amount, "
        "t.origin_account, t.destination_account, a.risk_level, a.rule_codes, a.reasons "
        "FROM alerts a JOIN transactions t ON t.transaction_id = a.transaction_id"
    )
    params: list = []
    if risk_level in ("MEDIUM", "HIGH"):
        sql += " WHERE a.risk_level = ?"
        params.append(risk_level)
    sql += " ORDER BY CASE a.risk_level WHEN 'HIGH' THEN 0 ELSE 1 END, t.amount DESC"

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for r in connection.execute(sql, params):
        writer.writerow(
            [
                r["alert_id"], r["transaction_id"], r["step"],
                _safe_cell(r["transaction_type"]), r["amount"],
                _safe_cell(r["origin_account"]), _safe_cell(r["destination_account"]),
                r["risk_level"],
                "; ".join(json.loads(r["rule_codes"])),
                "; ".join(json.loads(r["reasons"])),
            ]
        )
    return buffer.getvalue()
