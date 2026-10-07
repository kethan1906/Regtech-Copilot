"""Generate a SYNTHETIC transaction file in PaySim's column format.

This is demo/test data, not PaySim and not real transactions. It contains
ordinary traffic plus a few planted patterns so every rule has something to
find. Counts of flagged rows say nothing about real-world detection accuracy.

Run:  python -m scripts.generate_sample_data
"""
import argparse
import csv
import random
from pathlib import Path

import config

COLUMNS = [
    "step", "type", "amount", "nameOrig", "oldbalanceOrg", "newbalanceOrig",
    "nameDest", "oldbalanceDest", "newbalanceDest",
]
DEBIT_TYPES = {"PAYMENT", "TRANSFER", "CASH_OUT", "DEBIT"}


def _row(step, kind, amount, orig, old_o, dest, old_d, new_o=None):
    if new_o is None:
        new_o = old_o - amount if kind in DEBIT_TYPES else old_o + amount
    return [step, kind, round(amount, 2), orig, round(old_o, 2), round(max(new_o, 0), 2),
            dest, round(old_d, 2), round(old_d + amount, 2)]


def generate(seed: int = 42, n_background: int = 2500, max_step: int = 200):
    rng = random.Random(seed)
    acct = lambda prefix="C": f"{prefix}{rng.randint(10**8, 10**9 - 1)}"  # noqa: E731
    origins = [acct() for _ in range(900)]
    rows = []

    # Ordinary traffic: balance comfortably above the amount, modest amounts.
    kinds = ["PAYMENT"] * 50 + ["CASH_OUT"] * 20 + ["TRANSFER"] * 10 + ["CASH_IN"] * 15 + ["DEBIT"] * 5
    for _ in range(n_background):
        kind = rng.choice(kinds)
        amount = min(rng.lognormvariate(8.5, 1.0), 60000)
        old_o = amount * rng.uniform(1.5, 25)
        dest = acct("M") if kind == "PAYMENT" else rng.choice(origins)
        rows.append(_row(rng.randint(1, max_step), kind, amount, rng.choice(origins), old_o,
                         dest, rng.uniform(0, 80000)))

    # Planted: high-value transfers (the first five also empty the account -> two rules).
    for i in range(15):
        amount = rng.uniform(250000, 900000)
        if i < 5:
            rows.append(_row(rng.randint(1, max_step), "TRANSFER", amount, acct(),
                             amount, acct(), 0, new_o=0))
        else:
            rows.append(_row(rng.randint(1, max_step), "TRANSFER", amount, acct(),
                             amount * rng.uniform(1.5, 4), acct(), 0))

    # Planted: bursts of repeated activity from one account within 24 steps.
    for _ in range(10):
        orig, start = acct(), rng.randint(1, max_step - 24)
        for _ in range(rng.randint(4, 6)):
            amount = rng.uniform(500, 5000)
            rows.append(_row(start + rng.randint(0, 23), "PAYMENT", amount, orig,
                             amount * rng.uniform(5, 30), acct("M"), 0))

    # Planted: accounts drained to zero by a transfer / cash-out.
    for _ in range(12):
        old_o = rng.uniform(30000, 150000)
        kind = rng.choice(["TRANSFER", "CASH_OUT"])
        rows.append(_row(rng.randint(1, max_step), kind, old_o, acct(), old_o,
                         acct(), 0, new_o=0))

    # Planted: pass-through chains (TRANSFER in, then CASH_OUT shortly after).
    for _ in range(10):
        mule, step = acct(), rng.randint(1, max_step - 4)
        amount = rng.uniform(20000, 80000)
        rows.append(_row(step, "TRANSFER", amount, acct(), amount * 2, mule, 0))
        # Half cash out everything (pass-through + drained); half cash out ~60%.
        out = amount if _ % 2 == 0 else amount * 0.6
        rows.append(_row(step + rng.randint(1, 3), "CASH_OUT", out, mule, amount,
                         acct(), 0))

    rows.sort(key=lambda r: r[0])
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic PaySim-format data.")
    parser.add_argument("--out", default=str(config.SAMPLE_CSV_PATH))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    rows = generate(args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    print(f"Wrote {len(rows)} synthetic rows to {out}")


if __name__ == "__main__":
    main()
