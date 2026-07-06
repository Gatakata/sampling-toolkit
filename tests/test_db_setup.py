import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_FILE = ROOT / "data" / "test_db_setup.sqlite3"
os.environ["DB_PATH"] = str(DB_FILE)

sys.path.insert(0, str(ROOT / "app" / "backend"))

from db import get_connection, initialize_database  # noqa: E402


def setup_function():
    initialize_database()


def test_initialize_database_creates_tables_and_admin_user():
    initialize_database()
    with get_connection() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "admin_users" in tables
        assert "engagements" in tables
        assert "population" in tables
        assert "sample_runs" in tables
        assert "sample_output" in tables
        assert "audit_log" in tables

        count = conn.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]
        assert count >= 1
