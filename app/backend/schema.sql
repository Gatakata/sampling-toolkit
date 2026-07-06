-- Logical schema reference for the toolkit.
-- Runtime uses SQLite in app/backend/db.py; this file is retained for SQL documentation.

-- Audit engagements
CREATE TABLE IF NOT EXISTS engagements (
  id SERIAL PRIMARY KEY,
  client_name VARCHAR(255),
  engagement_ref VARCHAR(100),
  auditor_name VARCHAR(255),
  financial_year VARCHAR(20),
  materiality NUMERIC(18,2),
  performance_materiality NUMERIC(18,2),
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Admin users and sessions
CREATE TABLE IF NOT EXISTS admin_users (
  id SERIAL PRIMARY KEY,
  username VARCHAR(255) UNIQUE NOT NULL,
  first_name VARCHAR(255),
  surname VARCHAR(255),
  profile_picture TEXT,
  email VARCHAR(255) UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admin_sessions (
  token TEXT PRIMARY KEY,
  admin_id INTEGER REFERENCES admin_users(id) ON DELETE CASCADE,
  created_at TIMESTAMP NOT NULL,
  expires_at TIMESTAMP NOT NULL
);

-- Population data (transaction listings)
CREATE TABLE IF NOT EXISTS population (
  id SERIAL PRIMARY KEY,
  engagement_id INTEGER REFERENCES engagements(id) ON DELETE CASCADE,
  account_code VARCHAR(100),
  transaction_ref VARCHAR(100),
  description TEXT,
  transaction_date DATE,
  amount NUMERIC(18,2),
  is_high_value BOOLEAN DEFAULT FALSE
);

-- Sample runs
CREATE TABLE IF NOT EXISTS sample_runs (
  id SERIAL PRIMARY KEY,
  engagement_id INTEGER REFERENCES engagements(id) ON DELETE CASCADE,
  run_timestamp TIMESTAMP DEFAULT NOW(),
  auditor_name VARCHAR(255),
  sampling_method VARCHAR(50),
  population_count INTEGER,
  population_value NUMERIC(18,2),
  materiality NUMERIC(18,2),
  confidence_level NUMERIC(5,2),
  expected_error_rate NUMERIC(5,2),
  tolerable_error_rate NUMERIC(5,2),
  sample_size INTEGER,
  random_seed INTEGER,
  high_value_count INTEGER,
  notes TEXT
);

-- Sample output (selected items)
CREATE TABLE IF NOT EXISTS sample_output (
  id SERIAL PRIMARY KEY,
  run_id INTEGER REFERENCES sample_runs(id) ON DELETE CASCADE,
  population_id INTEGER REFERENCES population(id),
  is_high_value BOOLEAN DEFAULT FALSE,
  stratum VARCHAR(50),
  selected_reason VARCHAR(50)
);

-- Immutable operational log
CREATE TABLE IF NOT EXISTS audit_log (
  id SERIAL PRIMARY KEY,
  event_timestamp TIMESTAMP DEFAULT NOW(),
  user_name VARCHAR(255),
  engagement_id INTEGER REFERENCES engagements(id) ON DELETE CASCADE,
  event_type VARCHAR(100),
  sampling_method VARCHAR(50),
  materiality NUMERIC(18,2),
  random_seed INTEGER,
  sample_size INTEGER,
  details TEXT
);
