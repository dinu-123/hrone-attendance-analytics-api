# Employee Attendance & Analytics API

FastAPI and MongoDB implementation of the HROne Employee Attendance & Analytics assignment.

## Project Files

- `app/main.py` — API endpoints, business rules, and analytics.
- `openapi.yaml` — API contract and business rules R1–R10.
- `DATA_MODEL.md` — MongoDB collections and document structure.
- `REVIEW.md` — Review of starter-code issues and fixes.
- `DECISIONS.md` — Design and implementation decisions.

## Setup on Windows PowerShell

Run these commands from the project root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Configure `MONGO_URI` and `MONGO_DB` in `.env` to match your MongoDB setup. The command above preserves an existing `.env` file instead of overwriting it.

Ensure MongoDB is running before starting the API.

## Start the API

```powershell
python -m uvicorn app.main:app --port 8000
```

Health check: http://127.0.0.1:8000/health

Interactive API documentation: http://127.0.0.1:8000/docs

## Test Data

Sample data files and the destructive seed script are intentionally excluded from the public repository. The evaluator supplies its own dataset, and `DATA_MODEL.md` documents the expected MongoDB collections and fields.

For local testing, use a dedicated disposable database and configure `MONGO_URI` and `MONGO_DB` in your local `.env` file.

## Verification

Focused manual tests covered timestamp handling, overnight shifts, late and overtime calculations, punch-in and punch-out concurrency, regularization and audit history, analytics, pagination, and validation.

The five explain endpoints were tested against a synthetic dataset of 10,000 employees and 100,000 attendance records. All five reported at least one `IXSCAN` stage and no `COLLSCAN` stage. The department trend lookup also reported zero collection scans and used the attendance and employee indexes.

The department trend optimization was tested for a 10-day Engineering range. Using the same three-request benchmark, the original median was 8,751.1 ms and the optimized version's median was 458.4 ms, approximately 94.8% lower. In a separate run with one warm-up and five measured requests, the optimized median was 426.3 ms. These are local measurements, not a controlled production benchmark. The optimized response matched the original daily fields. Additional checks covered mid-month joiners, missing-attendance dates, weekends, the 92-day limit, and invalid date ranges. The disposable synthetic benchmark database was deleted after testing; no benchmark dataset is included in this repository.

These tests do not guarantee a particular evaluator score or replace a complete automated regression suite.

## Submission Safety

- Keep `.env` and credentials out of version control.
- Use `.env.example` to document the required environment variables.
- Remove temporary backups before submitting.
- Review staged files before committing or publishing the repository.

## Automated Tests

Install the development dependencies and run the full regression suite:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -v .\tests
```

MongoDB must be running locally. Tests use a separate disposable database named for the test process and drop only that test database after the test session. Keep normal and production databases separate from test databases.
