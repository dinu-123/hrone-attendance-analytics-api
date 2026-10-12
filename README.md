# Employee Attendance & Analytics API

FastAPI and MongoDB implementation of the HROne Employee Attendance & Analytics assignment.

## Project Files

- `app/main.py` — API endpoints, business rules, and analytics.
- `openapi.yaml` — API contract and business rules R1–R10.
- `DATA_MODEL.md` — MongoDB collections and document structure.
- `REVIEW.md` — Review of starter-code issues and fixes.
- `DECISIONS.md` — Design and implementation decisions.
- `sample_data/` — Sample employee and attendance documents.
- `sample_seed.py` — Optional sample-data loader.

## Setup on Windows PowerShell

Run these commands from the project root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create `.env` from `.env.example` if it does not already exist. Configure `MONGO_URI` and `MONGO_DB` to match your MongoDB setup.

Ensure MongoDB is running before starting the API.

## Start the API

```powershell
python -m uvicorn app.main:app --port 8000
```

Health check: http://127.0.0.1:8000/health

Interactive API documentation: http://127.0.0.1:8000/docs

## Optional Sample Data

**Warning:** `sample_seed.py` deletes all existing documents in the configured `employees` and `attendance_logs` collections before loading sample data. Run it only against a disposable development database.

```powershell
python sample_seed.py
```

## Verification

Focused manual tests covered timestamp handling, overnight shifts, late and overtime calculations, punch-in and punch-out concurrency, regularization and audit history, analytics, pagination, and validation.

The five explain endpoints were tested against 100,000 synthetic attendance records. All five reported at least one `IXSCAN` stage and no `COLLSCAN` stage. Synthetic test records were removed after testing.

These tests do not guarantee a particular evaluator score or replace a complete automated regression suite.

## Submission Safety

- Keep `.env` and credentials out of version control.
- Use `.env.example` to document the required environment variables.
- Remove temporary backups before submitting.
- Review staged files before committing or publishing the repository.