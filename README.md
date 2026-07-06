# VCCA Audit Sampling Toolkit

A full-stack audit sampling web application for Victoria Chartered Certified Accountants (VCCA).

## Tech stack

- Backend: Python + Flask
- Database: SQLite
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

## Deploy to GitHub

Run these commands from the project root:

```powershell
git init
git add .
git commit -m "Prepare app for Render deployment"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

If the repository already exists locally, only run:

```powershell
git add .
git commit -m "Prepare app for Render deployment"
git push
```

## Deploy to Render (free web service)

This repo includes `render.yaml`, so you can deploy using Render Blueprint:

1. Push this code to GitHub.
2. In Render, choose New + > Blueprint.
3. Select your GitHub repo.
4. Render will detect `render.yaml` and create the web service.
5. Wait for build/deploy, then open the generated URL.

Current Render start command:

```text
mkdir -p data && gunicorn --chdir app/backend app:app
```

## Important note about free Render + SQLite

On Render free instances, local filesystem storage is ephemeral. This means your SQLite data can reset on redeploy or instance restart.

For persistent production data, move to a managed database (for example PostgreSQL) and update the data layer accordingly.

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