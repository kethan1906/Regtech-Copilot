"""Pure rule logic: no database access, easy to unit test.

Rules
-----
HIGH_VALUE          amount >= threshold
REPEATED_ACTIVITY   >= N earlier transactions from the same origin account within
                    the look-back window
ACCOUNT_DRAINED     TRANSFER / CASH_OUT that empties (>= ratio of) the origin
                    account's balance, above a minimum amount
RAPID_PASS_THROUGH  CASH_OUT from an account that received a TRANSFER within the
                    last few steps (funds moved in and straight out)

Risk: 0 matched rules -> LOW (not flagged), 1 -> MEDIUM, 2+ -> HIGH.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import config

HIGH_VALUE = "HIGH_VALUE"
REPEATED_ACTIVITY = "REPEATED_ACTIVITY"
ACCOUNT_DRAINED = "ACCOUNT_DRAINED"
RAPID_PASS_THROUGH = "RAPID_PASS_THROUGH"

RULE_DESCRIPTIONS = {
    HIGH_VALUE: "High-value transaction",
    REPEATED_ACTIVITY: "Repeated transaction activity",
    ACCOUNT_DRAINED: "Origin account balance drained",
    RAPID_PASS_THROUGH: "Rapid pass-through (funds received then cashed out)",
}

DRAIN_TYPES = ("TRANSFER", "CASH_OUT")


@dataclass(frozen=True)
class RuleConfig:
    high_value_threshold: float = config.HIGH_VALUE_THRESHOLD
    repeated_count: int = config.REPEATED_TRANSACTION_COUNT
    lookback_steps: int = config.LOOKBACK_STEPS
    drain_ratio: float = config.DRAIN_RATIO
    drain_min_amount: float = config.DRAIN_MIN_AMOUNT
    pass_through_steps: int = config.PASS_THROUGH_STEPS

    def as_dict(self) -> dict:
        return asdict(self)


def evaluate_transaction(transaction, context, rules: RuleConfig | None = None) -> dict:
    """Evaluate one transaction.

    transaction: mapping with amount, transaction_type, old_balance_origin
    context:     mapping with recent_count (int) and inbound_transfer_recent (bool)
    """
    rules = rules or RuleConfig()
    codes: list[str] = []

    amount = transaction["amount"]
    txn_type = transaction["transaction_type"]

    if amount >= rules.high_value_threshold:
        codes.append(HIGH_VALUE)

    if context["recent_count"] >= rules.repeated_count:
        codes.append(REPEATED_ACTIVITY)

    old_balance = transaction["old_balance_origin"]
    if (
        txn_type in DRAIN_TYPES
        and old_balance > 0
        and amount >= rules.drain_min_amount
        and amount >= rules.drain_ratio * old_balance
    ):
        codes.append(ACCOUNT_DRAINED)

    if txn_type == "CASH_OUT" and context["inbound_transfer_recent"]:
        codes.append(RAPID_PASS_THROUGH)

    if not codes:
        return {"flagged": False, "risk_level": "LOW", "rule_codes": [], "reasons": []}

    return {
        "flagged": True,
        "risk_level": "HIGH" if len(codes) >= 2 else "MEDIUM",
        "rule_codes": codes,
        "reasons": [RULE_DESCRIPTIONS[c] for c in codes],
    }
