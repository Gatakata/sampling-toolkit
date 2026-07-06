import hashlib
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

try:
    import psycopg
except ImportError:  # Optional locally when running SQLite only.
    psycopg = None

DB_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
DB_PATH = os.getenv("DB_PATH", os.path.join(DB_DIR, "audit_sampling.sqlite3"))
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
DB_BACKEND = "postgres" if DATABASE_URL else "sqlite"
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "Taku")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "gatakatakum@gmail.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Taku2002!")
SESSION_HOURS = int(os.getenv("ADMIN_SESSION_HOURS", "12"))
MAX_FAILED_LOGINS = int(os.getenv("MAX_FAILED_LOGINS", "5"))
LOCKOUT_MINUTES = int(os.getenv("LOCKOUT_MINUTES", "15"))
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NAME_PATTERN = re.compile(r"^[A-Za-z-]+$")
PROFILE_PICTURE_PATTERN = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+$")


def _to_pg_query(query):
    return query.replace("?", "%s")


class CompatRow:
    def __init__(self, columns, values):
        self._columns = list(columns)
        self._values = tuple(values)
        self._index = {name: idx for idx, name in enumerate(self._columns)}

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._values[self._index[key]]
        return self._values[key]

    def __iter__(self):
        return iter(zip(self._columns, self._values))

    def keys(self):
        return list(self._columns)

    def get(self, key, default=None):
        if key in self._index:
            return self._values[self._index[key]]
        return default


