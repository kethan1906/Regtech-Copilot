"""Create the database schema.   Run:  python -m scripts.init_db [--reset]"""
import argparse

import config
from database.db import get_connection, init_db


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialise the SQLite database.")
    parser.add_argument("--db", default=str(config.DATABASE_PATH))
    parser.add_argument("--reset", action="store_true", help="DROP all existing data first")
    args = parser.parse_args()
    connection = get_connection(args.db)
    init_db(connection, reset=args.reset)
    connection.close()
    print(f"Database ready at {args.db}" + (" (reset)" if args.reset else ""))


if __name__ == "__main__":
    main()
