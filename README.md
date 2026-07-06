# VCCA Audit Sampling Toolkit

A full-stack audit sampling web application for Victoria Chartered Certified Accountants (VCCA).

## Tech stack

- Backend: Python + Flask
- Database:
	- Local/dev: SQLite
	- Production: PostgreSQL
- Frontend: HTML, CSS, vanilla JavaScript

## Local setup

1. Create and activate a virtual environment.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies.

```powershell
pip install -r requirements.txt
```

3. Run the app.

```powershell
python app/backend/app.py
```

4. Open `http://127.0.0.1:5000`.

The backend auto-initializes the SQLite database at `data/audit_sampling.sqlite3` by default.

## Environment variables

- `DATABASE_URL`: if set, the app uses PostgreSQL (production mode).
- `DB_PATH`: used only when `DATABASE_URL` is not set (SQLite mode).
- `ADMIN_USERNAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`: bootstrap admin account values.

## Step-by-step: GitHub -> Render -> PostgreSQL -> live app

### 1. Push code to GitHub

If this is a fresh local folder:

```powershell
git init
git add .
git commit -m "Add PostgreSQL production deployment"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

If the repo is already connected:

```powershell
git add .
git commit -m "Add PostgreSQL production deployment"
git push
```

### 2. Deploy with Render Blueprint

This project includes `render.yaml`, which provisions:

- A Python web service
- A managed PostgreSQL database
- `DATABASE_URL` linked automatically from that database

In Render:

1. Go to Dashboard.
2. Click **New +**.
3. Click **Blueprint**.
4. Connect/select your GitHub repository.
5. Confirm detected `render.yaml` services.
6. Click **Apply**.

### 3. Configure required secrets in Render

Open the created web service -> **Environment** and set:

- `ADMIN_USERNAME`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD` (strong password)

Then redeploy if prompted.

### 4. Verify database linkage

Open the web service -> **Environment** and confirm `DATABASE_URL` is present.

You do not need to manually run schema SQL. The app initializes/migrates tables on startup.

### 5. Validate deployment

1. Open the Render service URL.
2. Log in with your configured admin credentials.
3. Create a test engagement and one sample run.
4. Refresh and verify data still exists.

If data persists after refresh/redeploy, PostgreSQL is wired correctly.

## Render notes

- Free Render web instances can sleep when idle.
- If Render free PostgreSQL is unavailable in your region/account, select the lowest paid PostgreSQL plan while keeping the same `render.yaml` structure.

## API endpoints

- `POST /api/engagements`
- `GET /api/engagements`
- `GET /api/engagements/:id`
- `POST /api/engagements/:id/population`
- `GET /api/engagements/:id/population/summary`
- `POST /api/engagements/:id/run-sample`
- `GET /api/engagements/:id/runs`
- `GET /api/runs/:run_id/output`
- `GET /api/runs/:run_id/high-value`