class CursorAdapter:
    def __init__(self, cursor, backend):
        self._cursor = cursor
        self._backend = backend

    @property
    def lastrowid(self):
        return getattr(self._cursor, "lastrowid", None)

    @property
    def description(self):
        return getattr(self._cursor, "description", None)

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None or self._backend == "sqlite":
            return row
        columns = [col.name if hasattr(col, "name") else col[0] for col in (self._cursor.description or [])]
        return CompatRow(columns, row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        if self._backend == "sqlite":
            return rows
        columns = [col.name if hasattr(col, "name") else col[0] for col in (self._cursor.description or [])]
        return [CompatRow(columns, row) for row in rows]


class ConnectionAdapter:
    def __init__(self, connection, backend):
        self._connection = connection
        self._backend = backend

    def execute(self, query, params=None):
        if self._backend == "postgres":
            query = _to_pg_query(query)
        cursor = self._connection.execute(query, params or ())
        return CursorAdapter(cursor, self._backend)

    def executescript(self, script):
        if self._backend == "sqlite":
            self._connection.executescript(script)
            return
        for statement in [chunk.strip() for chunk in script.split(";") if chunk.strip()]:
            self.execute(statement)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            try:
                self.rollback()
            finally:
                self.close()
            return False
        self.close()
        return False


def _insert_and_get_id(conn, insert_query, params):
    if DB_BACKEND == "postgres":
        row = conn.execute(f"{insert_query} RETURNING id", params).fetchone()
        return row[0] if row is not None else None
    cursor = conn.execute(insert_query, params)
    return cursor.lastrowid


def get_connection():
    if DB_BACKEND == "postgres":
        if psycopg is None:
            raise RuntimeError("PostgreSQL backend selected but psycopg is not installed")
        return ConnectionAdapter(psycopg.connect(DATABASE_URL), "postgres")
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return ConnectionAdapter(conn, "sqlite")


def fetch_all(query, params=None):
    with get_connection() as conn:
        rows = conn.execute(query, params or ()).fetchall()
        return [dict(row) for row in rows]


def fetch_one(query, params=None):
    with get_connection() as conn:
        row = conn.execute(query, params or ()).fetchone()
        return dict(row) if row is not None else None


def execute(query, params=None, returning=False):
    with get_connection() as conn:
        cur = conn.execute(query, params or ())
        conn.commit()
        if returning:
            row = cur.fetchone()
            if row is None:
                return None
            return dict(row)
        return None


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def validate_password_strength(password):
    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not re.search(r"[A-Z]", password):
        return False, "Password must include at least one uppercase letter"
    if not re.search(r"[a-z]", password):
        return False, "Password must include at least one lowercase letter"
    if not re.search(r"\d", password):
        return False, "Password must include at least one number"
    if not re.search(r"[^A-Za-z0-9]", password):
        return False, "Password must include at least one special character"
    return True, "ok"


def is_valid_email(email):
    return bool(email and EMAIL_PATTERN.match(email.strip()))


def normalize_name(value):
    raw = (value or "").strip()
    if not raw:
        return ""
    parts = [part for part in raw.split("-") if part]
    if not parts:
        return ""
    return "-".join(part.capitalize() for part in parts)


def validate_name(value, field_label):
    raw = (value or "").strip()
    if not raw:
        return f"{field_label} is required"
    if len(raw) > 80:
        return f"{field_label} must be 80 characters or fewer"
    if not NAME_PATTERN.match(raw):
        return f"{field_label} can only contain letters and hyphens"
    return None


def validate_profile_picture(value):
    if not value:
        return None
    if len(value) > 2_000_000:
        return "Profile picture is too large"
    if not PROFILE_PICTURE_PATTERN.match(value):
        return "Profile picture must be an image data URL"
    return None


def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _to_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _insert_audit_event(
    conn,
    user_name,
    event_type,
    details="",
    engagement_id=None,
    sampling_method=None,
    materiality=None,
    random_seed=None,
    sample_size=None,
    run_id=None,
    is_voided=0,
):
    conn.execute(
        """
        INSERT INTO audit_log (
          user_name,
          engagement_id,
          run_id,
          event_type,
          sampling_method,
          materiality,
          random_seed,
          sample_size,
          is_voided,
          details
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_name,
            engagement_id,
            run_id,
            event_type,
            sampling_method,
            materiality,
            random_seed,
            sample_size,
            1 if is_voided else 0,
            details,
        ),
    )


def add_audit_event(
    user_name,
    event_type,
    details="",
    engagement_id=None,
    sampling_method=None,
    materiality=None,
    random_seed=None,
    sample_size=None,
    run_id=None,
    is_voided=0,
):
    with get_connection() as conn:
        _insert_audit_event(
            conn,
            user_name,
            event_type,
            details,
            engagement_id=engagement_id,
            sampling_method=sampling_method,
            materiality=materiality,
            random_seed=random_seed,
            sample_size=sample_size,
            run_id=run_id,
            is_voided=is_voided,
        )
        conn.commit()


def initialize_database():
    with get_connection() as conn:
        if DB_BACKEND == "postgres":
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS admin_users (
                  id SERIAL PRIMARY KEY,
                  username TEXT UNIQUE NOT NULL,
                  first_name TEXT,
                  surname TEXT,
                  profile_picture TEXT,
                  email TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL,
                  is_admin INTEGER DEFAULT 0,
                  is_active INTEGER DEFAULT 1,
                  failed_login_attempts INTEGER DEFAULT 0,
                  locked_until TEXT,
                  last_failed_login TEXT,
                  must_reset_password INTEGER DEFAULT 0,
                  created_by INTEGER REFERENCES admin_users(id),
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS admin_sessions (
                  token TEXT PRIMARY KEY,
                  admin_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
                  created_at TEXT NOT NULL,
                  expires_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS engagements (
                  id SERIAL PRIMARY KEY,
                  client_name TEXT,
                  engagement_ref TEXT,
                  auditor_name TEXT,
                  financial_year TEXT,
                  materiality_benchmark TEXT,
                  materiality_base REAL,
                  materiality_percent REAL,
                  materiality REAL,
                  performance_percent REAL,
                  performance_materiality REAL,
                  clearly_trivial_percent REAL,
                  clearly_trivial_threshold REAL,
                  created_by TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS population (
                  id SERIAL PRIMARY KEY,
                  engagement_id INTEGER REFERENCES engagements(id) ON DELETE CASCADE,
                  account_code TEXT,
                  transaction_ref TEXT,
                  description TEXT,
                  transaction_date TEXT,
                  amount REAL,
                  is_high_value INTEGER DEFAULT 0
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_population_unique_ref
                ON population (engagement_id, transaction_ref)
                WHERE transaction_ref IS NOT NULL AND transaction_ref <> '';

                CREATE INDEX IF NOT EXISTS idx_population_engagement_account
                ON population (engagement_id, account_code);

                CREATE TABLE IF NOT EXISTS sample_runs (
                  id SERIAL PRIMARY KEY,
                  engagement_id INTEGER REFERENCES engagements(id) ON DELETE CASCADE,
                  run_timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                  auditor_name TEXT,
                  sampling_method TEXT,
                  population_count INTEGER,
                  population_value REAL,
                  materiality REAL,
                  performance_materiality REAL,
                  clearly_trivial_threshold REAL,
                  confidence_level REAL,
                  expected_error_rate REAL,
                  tolerable_error_rate REAL,
                  sample_size INTEGER,
                  random_seed INTEGER,
                  high_value_count INTEGER,
                  is_voided INTEGER DEFAULT 0,
                  voided_at TEXT,
                  voided_by TEXT,
                  notes TEXT
                );

                CREATE TABLE IF NOT EXISTS sample_output (
                  id SERIAL PRIMARY KEY,
                  run_id INTEGER REFERENCES sample_runs(id) ON DELETE CASCADE,
                  population_id INTEGER REFERENCES population(id),
                  is_high_value INTEGER DEFAULT 0,
                  stratum TEXT,
                  selected_reason TEXT DEFAULT 'sample'
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                  id SERIAL PRIMARY KEY,
                  event_timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                  user_name TEXT,
                  engagement_id INTEGER REFERENCES engagements(id) ON DELETE CASCADE,
                  run_id INTEGER REFERENCES sample_runs(id) ON DELETE SET NULL,
                  event_type TEXT,
                  sampling_method TEXT,
                  materiality REAL,
                  performance_materiality REAL,
                  clearly_trivial_threshold REAL,
                  random_seed INTEGER,
                  sample_size INTEGER,
                  is_voided INTEGER DEFAULT 0,
                  details TEXT
                );

                ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS first_name TEXT;
                ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS surname TEXT;
                ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS profile_picture TEXT;
                ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS is_admin INTEGER DEFAULT 0;
                ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS is_active INTEGER DEFAULT 1;
                ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS created_by INTEGER;
                ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS must_reset_password INTEGER DEFAULT 0;
                ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER DEFAULT 0;
                ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS locked_until TEXT;
                ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS last_failed_login TEXT;

                ALTER TABLE engagements ADD COLUMN IF NOT EXISTS materiality_benchmark TEXT;
                ALTER TABLE engagements ADD COLUMN IF NOT EXISTS materiality_base REAL;
                ALTER TABLE engagements ADD COLUMN IF NOT EXISTS materiality_percent REAL;
                ALTER TABLE engagements ADD COLUMN IF NOT EXISTS performance_percent REAL DEFAULT 75;
                ALTER TABLE engagements ADD COLUMN IF NOT EXISTS clearly_trivial_percent REAL DEFAULT 3;
                ALTER TABLE engagements ADD COLUMN IF NOT EXISTS clearly_trivial_threshold REAL;
                ALTER TABLE engagements ADD COLUMN IF NOT EXISTS created_by TEXT;

                ALTER TABLE sample_runs ADD COLUMN IF NOT EXISTS performance_materiality REAL;
                ALTER TABLE sample_runs ADD COLUMN IF NOT EXISTS clearly_trivial_threshold REAL;
                ALTER TABLE sample_runs ADD COLUMN IF NOT EXISTS tolerable_error_rate REAL;
                ALTER TABLE sample_runs ADD COLUMN IF NOT EXISTS is_voided INTEGER DEFAULT 0;
                ALTER TABLE sample_runs ADD COLUMN IF NOT EXISTS voided_at TEXT;
                ALTER TABLE sample_runs ADD COLUMN IF NOT EXISTS voided_by TEXT;

                ALTER TABLE sample_output ADD COLUMN IF NOT EXISTS stratum TEXT;
                ALTER TABLE sample_output ADD COLUMN IF NOT EXISTS selected_reason TEXT DEFAULT 'sample';

                ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS performance_materiality REAL;
                ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS clearly_trivial_threshold REAL;
                ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS run_id INTEGER;
                ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS is_voided INTEGER DEFAULT 0;
                """
            )
        else:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS admin_users (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  first_name TEXT,
                  surname TEXT,
                  profile_picture TEXT,
                  email TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL,
                  is_admin INTEGER DEFAULT 0,
                  is_active INTEGER DEFAULT 1,
                  failed_login_attempts INTEGER DEFAULT 0,
                  locked_until TEXT,
                  last_failed_login TEXT,
                  must_reset_password INTEGER DEFAULT 0,
                  created_by INTEGER REFERENCES admin_users(id),
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS admin_sessions (
                  token TEXT PRIMARY KEY,
                  admin_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
                  created_at TEXT NOT NULL,
                  expires_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS engagements (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  client_name TEXT,
                  engagement_ref TEXT,
                  auditor_name TEXT,
                  financial_year TEXT,
                  materiality_benchmark TEXT,
                  materiality_base REAL,
                  materiality_percent REAL,
                  materiality REAL,
                  performance_percent REAL,
                  performance_materiality REAL,
                  clearly_trivial_percent REAL,
                  clearly_trivial_threshold REAL,
                  created_by TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS population (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  engagement_id INTEGER REFERENCES engagements(id) ON DELETE CASCADE,
                  account_code TEXT,
                  transaction_ref TEXT,
                  description TEXT,
                  transaction_date TEXT,
                  amount REAL,
                  is_high_value INTEGER DEFAULT 0
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_population_unique_ref
                ON population (engagement_id, transaction_ref)
                WHERE transaction_ref IS NOT NULL AND transaction_ref <> '';

                CREATE INDEX IF NOT EXISTS idx_population_engagement_account
                ON population (engagement_id, account_code);

                CREATE TABLE IF NOT EXISTS sample_runs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  engagement_id INTEGER REFERENCES engagements(id) ON DELETE CASCADE,
                  run_timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                  auditor_name TEXT,
                  sampling_method TEXT,
                  population_count INTEGER,
                  population_value REAL,
                  materiality REAL,
                  performance_materiality REAL,
                  clearly_trivial_threshold REAL,
                  confidence_level REAL,
                  expected_error_rate REAL,
                  tolerable_error_rate REAL,
                  sample_size INTEGER,
                  random_seed INTEGER,
                  high_value_count INTEGER,
                  is_voided INTEGER DEFAULT 0,
                  voided_at TEXT,
                  voided_by TEXT,
                  notes TEXT
                );

                CREATE TABLE IF NOT EXISTS sample_output (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_id INTEGER REFERENCES sample_runs(id) ON DELETE CASCADE,
                  population_id INTEGER REFERENCES population(id),
                  is_high_value INTEGER DEFAULT 0,
                  stratum TEXT,
                  selected_reason TEXT DEFAULT 'sample'
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  event_timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                  user_name TEXT,
                  engagement_id INTEGER REFERENCES engagements(id) ON DELETE CASCADE,
                  run_id INTEGER REFERENCES sample_runs(id) ON DELETE SET NULL,
                  event_type TEXT,
                  sampling_method TEXT,
                  materiality REAL,
                  performance_materiality REAL,
                  clearly_trivial_threshold REAL,
                  random_seed INTEGER,
                  sample_size INTEGER,
                  is_voided INTEGER DEFAULT 0,
                  details TEXT
                );
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(admin_users)").fetchall()}
            if "first_name" not in columns:
                conn.execute("ALTER TABLE admin_users ADD COLUMN first_name TEXT")
            if "surname" not in columns:
                conn.execute("ALTER TABLE admin_users ADD COLUMN surname TEXT")
            if "profile_picture" not in columns:
                conn.execute("ALTER TABLE admin_users ADD COLUMN profile_picture TEXT")
            if "is_admin" not in columns:
                conn.execute("ALTER TABLE admin_users ADD COLUMN is_admin INTEGER DEFAULT 0")
            if "is_active" not in columns:
                conn.execute("ALTER TABLE admin_users ADD COLUMN is_active INTEGER DEFAULT 1")
            if "created_by" not in columns:
                conn.execute("ALTER TABLE admin_users ADD COLUMN created_by INTEGER")
            if "must_reset_password" not in columns:
                conn.execute("ALTER TABLE admin_users ADD COLUMN must_reset_password INTEGER DEFAULT 0")
            if "failed_login_attempts" not in columns:
                conn.execute("ALTER TABLE admin_users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0")
            if "locked_until" not in columns:
                conn.execute("ALTER TABLE admin_users ADD COLUMN locked_until TEXT")
            if "last_failed_login" not in columns:
                conn.execute("ALTER TABLE admin_users ADD COLUMN last_failed_login TEXT")

            engagement_columns = {row[1] for row in conn.execute("PRAGMA table_info(engagements)").fetchall()}
            if "materiality_benchmark" not in engagement_columns:
                conn.execute("ALTER TABLE engagements ADD COLUMN materiality_benchmark TEXT")
            if "materiality_base" not in engagement_columns:
                conn.execute("ALTER TABLE engagements ADD COLUMN materiality_base REAL")
            if "materiality_percent" not in engagement_columns:
                conn.execute("ALTER TABLE engagements ADD COLUMN materiality_percent REAL")
            if "performance_percent" not in engagement_columns:
                conn.execute("ALTER TABLE engagements ADD COLUMN performance_percent REAL DEFAULT 75")
            if "clearly_trivial_percent" not in engagement_columns:
                conn.execute("ALTER TABLE engagements ADD COLUMN clearly_trivial_percent REAL DEFAULT 3")
            if "clearly_trivial_threshold" not in engagement_columns:
                conn.execute("ALTER TABLE engagements ADD COLUMN clearly_trivial_threshold REAL")
            if "created_by" not in engagement_columns:
                conn.execute("ALTER TABLE engagements ADD COLUMN created_by TEXT")

            sample_run_columns = {row[1] for row in conn.execute("PRAGMA table_info(sample_runs)").fetchall()}
            if "performance_materiality" not in sample_run_columns:
                conn.execute("ALTER TABLE sample_runs ADD COLUMN performance_materiality REAL")
            if "clearly_trivial_threshold" not in sample_run_columns:
                conn.execute("ALTER TABLE sample_runs ADD COLUMN clearly_trivial_threshold REAL")
            if "tolerable_error_rate" not in sample_run_columns:
                conn.execute("ALTER TABLE sample_runs ADD COLUMN tolerable_error_rate REAL")
            if "is_voided" not in sample_run_columns:
                conn.execute("ALTER TABLE sample_runs ADD COLUMN is_voided INTEGER DEFAULT 0")
            if "voided_at" not in sample_run_columns:
                conn.execute("ALTER TABLE sample_runs ADD COLUMN voided_at TEXT")
            if "voided_by" not in sample_run_columns:
                conn.execute("ALTER TABLE sample_runs ADD COLUMN voided_by TEXT")

            sample_output_columns = {row[1] for row in conn.execute("PRAGMA table_info(sample_output)").fetchall()}
            if "stratum" not in sample_output_columns:
                conn.execute("ALTER TABLE sample_output ADD COLUMN stratum TEXT")
            if "selected_reason" not in sample_output_columns:
                conn.execute("ALTER TABLE sample_output ADD COLUMN selected_reason TEXT DEFAULT 'sample'")

            audit_columns = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)").fetchall()}
            if "performance_materiality" not in audit_columns:
                conn.execute("ALTER TABLE audit_log ADD COLUMN performance_materiality REAL")
            if "clearly_trivial_threshold" not in audit_columns:
                conn.execute("ALTER TABLE audit_log ADD COLUMN clearly_trivial_threshold REAL")
            if "run_id" not in audit_columns:
                conn.execute("ALTER TABLE audit_log ADD COLUMN run_id INTEGER")
            if "is_voided" not in audit_columns:
                conn.execute("ALTER TABLE audit_log ADD COLUMN is_voided INTEGER DEFAULT 0")
        admin_count = conn.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]
        if admin_count == 0:
            seed_first_name = normalize_name(ADMIN_USERNAME or "Admin") or "Admin"
            conn.execute(
                "INSERT INTO admin_users (username, first_name, surname, profile_picture, email, password_hash, is_admin, is_active, must_reset_password) VALUES (?, ?, ?, ?, ?, ?, 1, 1, 0)",
                (ADMIN_USERNAME, seed_first_name, "Admin", None, ADMIN_EMAIL, hash_password(ADMIN_PASSWORD)),
            )
        conn.execute("UPDATE admin_users SET is_admin = 1, is_active = 1, must_reset_password = 0 WHERE username = ?", (ADMIN_USERNAME,))
        conn.commit()


initialize_database()


def _cleanup_sessions(conn):
    conn.execute("DELETE FROM admin_sessions WHERE expires_at < ?", (utc_now_iso(),))


def create_admin_session(admin_id):
    token = secrets.token_urlsafe(32)
    created_at = utc_now_iso()
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).replace(microsecond=0).isoformat()
    with get_connection() as conn:
        _cleanup_sessions(conn)
        conn.execute(
            "INSERT INTO admin_sessions (token, admin_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, admin_id, created_at, expires_at),
        )
        conn.commit()
    return {"token": token, "expires_at": expires_at}


def get_admin_by_token(token):
    if not token:
        return None
    with get_connection() as conn:
        _cleanup_sessions(conn)
        row = conn.execute(
            """
            SELECT au.id, au.username, au.email, au.is_admin, au.is_active, au.must_reset_password, au.created_at, s.expires_at
            FROM admin_sessions s
            JOIN admin_users au ON au.id = s.admin_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
        conn.commit()
        if row is None:
            return None
        user = dict(row)
        details = conn.execute(
            "SELECT first_name, surname, profile_picture FROM admin_users WHERE id = ?",
            (user["id"],),
        ).fetchone()
        if details is not None:
            user.update(dict(details))
        return user


def _validate_user_payload(data, require_password=True, require_identity=True):
    errors = {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip()
    first_name = data.get("first_name")
    surname = data.get("surname")
    profile_picture = data.get("profile_picture")
    password = data.get("password") or ""

    if require_identity:
        if not username:
            errors["username"] = "Username is required"
        if not email:
            errors["email"] = "Email is required"
        elif not is_valid_email(email):
            errors["email"] = "Invalid email format"

    first_name_error = validate_name(first_name, "First name")
    if first_name_error:
        errors["first_name"] = first_name_error
    surname_error = validate_name(surname, "Surname")
    if surname_error:
        errors["surname"] = surname_error

    picture_error = validate_profile_picture(profile_picture)
    if picture_error:
        errors["profile_picture"] = picture_error

    if require_password:
        if not password:
            errors["password"] = "Password is required"
        else:
            strong, message = validate_password_strength(password)
            if not strong:
                errors["password"] = message

    return errors


def create_admin_user(data):
    username = (data.get("username") or "").strip()
    first_name = normalize_name(data.get("first_name"))
    surname = normalize_name(data.get("surname"))
    profile_picture = data.get("profile_picture") or None
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    is_admin = 1 if data.get("is_admin", False) else 0
    created_by = data.get("created_by")
    must_reset_password = 0 if is_admin else 1
    errors = _validate_user_payload(
        {
            "username": username,
            "email": email,
            "password": password,
            "first_name": first_name,
            "surname": surname,
            "profile_picture": profile_picture,
        }
    )
    if errors:
        return {"created": False, "errors": errors}
    with get_connection() as conn:
        username_exists = conn.execute("SELECT id FROM admin_users WHERE lower(username) = lower(?)", (username,)).fetchone()
        if username_exists:
            return {"created": False, "errors": {"username": "Username already exists"}}
        email_exists = conn.execute("SELECT id FROM admin_users WHERE lower(email) = lower(?)", (email,)).fetchone()
        if email_exists:
            return {"created": False, "errors": {"email": "Email already exists"}}
        admin_id = _insert_and_get_id(
            conn,
            "INSERT INTO admin_users (username, first_name, surname, profile_picture, email, password_hash, is_admin, is_active, must_reset_password, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (username, first_name, surname, profile_picture, email, hash_password(password), is_admin, must_reset_password, created_by),
        )
        conn.commit()
        creator = conn.execute("SELECT username FROM admin_users WHERE id = ?", (created_by,)).fetchone() if created_by else None
        actor = creator[0] if creator else username
        _insert_audit_event(
            conn,
            actor,
            "user_created",
            f"Created user {username} with role {'admin' if is_admin else 'user'}",
        )
        conn.commit()
    return {
        "created": True,
        "id": admin_id,
        "username": username,
        "first_name": first_name,
        "surname": surname,
        "profile_picture": profile_picture,
        "email": email,
        "is_admin": bool(is_admin),
        "must_reset_password": bool(must_reset_password),
    }


def create_user(data, created_by):
    payload = {
        "username": data.get("username"),
        "first_name": data.get("first_name"),
        "surname": data.get("surname"),
        "profile_picture": data.get("profile_picture"),
        "email": data.get("email"),
        "password": data.get("password"),
        "is_admin": bool(data.get("is_admin", False)),
        "created_by": created_by,
    }
    return create_admin_user(payload)


def get_users():
    return fetch_all(
        """
        SELECT id, username, first_name, surname, profile_picture, email, is_admin, is_active, must_reset_password, created_by, created_at
        FROM admin_users
        ORDER BY username
        """
    )


def update_user(user_id, data, acted_by=None):
    username = (data.get("username") or "").strip()
    first_name = normalize_name(data.get("first_name"))
    surname = normalize_name(data.get("surname"))
    profile_picture = data.get("profile_picture", None)
    email = (data.get("email") or "").strip()
    is_admin = 1 if bool(data.get("is_admin", False)) else 0

    errors = _validate_user_payload(
        {
            "username": username,
            "email": email,
            "first_name": first_name,
            "surname": surname,
            "profile_picture": profile_picture,
        },
        require_password=False,
    )
    if errors:
        return {"updated": False, "errors": errors}

    with get_connection() as conn:
        existing = conn.execute("SELECT id, username FROM admin_users WHERE id = ?", (user_id,)).fetchone()
        if existing is None:
            return {"updated": False, "message": "User not found"}

        username_conflict = conn.execute(
            "SELECT id FROM admin_users WHERE lower(username) = lower(?) AND id <> ?",
            (username, user_id),
        ).fetchone()
        if username_conflict:
            return {"updated": False, "message": "Username already exists"}

        email_conflict = conn.execute(
            "SELECT id FROM admin_users WHERE lower(email) = lower(?) AND id <> ?",
            (email, user_id),
        ).fetchone()
        if email_conflict:
            return {"updated": False, "errors": {"email": "Email already exists"}}

        current_profile = conn.execute("SELECT profile_picture FROM admin_users WHERE id = ?", (user_id,)).fetchone()
        resolved_picture = current_profile[0] if current_profile is not None else None
        if profile_picture is not None:
            resolved_picture = profile_picture or None

        conn.execute(
            "UPDATE admin_users SET username = ?, first_name = ?, surname = ?, profile_picture = ?, email = ?, is_admin = ? WHERE id = ?",
            (username, first_name, surname, resolved_picture, email, is_admin, user_id),
        )
        _insert_audit_event(
            conn,
            acted_by or existing[1],
            "user_updated",
            f"Updated user {existing[1]} -> {username}; role {'admin' if is_admin else 'user'}",
        )
        conn.commit()

    user = fetch_one(
        "SELECT id, username, first_name, surname, profile_picture, email, is_admin, is_active, must_reset_password, created_by, created_at FROM admin_users WHERE id = ?",
        [user_id],
    )
    return {"updated": True, "user": user}


def delete_user(user_id, acted_by=None):
    with get_connection() as conn:
        row = conn.execute("SELECT username FROM admin_users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return {"deleted": False, "message": "User not found"}
        username = row[0]
        conn.execute("UPDATE audit_log SET user_name = '[Deleted User]' WHERE user_name = ?", (username,))
        conn.execute("DELETE FROM admin_sessions WHERE admin_id = ?", (user_id,))
        conn.execute("DELETE FROM admin_users WHERE id = ?", (user_id,))
        _insert_audit_event(
            conn,
            acted_by or "system",
            "user_deleted",
            f"Deleted user {username}",
        )
        conn.commit()
    return {"deleted": True}


def authenticate_admin(username, password):
    result = authenticate_user(username, password)
    return result.get("user") if result.get("ok") else None


def update_user_status(user_id, is_active, acted_by=None):
    with get_connection() as conn:
        row = conn.execute("SELECT username FROM admin_users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE admin_users SET is_active = ? WHERE id = ?", (1 if is_active else 0, user_id))
        if not is_active:
            conn.execute("DELETE FROM admin_sessions WHERE admin_id = ?", (user_id,))
        _insert_audit_event(
            conn,
            acted_by or row[0],
            "user_enabled" if is_active else "user_disabled",
            f"User account status changed for {row[0]}",
        )
        conn.commit()
    return fetch_one(
        "SELECT id, username, first_name, surname, profile_picture, email, is_admin, is_active, must_reset_password, created_at FROM admin_users WHERE id = ?",
        [user_id],
    )


def set_user_password(user_id, new_password, must_reset_password, acted_by=None):
    strong, message = validate_password_strength(new_password)
    if not strong:
        return {"updated": False, "message": message}
    with get_connection() as conn:
        row = conn.execute("SELECT username FROM admin_users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return {"updated": False, "message": "User not found"}
        conn.execute(
            """
            UPDATE admin_users
            SET password_hash = ?, must_reset_password = ?, failed_login_attempts = 0, locked_until = NULL, last_failed_login = NULL
            WHERE id = ?
            """,
            (hash_password(new_password), 1 if must_reset_password else 0, user_id),
        )
        _insert_audit_event(conn, acted_by or row[0], "user_password_set", f"Password updated for {row[0]}")
        conn.commit()
    return {"updated": True}


def change_own_password(user_id, current_password, new_password):
    with get_connection() as conn:
        existing = conn.execute("SELECT password_hash FROM admin_users WHERE id = ?", (user_id,)).fetchone()
        if not existing:
            return {"updated": False, "message": "User not found"}
        if existing[0] != hash_password(current_password or ""):
            return {"updated": False, "message": "Current password is incorrect"}
    result = set_user_password(user_id, new_password, must_reset_password=False, acted_by=None)
    if result.get("updated"):
        user = fetch_one("SELECT username FROM admin_users WHERE id = ?", [user_id])
        if user:
            add_audit_event(user["username"], "user_password_changed", "User changed own password")
    return result


def authenticate_user(username, password):
    normalized = (username or "").strip()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, username, email, password_hash, is_admin, is_active, must_reset_password,
                   failed_login_attempts, locked_until, last_failed_login, first_name, surname, profile_picture
            FROM admin_users
            WHERE username = ?
            """,
            (normalized,),
        ).fetchone()

        if row is None:
            _insert_audit_event(conn, normalized or "unknown", "login_failed", "Unknown username")
            conn.commit()
            return {"ok": False, "error": "Invalid credentials", "code": "INVALID_CREDENTIALS"}

        user = dict(row)
        if not bool(user.get("is_active", 1)):
            _insert_audit_event(conn, user["username"], "login_blocked_disabled", "Disabled account login attempt")
            conn.commit()
            return {"ok": False, "error": "User account disabled", "code": "ACCOUNT_DISABLED"}

        now = datetime.now(timezone.utc)
        locked_until = _to_datetime(user.get("locked_until"))
        if locked_until and locked_until > now:
            _insert_audit_event(conn, user["username"], "login_blocked_locked", f"Locked until {user['locked_until']}")
            conn.commit()
            return {
                "ok": False,
                "error": "Account locked due to repeated failed logins",
                "code": "ACCOUNT_LOCKED",
                "locked_until": user.get("locked_until"),
            }

        password_hash = hash_password(password or "")
        if password_hash != user["password_hash"]:
            attempts = int(user.get("failed_login_attempts") or 0) + 1
            now_iso = utc_now_iso()
            if attempts >= MAX_FAILED_LOGINS:
                until = (now + timedelta(minutes=LOCKOUT_MINUTES)).replace(microsecond=0).isoformat()
                conn.execute(
                    "UPDATE admin_users SET failed_login_attempts = ?, last_failed_login = ?, locked_until = ? WHERE id = ?",
                    (attempts, now_iso, until, user["id"]),
                )
                _insert_audit_event(
                    conn,
                    user["username"],
                    "login_locked",
                    f"Account locked after {attempts} failed login attempts",
                )
                conn.commit()
                return {
                    "ok": False,
                    "error": "Account locked due to repeated failed logins",
                    "code": "ACCOUNT_LOCKED",
                    "locked_until": until,
                }

            conn.execute(
                "UPDATE admin_users SET failed_login_attempts = ?, last_failed_login = ?, locked_until = NULL WHERE id = ?",
                (attempts, now_iso, user["id"]),
            )
            remaining = max(0, MAX_FAILED_LOGINS - attempts)
            _insert_audit_event(
                conn,
                user["username"],
                "login_failed",
                f"Failed login attempt {attempts}/{MAX_FAILED_LOGINS}",
            )
            conn.commit()
            return {
                "ok": False,
                "error": "Invalid credentials",
                "code": "INVALID_CREDENTIALS",
                "remaining_attempts": remaining,
            }

        conn.execute(
            "UPDATE admin_users SET failed_login_attempts = 0, locked_until = NULL, last_failed_login = NULL WHERE id = ?",
            (user["id"],),
        )
        _insert_audit_event(conn, user["username"], "login_success", "User logged in successfully")
        conn.commit()

        safe_user = {
            "id": user["id"],
            "username": user["username"],
            "first_name": user.get("first_name"),
            "surname": user.get("surname"),
            "profile_picture": user.get("profile_picture"),
            "email": user["email"],
            "is_admin": user["is_admin"],
            "is_active": user["is_active"],
            "must_reset_password": user["must_reset_password"],
            "created_at": user.get("created_at"),
        }
        return {"ok": True, "user": safe_user}


def update_own_profile(user_id, data):
    first_name = normalize_name(data.get("first_name"))
    surname = normalize_name(data.get("surname"))
    profile_picture = data.get("profile_picture", None)

    errors = _validate_user_payload(
        {
            "username": "placeholder",
            "email": "placeholder@example.com",
            "first_name": first_name,
            "surname": surname,
            "profile_picture": profile_picture,
        },
        require_password=False,
        require_identity=False,
    )
    if errors:
        return {"updated": False, "errors": errors}

    with get_connection() as conn:
        current = conn.execute("SELECT profile_picture FROM admin_users WHERE id = ?", (user_id,)).fetchone()
        if current is None:
            return {"updated": False, "message": "User not found"}
        resolved_picture = current[0]
        if profile_picture is not None:
            resolved_picture = profile_picture or None
        conn.execute(
            "UPDATE admin_users SET first_name = ?, surname = ?, profile_picture = ? WHERE id = ?",
            (first_name, surname, resolved_picture, user_id),
        )
        conn.commit()
    user = fetch_one(
        "SELECT id, username, first_name, surname, profile_picture, email, is_admin, is_active, must_reset_password, created_at FROM admin_users WHERE id = ?",
        [user_id],
    )
    return {"updated": True, "user": user}


def create_user_session(user_id):
    return create_admin_session(user_id)


def get_user_by_token(token):
    return get_admin_by_token(token)


def get_admin_status():
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM admin_users").fetchone()
        return {"configured": row[0] > 0}


def create_engagement(data, acted_by=None):
    query = """
    INSERT INTO engagements (
      client_name,
      engagement_ref,
      auditor_name,
      financial_year,
      materiality_benchmark,
      materiality_base,
      materiality_percent,
      materiality,
      performance_percent,
      performance_materiality,
      clearly_trivial_percent,
            clearly_trivial_threshold,
            created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with get_connection() as conn:
        engagement_id = _insert_and_get_id(conn, query, [
            data.get("client_name"),
            data.get("engagement_ref"),
            data.get("auditor_name"),
            data.get("financial_year"),
            data.get("materiality_benchmark"),
            data.get("materiality_base"),
            data.get("materiality_percent"),
            data.get("materiality"),
            data.get("performance_percent", 75),
            data.get("performance_materiality"),
            data.get("clearly_trivial_percent", 3),
            data.get("clearly_trivial_threshold"),
            data.get("created_by"),
        ])
        conn.commit()
        conn.execute(
            """
            INSERT INTO audit_log (user_name, engagement_id, event_type, details)
            VALUES (?, ?, 'engagement_created', ?)
            """,
            (
                acted_by or data.get("auditor_name") or "system",
                engagement_id,
                f"Created engagement {data.get('engagement_ref') or engagement_id}",
            ),
        )
        conn.commit()
        return fetch_one("SELECT * FROM engagements WHERE id = ?", [engagement_id])


def get_engagements():
    return fetch_all("SELECT * FROM engagements ORDER BY created_at DESC")


def get_engagement(engagement_id):
    return fetch_one("SELECT * FROM engagements WHERE id = ?", [engagement_id])


def update_engagement(engagement_id, data, acted_by=None):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE engagements
            SET client_name = ?, engagement_ref = ?, auditor_name = ?, financial_year = ?,
                materiality_benchmark = ?, materiality_base = ?, materiality_percent = ?,
                materiality = ?, performance_percent = ?, performance_materiality = ?,
                clearly_trivial_percent = ?, clearly_trivial_threshold = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                data.get("client_name"),
                data.get("engagement_ref"),
                data.get("auditor_name"),
                data.get("financial_year"),
                data.get("materiality_benchmark"),
                data.get("materiality_base"),
                data.get("materiality_percent"),
                data.get("materiality"),
                data.get("performance_percent", 75),
                data.get("performance_materiality"),
                data.get("clearly_trivial_percent", 3),
                data.get("clearly_trivial_threshold"),
                engagement_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO audit_log (user_name, engagement_id, event_type, materiality, details)
            VALUES (?, ?, 'engagement_updated', ?, ?)
            """,
            (
                acted_by or data.get("auditor_name") or "system",
                engagement_id,
                data.get("materiality"),
                "Updated engagement settings",
            ),
        )
        conn.commit()
    return get_engagement(engagement_id)


