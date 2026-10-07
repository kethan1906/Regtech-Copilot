import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import config  # noqa: E402
from database.db import get_connection, init_db  # noqa: E402
from scripts.import_data import import_transactions  # noqa: E402
from services.monitoring_service import run_monitoring  # noqa: E402


@pytest.fixture()
def empty_db(tmp_path):
    path = tmp_path / "test.db"
    conn = get_connection(path)
    init_db(conn)
    yield conn, path
    conn.close()


@pytest.fixture()
def demo_db(tmp_path):
    path = tmp_path / "demo.db"
    conn = get_connection(path)
    init_db(conn)
    import_transactions(conn, config.SAMPLE_CSV_PATH)
    run_monitoring(conn)
    yield conn, path
    conn.close()
