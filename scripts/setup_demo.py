"""One-shot demo setup: fresh DB + bundled SYNTHETIC sample data + monitoring.

Run:  python -m scripts.setup_demo
"""
import config
from database.db import get_connection, init_db
from scripts.import_data import import_transactions
from services.monitoring_service import run_monitoring


def main() -> None:
    connection = get_connection(config.DATABASE_PATH)
    init_db(connection, reset=True)
    n = import_transactions(connection, config.SAMPLE_CSV_PATH)
    result = run_monitoring(connection)
    connection.close()
    print(f"Demo database ready: {n} synthetic transactions, {result['alerts_created']} alerts.")
    print("Start the app with:  python app.py   then open http://127.0.0.1:5000")


if __name__ == "__main__":
    main()