def delete_engagement(engagement_id, acted_by=None):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id, client_name, engagement_ref FROM engagements WHERE id = ?",
            (engagement_id,),
        ).fetchone()
        if existing is None:
            return {"deleted": False, "message": "Engagement not found"}

        client_name = existing[1] or "Unknown"
        engagement_ref = existing[2] or existing[0]
        conn.execute("DELETE FROM engagements WHERE id = ?", (engagement_id,))
        _insert_audit_event(
            conn,
            acted_by or "system",
            "engagement_deleted",
            f"Deleted engagement {engagement_ref} ({client_name})",
            engagement_id=None,
        )
        conn.commit()
    return {"deleted": True}


def save_population(engagement_id, rows, acted_by=None):
    query = """
    INSERT INTO population (engagement_id, account_code, transaction_ref, description, transaction_date, amount, is_high_value)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    inserted = 0
    duplicates = set()
    seen_refs = set()
    refs = [
        (row.get("transaction_ref") or "").strip()
        for row in rows
        if (row.get("transaction_ref") or "").strip()
    ]
    with get_connection() as conn:
        existing_refs = set()
        if refs:
            placeholders = ",".join(["?"] * len(refs))
            existing_rows = conn.execute(
                f"SELECT transaction_ref FROM population WHERE engagement_id = ? AND transaction_ref IN ({placeholders})",
                [engagement_id, *refs],
            ).fetchall()
            existing_refs = {r[0] for r in existing_rows if r[0]}

        for row in rows:
            ref = (row.get("transaction_ref") or "").strip()
            amount = float(row.get("amount") or 0)
            if ref and (ref in seen_refs or ref in existing_refs):
                duplicates.add(ref)
                continue
            if ref:
                seen_refs.add(ref)
            conn.execute(
                query,
                [
                    engagement_id,
                    row.get("account_code"),
                    ref or None,
                    row.get("description"),
                    row.get("transaction_date"),
                    amount,
                    1 if row.get("is_high_value", False) else 0,
                ],
            )
            inserted += 1
        conn.execute(
            """
            INSERT INTO audit_log (user_name, engagement_id, event_type, details)
            VALUES ('system', ?, 'population_imported', ?)
            """,
            (engagement_id, f"Inserted {inserted} population rows"),
        )
        conn.commit()
    return {"inserted": inserted, "duplicates": sorted(duplicates)}


def get_population_by_engagement(engagement_id):
    return fetch_all(
        "SELECT * FROM population WHERE engagement_id = ? ORDER BY transaction_date, id",
        [engagement_id],
    )


def get_population_items(
    engagement_id,
    account_code=None,
    performance_materiality=0,
    clearly_trivial_threshold=0,
    include_high_value=True,
    include_trivial=True,
):
    clauses = ["engagement_id = ?"]
    params = [engagement_id]
    if account_code:
        clauses.append("account_code = ?")
        params.append(account_code)
    if not include_high_value:
        clauses.append("COALESCE(amount, 0) <= ?")
        params.append(performance_materiality or 0)
    if not include_trivial:
        clauses.append("COALESCE(amount, 0) >= ?")
        params.append(clearly_trivial_threshold or 0)
    query = f"SELECT * FROM population WHERE {' AND '.join(clauses)} ORDER BY transaction_date, id"
    items = fetch_all(query, params)
    high_value_threshold = performance_materiality or 0
    trivial_threshold = clearly_trivial_threshold or 0
    for item in items:
        amount = item.get("amount") or 0
        item["is_high_value"] = bool(amount > high_value_threshold and high_value_threshold > 0)
        item["is_trivial"] = bool(amount < trivial_threshold and trivial_threshold > 0)
    return items


def get_population_item(item_id):
    return fetch_one("SELECT * FROM population WHERE id = ?", [item_id])


def update_population_item(item_id, data, acted_by=None):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE population
            SET account_code = ?, transaction_ref = ?, description = ?, transaction_date = ?, amount = ?
            WHERE id = ?
            """,
            (
                data.get("account_code"),
                data.get("transaction_ref"),
                data.get("description"),
                data.get("transaction_date"),
                float(data.get("amount") or 0),
                item_id,
            ),
        )
        engagement = conn.execute("SELECT engagement_id FROM population WHERE id = ?", (item_id,)).fetchone()
        conn.execute(
            """
            INSERT INTO audit_log (user_name, engagement_id, event_type, details)
            VALUES (?, ?, 'population_updated', ?)
            """,
            (acted_by or "system", (engagement[0] if engagement else None), f"Updated population row {item_id}"),
        )
        conn.commit()
    return get_population_item(item_id)


