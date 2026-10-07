"""Import a PaySim-format CSV into SQLite.

Run:  python -m scripts.import_data --csv data/sample_transactions.csv [--monitor]

PaySim columns used: step, type, amount, nameOrig, oldbalanceOrg, newbalanceOrig,
nameDest, oldbalanceDest, newbalanceDest. The dataset's fraud labels are ignored.
"""
import argparse
import csv
import sqlite3

import config
from database.db import get_connection, init_db

REQUIRED = [
    "step", "type", "amount", "nameOrig", "oldbalanceOrg", "newbalanceOrig",
    "nameDest", "oldbalanceDest", "newbalanceDest",
]
INSERT_SQL = """
    INSERT INTO transactions (
        step, transaction_type, amount, origin_account, old_balance_origin,
        new_balance_origin, destination_account, old_balance_dest, new_balance_dest
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _parse(row: dict, line: int) -> tuple:
    try:
        return (
            int(row["step"]), row["type"].strip(), float(row["amount"]),
            row["nameOrig"].strip(), float(row["oldbalanceOrg"]), float(row["newbalanceOrig"]),
            row["nameDest"].strip(), float(row["oldbalanceDest"]), float(row["newbalanceDest"]),
        )
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"Invalid data on CSV line {line}: {exc}") from None


def import_transactions(
    connection: sqlite3.Connection,
    csv_path,
    limit: int | None = None,
    batch_size: int = 10000,
    replace: bool = False,
) -> int:
    """Insert rows in batches inside one transaction (all-or-nothing). Returns the row count."""
    init_db(connection)
    count = 0
    with open(csv_path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"CSV is missing required columns: {missing}")
        batch = []
        try:
            if replace:
                connection.execute("DELETE FROM alerts")
                connection.execute("DELETE FROM monitoring_runs")
                connection.execute("DELETE FROM transactions")

            for line, row in enumerate(reader, start=2):
                if limit is not None and count >= limit:
                    break
                batch.append(_parse(row, line))
                count += 1
                if len(batch) >= batch_size:
                    connection.executemany(INSERT_SQL, batch)
                    batch.clear()
            if batch:
                connection.executemany(INSERT_SQL, batch)
            if count == 0:
                raise ValueError("CSV contains no data rows")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Import transactions from CSV.")
    parser.add_argument("--csv", default=str(config.SAMPLE_CSV_PATH))
    parser.add_argument("--db", default=str(config.DATABASE_PATH))
    parser.add_argument("--limit", type=int, help="Only import the first N rows")
    parser.add_argument("--monitor", action="store_true", help="Run monitoring afterwards")
    parser.add_argument("--replace", action="store_true", help="Replace existing transactions before importing")
    args = parser.parse_args()

    connection = get_connection(args.db)
    try:
        n = import_transactions(connection, args.csv, args.limit, replace=args.replace)
        print(f"Imported {n} transactions into {args.db}")
        if args.monitor:
            from services.monitoring_service import run_monitoring

            print(run_monitoring(connection))
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(f"Import failed: {exc}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
