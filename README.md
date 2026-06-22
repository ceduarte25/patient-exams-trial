# Patient Exams — FastAPI + Postgres Trial Task

Local throwaway Postgres database with an idempotent migration (seed → dedupe → unique constraint) and a FastAPI read endpoint.

## Prerequisites

- Python 3.11+ (Homebrew `python3` works)
- PostgreSQL 15+ running locally (`brew services start postgresql@17`)

## Quick start

```bash
# 1. Create throwaway database
createdb patient_exams_trial

# 2. Virtualenv + dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Optional: copy env file (defaults match below)
cp .env.example .env

# 4. Run migration (safe to run multiple times)
python migrations/migrate.py

# 5. Start API
uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000/docs for Swagger UI.

### Environment

| Variable       | Default                                           |
| -------------- | ------------------------------------------------- |
| `DATABASE_URL` | `postgresql://localhost:5432/patient_exams_trial` |

## Migration behavior

**Table:** `patient_exams` — columns `id`, `patient_id`, `exam_date`, `notes`.

**Seed:** Inserts 9 rows on first run only (tracked in `_migration_meta`). Includes duplicate `(patient_id, exam_date)` pairs.

**Keeper rule:** When duplicates exist, **keep the row with the smallest `id`** (earliest inserted) and delete the rest.

**Dedup:** Single `DELETE` using `ROW_NUMBER() OVER (PARTITION BY patient_id, exam_date ORDER BY id)` — O(n log n) sort within partitions, one pass.

**Constraint:** `uq_patient_exam_date UNIQUE (patient_id, exam_date)` — added only if missing.

**Idempotency guards:**

1. `CREATE TABLE IF NOT EXISTS` for schema objects
2. Seed runs once (key `001_patient_exams_dedupe` in `_migration_meta`)
3. Dedup is a no-op when no duplicates remain
4. Constraint added inside `DO $$ ... IF NOT EXISTS` block

## API

| Method | Path                    | Description                   |
| ------ | ----------------------- | ----------------------------- |
| GET    | `/health`               | Liveness check                |
| GET    | `/exams`                | All deduplicated rows as JSON |
| GET    | `/exams?patient_id=101` | Filter by patient             |

Example:

```bash
curl -s http://127.0.0.1:8000/exams | python3 -m json.tool
```

Errors: `503` if Postgres is down; `500` on query failure.

## Validation (idempotency + constraint)

Run these after setup:

```bash
# Run migration twice — second run must exit 0 with "Seed step skipped" and no errors
python migrations/migrate.py
python migrations/migrate.py

# Confirm row count matches distinct (patient_id, exam_date) pairs
psql patient_exams_trial -c "
  SELECT COUNT(*) AS total,
         COUNT(DISTINCT (patient_id, exam_date)) AS distinct_pairs
  FROM patient_exams;"

# Attempt duplicate insert — must fail with unique_violation
psql patient_exams_trial -c "
  INSERT INTO patient_exams (patient_id, exam_date) VALUES (101, '2024-01-15');"
# Expected: ERROR: duplicate key value violates unique constraint \"uq_patient_exam_date\"
```

Expected after migration: **5 rows** (9 seeded − 4 duplicates removed).