def delete_population_item(item_id, acted_by=None):
    with get_connection() as conn:
        row = conn.execute("SELECT engagement_id FROM population WHERE id = ?", (item_id,)).fetchone()
        conn.execute("DELETE FROM population WHERE id = ?", (item_id,))
        conn.execute(
            """
            INSERT INTO audit_log (user_name, engagement_id, event_type, details)
            VALUES (?, ?, 'population_deleted', ?)
            """,
            (acted_by or "system", (row[0] if row else None), f"Deleted population row {item_id}"),
        )
        conn.commit()
    return {"deleted": True}


def clear_population(engagement_id, acted_by=None):
    with get_connection() as conn:
        deleted_count = conn.execute("SELECT COUNT(*) FROM population WHERE engagement_id = ?", (engagement_id,)).fetchone()[0]
        conn.execute("DELETE FROM population WHERE engagement_id = ?", (engagement_id,))
        _insert_audit_event(
            conn,
            acted_by or "system",
            "population_cleared",
            f"Cleared {deleted_count} population rows",
            engagement_id=engagement_id,
        )
        conn.commit()
    return {"deleted": deleted_count}


def get_population_account_stats(engagement_id, performance_materiality=0, clearly_trivial_threshold=0):
    return fetch_all(
        """
        SELECT
          account_code,
          COUNT(*) AS item_count,
          COALESCE(SUM(amount), 0) AS total_value,
          SUM(CASE WHEN amount > ? THEN 1 ELSE 0 END) AS high_value_count,
          SUM(CASE WHEN amount >= ? AND amount <= ? THEN 1 ELSE 0 END) AS sampling_population_count,
          SUM(CASE WHEN amount < ? THEN 1 ELSE 0 END) AS trivial_count
        FROM population
        WHERE engagement_id = ?
        GROUP BY account_code
        ORDER BY total_value DESC
        """,
        [
            performance_materiality or 0,
            clearly_trivial_threshold or 0,
            performance_materiality or 0,
            clearly_trivial_threshold or 0,
            engagement_id,
        ],
    )


