"""(Re)run the rule engine over every stored transaction and refresh the alerts.

Run:  python -m scripts.run_monitoring
"""
import argparse

import config
from database.db import get_connection, init_db
from services.monitoring_service import run_monitoring


def main() -> None:
    parser = argparse.ArgumentParser(description="Run transaction monitoring.")
    parser.add_argument("--db", default=str(config.DATABASE_PATH))
    args = parser.parse_args()
    connection = get_connection(args.db)
    init_db(connection)
    result = run_monitoring(connection)
    connection.close()
    print(f"Scanned {result['transactions_scanned']} transactions, "
          f"created {result['alerts_created']} alerts.")


if __name__ == "__main__":
    main()
