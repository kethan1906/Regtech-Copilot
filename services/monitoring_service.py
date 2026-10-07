"""Batch monitoring: compute per-transaction context in SQL, apply the rules,
and persist the flagged results in the `alerts` table."""
from __future__ import annotations

import json
import sqlite3

from services.rule_engine import RuleConfig, evaluate_transaction


def _context_query(rules: RuleConfig) -> str:
    # Frame bounds are cast to int and inlined: SQLite requires constant frame offsets.
    lookback = int(rules.lookback_steps)
    pass_through = int(rules.pass_through_steps)
    return f"""
        SELECT
            t.transaction_id,
            t.transaction_type,
            t.amount,
            t.old_balance_origin,
            COUNT(*) OVER (
                PARTITION BY t.origin_account
                ORDER BY t.step
                RANGE BETWEEN {lookback} PRECEDING AND 1 PRECEDING
            ) AS recent_count,
            EXISTS (
                SELECT 1 FROM transactions i
                WHERE i.destination_account = t.origin_account
                  AND i.transaction_type = 'TRANSFER'
                  AND i.step BETWEEN t.step - {pass_through} AND t.step
                  AND i.transaction_id <> t.transaction_id
            ) AS inbound_transfer_recent
        FROM transactions t
    """


def run_monitoring(connection: sqlite3.Connection, rules: RuleConfig | None = None) -> dict:
    """Re-evaluate every transaction and replace the alerts table. Idempotent."""
    rules = rules or RuleConfig()
    scanned = 0
    max_id = 0
    alerts = []

    for row in connection.execute(_context_query(rules)):
        scanned += 1
        max_id = max(max_id, row["transaction_id"])
        result = evaluate_transaction(
            row,
            {
                "recent_count": row["recent_count"],
                "inbound_transfer_recent": bool(row["inbound_transfer_recent"]),
            },
            rules,
        )
        if result["flagged"]:
            alerts.append(
                (
                    row["transaction_id"],
                    result["risk_level"],
                    json.dumps(result["rule_codes"]),
                    json.dumps(result["reasons"]),
                )
            )

    with connection:  # one atomic transaction: delete + insert + run log
        connection.execute("DELETE FROM alerts")
        connection.executemany(
            "INSERT INTO alerts (transaction_id, risk_level, rule_codes, reasons) "
            "VALUES (?, ?, ?, ?)",
            alerts,
        )
        connection.execute(
            "INSERT INTO monitoring_runs "
            "(transactions_scanned, alerts_created, max_transaction_id, rule_config) "
            "VALUES (?, ?, ?, ?)",
            (scanned, len(alerts), max_id, json.dumps(rules.as_dict())),
        )

    return {"transactions_scanned": scanned, "alerts_created": len(alerts)}