def get_population_summary(engagement_id, performance_materiality=None, clearly_trivial_threshold=None):
    query = """
        SELECT
            COUNT(*) AS total_items,
            COALESCE(SUM(amount), 0) AS total_value,
            SUM(CASE WHEN amount > ? THEN 1 ELSE 0 END) AS items_above_performance_materiality,
            SUM(CASE WHEN amount >= ? AND amount <= ? THEN 1 ELSE 0 END) AS sampling_population_items,
            SUM(CASE WHEN amount < ? THEN 1 ELSE 0 END) AS items_below_clearly_trivial,
            COALESCE(SUM(CASE WHEN amount >= ? AND amount <= ? THEN amount ELSE 0 END), 0) AS sampling_population_value,
            COUNT(DISTINCT account_code) AS account_count
        FROM population
        WHERE engagement_id = ?
    """
    perf = performance_materiality or 0
    trivial = clearly_trivial_threshold or 0
    summary = fetch_one(query, [perf, trivial, perf, trivial, trivial, perf, engagement_id])
    # Compatibility aliases for existing UI fields.
    summary["items_above_materiality"] = summary["items_above_performance_materiality"]
    summary["remaining_items"] = summary["sampling_population_items"]
    summary["remaining_value"] = summary["sampling_population_value"]
    summary["account_stats"] = get_population_account_stats(engagement_id, perf, trivial)
    return summary


