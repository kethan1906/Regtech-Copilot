import pytest

from services.rule_engine import (
    ACCOUNT_DRAINED, HIGH_VALUE, RAPID_PASS_THROUGH, REPEATED_ACTIVITY,
    RuleConfig, evaluate_transaction,
)

RULES = RuleConfig(
    high_value_threshold=200000, repeated_count=3, lookback_steps=24,
    drain_ratio=0.99, drain_min_amount=10000, pass_through_steps=6,
)
QUIET = {"recent_count": 0, "inbound_transfer_recent": False}


def txn(amount=100.0, kind="PAYMENT", old=100000.0):
    return {"amount": amount, "transaction_type": kind, "old_balance_origin": old}


def test_no_rules_matched_is_low_and_not_flagged():
    r = evaluate_transaction(txn(), QUIET, RULES)
    assert r == {"flagged": False, "risk_level": "LOW", "rule_codes": [], "reasons": []}


def test_high_value_boundary():
    assert HIGH_VALUE in evaluate_transaction(txn(200000), QUIET, RULES)["rule_codes"]
    assert HIGH_VALUE not in evaluate_transaction(txn(199999.99), QUIET, RULES)["rule_codes"]


def test_repeated_activity_boundary():
    ctx = lambda n: {"recent_count": n, "inbound_transfer_recent": False}  # noqa: E731
    assert REPEATED_ACTIVITY not in evaluate_transaction(txn(), ctx(2), RULES)["rule_codes"]
    assert REPEATED_ACTIVITY in evaluate_transaction(txn(), ctx(3), RULES)["rule_codes"]


@pytest.mark.parametrize(
    "amount,kind,old,expected",
    [
        (50000, "TRANSFER", 50000, True),
        (49500, "CASH_OUT", 50000, True),      # exactly 99%
        (49000, "CASH_OUT", 50000, False),     # below ratio
        (50000, "PAYMENT", 50000, False),      # type not covered
        (5000, "TRANSFER", 5000, False),       # below minimum amount
        (50000, "TRANSFER", 0, False),         # no prior balance
    ],
)
def test_account_drained(amount, kind, old, expected):
    r = evaluate_transaction(txn(amount, kind, old), QUIET, RULES)
    assert (ACCOUNT_DRAINED in r["rule_codes"]) is expected


def test_pass_through_only_for_cash_out():
    ctx = {"recent_count": 0, "inbound_transfer_recent": True}
    assert RAPID_PASS_THROUGH in evaluate_transaction(txn(kind="CASH_OUT"), ctx, RULES)["rule_codes"]
    assert RAPID_PASS_THROUGH not in evaluate_transaction(txn(kind="TRANSFER"), ctx, RULES)["rule_codes"]


def test_risk_levels_one_rule_medium_two_or_more_high():
    one = evaluate_transaction(txn(300000), QUIET, RULES)
    assert (one["flagged"], one["risk_level"]) == (True, "MEDIUM")
    two = evaluate_transaction(txn(300000), {"recent_count": 5, "inbound_transfer_recent": False}, RULES)
    assert two["risk_level"] == "HIGH" and len(two["reasons"]) == 2
    four = evaluate_transaction(
        txn(300000, "CASH_OUT", 300000), {"recent_count": 5, "inbound_transfer_recent": True}, RULES
    )
    assert four["risk_level"] == "HIGH" and len(four["rule_codes"]) == 4


def test_reasons_match_codes():
    r = evaluate_transaction(txn(300000), QUIET, RULES)
    assert r["reasons"] == ["High-value transaction"]
