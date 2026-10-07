"""Read-side queries used by the REST API."""
from __future__ import annotations

import json
import sqlite3

VALID_RISK_LEVELS = ("LOW", "MEDIUM", "HIGH")


def _filters(risk_level: str | None, flagged_only: bool) -> tuple[str, list]:
    clauses, params = [], []
    if risk_level == "LOW":
        clauses.append("a.alert_id IS NULL")
    elif risk_level in ("MEDIUM", "HIGH"):
        clauses.append("a.risk_level = ?")
        params.append(risk_level)
    if flagged_only:
        clauses.append("a.alert_id IS NOT NULL")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def list_transactions(
    connection: sqlite3.Connection,
    limit: int = 100,
    offset: int = 0,
    risk_level: str | None = None,
    flagged_only: bool = False,
) -> dict:
    where, params = _filters(risk_level, flagged_only)
    base = "FROM transactions t LEFT JOIN alerts a ON a.transaction_id = t.transaction_id " + where

    total = connection.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    rows = connection.execute(
        f"""
        SELECT t.transaction_id, t.step, t.transaction_type, t.amount,
               t.origin_account, t.destination_account,
               a.risk_level, a.reasons, a.rule_codes
        {base}
        ORDER BY t.transaction_id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()

    items = []
    for r in rows:
        flagged = r["risk_level"] is not None
        items.append(
            {
                "id": r["transaction_id"],
                "step": r["step"],
                "type": r["transaction_type"],
                "amount": r["amount"],
                "origin": r["origin_account"],
                "destination": r["destination_account"],
                "flagged": flagged,
                "risk_level": r["risk_level"] or "LOW",
                "reasons": json.loads(r["reasons"]) if flagged else [],
                "rule_codes": json.loads(r["rule_codes"]) if flagged else [],
            }
        )
    return {"transactions": items, "total": total, "limit": limit, "offset": offset}