def get_high_value_population_items(engagement_id, performance_materiality):
    return fetch_all(
        """
        SELECT *
        FROM population
        WHERE engagement_id = ? AND amount > ?
        ORDER BY amount DESC, transaction_date, id
        """,
        [engagement_id, performance_materiality or 0],
    )


def create_sample_run(run):
    query = """
    INSERT INTO sample_runs (
      engagement_id, auditor_name, sampling_method, population_count, population_value,
            materiality, performance_materiality, clearly_trivial_threshold,
            confidence_level, expected_error_rate, tolerable_error_rate, sample_size, random_seed,
      high_value_count, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with get_connection() as conn:
        run_id = _insert_and_get_id(conn, query, [
            run["engagement_id"],
            run["auditor_name"],
            run["sampling_method"],
            run["population_count"],
            run["population_value"],
            run["materiality"],
                        run["performance_materiality"],
                        run["clearly_trivial_threshold"],
            run["confidence_level"],
            run["expected_error_rate"],
            run["tolerable_error_rate"],
            run["sample_size"],
            run.get("random_seed"),
            run["high_value_count"],
            run.get("notes"),
        ])
        conn.commit()
        conn.execute(
            """
            INSERT INTO audit_log (
              user_name,
              engagement_id,
              event_type,
              sampling_method,
              materiality,
                            performance_materiality,
                            clearly_trivial_threshold,
              random_seed,
              sample_size,
              run_id,
              details
                        ) VALUES (?, ?, 'sample_run_created', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.get("auditor_name") or "system",
                run["engagement_id"],
                run["sampling_method"],
                run["materiality"],
                                run["performance_materiality"],
                                run["clearly_trivial_threshold"],
                run.get("random_seed"),
                run["sample_size"],
                run_id,
                run.get("notes") or "Sample run recorded",
            ),
        )
        conn.commit()
        return fetch_one("SELECT * FROM sample_runs WHERE id = ?", [run_id])


