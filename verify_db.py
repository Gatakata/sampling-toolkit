import sys
from pathlib import Path
sys.path.insert(0, str(Path('app/backend').resolve()))
from db import initialize_database, get_connection

initialize_database()
with get_connection() as conn:
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='admin_users'")
    print('admin_users_exists', cur.fetchone() is not None)
    cur.execute("SELECT COUNT(*) FROM admin_users")
    print('admin_users_count', cur.fetchone()[0])