def add_sample_output(run_id, outputs):
    query = """
    INSERT INTO sample_output (run_id, population_id, is_high_value, stratum, selected_reason)
    VALUES (?, ?, ?, ?, ?)
    """
    with get_connection() as conn:
        for item in outputs:
            conn.execute(query, [
                run_id,
                item["population_id"],
                item.get("is_high_value", False),
                item.get("stratum"),
                item.get("selected_reason", "sample"),
            ])
        conn.commit()


def get_sample_runs(engagement_id):
    if engagement_id:
        return fetch_all(
            """
            SELECT sr.*, e.client_name, e.engagement_ref
            FROM sample_runs sr
            JOIN engagements e ON e.id = sr.engagement_id
            WHERE sr.engagement_id = ?
            ORDER BY sr.run_timestamp DESC
            """,
            [engagement_id],
        )
    return fetch_all(
        """
        SELECT sr.*, e.client_name, e.engagement_ref
        FROM sample_runs sr
        JOIN engagements e ON e.id = sr.engagement_id
        ORDER BY sr.run_timestamp DESC
        """
    )


def delete_sample_output_item(output_id, acted_by=None):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT so.id, so.run_id, p.engagement_id
            FROM sample_output so
            LEFT JOIN population p ON p.id = so.population_id
            WHERE so.id = ?
            """,
            (output_id,),
        ).fetchone()
        if row is None:
            return {"deleted": False, "message": "Sample record not found"}

        conn.execute("DELETE FROM sample_output WHERE id = ?", (output_id,))
        _insert_audit_event(
            conn,
            acted_by or "system",
            "sample_record_deleted",
            f"Deleted sample output row {output_id}",
            engagement_id=row[2],
            sample_size=1,
        )
        conn.commit()
    return {"deleted": True}


def void_sample_run(run_id, acted_by=None):
    with get_connection() as conn:
        run = conn.execute("SELECT id, engagement_id, is_voided FROM sample_runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            return {"voided": False, "message": "Sample run not found"}
        if int(run[2] or 0) == 1:
            return {"voided": False, "message": "Sample run already voided"}

        conn.execute(
            "UPDATE sample_runs SET is_voided = 1, voided_at = CURRENT_TIMESTAMP, voided_by = ? WHERE id = ?",
            (acted_by or "system", run_id),
        )
        conn.execute("DELETE FROM sample_output WHERE run_id = ?", (run_id,))
        conn.execute("UPDATE audit_log SET is_voided = 1 WHERE run_id = ?", (run_id,))
        _insert_audit_event(
            conn,
            acted_by or "system",
            "sample_run_voided",
            f"Voided sample run {run_id}",
            engagement_id=run[1],
            run_id=run_id,
        )
        conn.commit()
    return {"voided": True}


def get_sample_output(run_id):
    return fetch_all(
        """
        SELECT so.*, p.engagement_id, p.account_code, p.transaction_ref, p.description, p.transaction_date, p.amount
        FROM sample_output so
        JOIN population p ON so.population_id = p.id
        WHERE so.run_id = ?
        ORDER BY p.transaction_date, p.id
        """,
        [run_id],
    )


def get_high_value_items(run_id):
    return fetch_all(
        """
        SELECT so.*, p.engagement_id, p.account_code, p.transaction_ref, p.description, p.transaction_date, p.amount
        FROM sample_output so
        JOIN population p ON so.population_id = p.id
        WHERE so.run_id = ? AND so.is_high_value = 1
        ORDER BY p.transaction_date, p.id
        """,
        [run_id],
    )


def get_audit_log(engagement_id=None, user_name=None, method=None, from_date=None, to_date=None, is_voided=None):
    clauses = []
    params = []

    if engagement_id is not None:
        clauses.append("al.engagement_id = ?")
        params.append(engagement_id)
    if user_name:
        clauses.append("lower(al.user_name) = lower(?)")
        params.append(user_name)
    if method:
        clauses.append("lower(al.sampling_method) = lower(?)")
        params.append(method)
    if from_date:
        if DB_BACKEND == "postgres":
            clauses.append("al.event_timestamp::timestamp >= ?::timestamp")
        else:
            clauses.append("datetime(al.event_timestamp) >= datetime(?)")
        params.append(from_date)
    if to_date:
        if DB_BACKEND == "postgres":
            clauses.append("al.event_timestamp::timestamp <= ?::timestamp")
        else:
            clauses.append("datetime(al.event_timestamp) <= datetime(?)")
        params.append(to_date)
    if is_voided is not None:
        clauses.append("COALESCE(al.is_voided, 0) = ?")
        params.append(1 if bool(is_voided) else 0)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT al.*, e.client_name, e.engagement_ref, au.first_name, au.surname, au.profile_picture
        FROM audit_log al
        LEFT JOIN engagements e ON e.id = al.engagement_id
        LEFT JOIN admin_users au ON lower(au.username) = lower(al.user_name)
        {where_sql}
        ORDER BY al.event_timestamp DESC, al.id DESC
    """
    return fetch_all(query, params)


def delete_voided_audit_log_entries(acted_by=None):
    with get_connection() as conn:
        deleted = conn.execute("SELECT COUNT(*) FROM audit_log WHERE COALESCE(is_voided, 0) = 1").fetchone()[0]
        conn.execute("DELETE FROM audit_log WHERE COALESCE(is_voided, 0) = 1")
        _insert_audit_event(
            conn,
            acted_by or "system",
            "audit_log_voided_deleted",
            f"Deleted {deleted} voided audit log entries",
            engagement_id=None,
        )
        conn.commit()
    return {"deleted": deleted}


def get_population_all(account_code=None):
    clauses = []
    params = []
    if account_code:
        clauses.append("p.account_code = ?")
        params.append(account_code)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT p.*, e.client_name, e.engagement_ref
        FROM population p
        LEFT JOIN engagements e ON e.id = p.engagement_id
        {where_sql}
        ORDER BY p.engagement_id, p.transaction_date, p.id
    """
    return fetch_all(query, params)
