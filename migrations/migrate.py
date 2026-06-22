#!/usr/bin/env python3

import os
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://localhost:5432/patient_exams_trial",
)

MIGRATION_KEY = "001_patient_exams_dedupe"
TABLE = "patient_exams"
CONSTRAINT = "uq_patient_exam_date"

CREATE_META = """
CREATE TABLE IF NOT EXISTS _migration_meta (
    key         TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id          SERIAL PRIMARY KEY,
    patient_id  INTEGER NOT NULL,
    exam_date   DATE NOT NULL,
    notes       TEXT
);
"""

SEED_ROWS = [
    (101, "2024-01-15", "annual checkup"),
    (101, "2024-01-15", "duplicate annual checkup"),
    (101, "2024-06-01", "follow-up"),
    (202, "2024-03-10", "screening"),
    (202, "2024-03-10", "duplicate screening"),
    (202, "2024-03-10", "second duplicate screening"),
    (303, "2024-05-20", "consultation"),
    (404, "2024-07-04", "lab work"),
    (404, "2024-07-04", "duplicate lab work"),
]

INSERT_SEED = f"""
INSERT INTO {TABLE} (patient_id, exam_date, notes)
VALUES (%s, %s, %s);
"""

# Single-pass dedup: O(n log n) window sort
DEDUPE_SQL = f"""
DELETE FROM {TABLE}
WHERE id IN (
    SELECT id
    FROM (
        SELECT id,
               ROW_NUMBER() OVER (
                   PARTITION BY patient_id, exam_date
                   ORDER BY id ASC
               ) AS rn
        FROM {TABLE}
    ) ranked
    WHERE rn > 1
);
"""

ADD_CONSTRAINT = f"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = '{CONSTRAINT}'
    ) THEN
        ALTER TABLE {TABLE}
            ADD CONSTRAINT {CONSTRAINT} UNIQUE (patient_id, exam_date);
    END IF;
END $$;
"""

MARK_MIGRATION = """
INSERT INTO _migration_meta (key)
VALUES (%s)
ON CONFLICT (key) DO NOTHING;
"""


def run_migration(conn: psycopg.Connection) -> None:
    with conn.transaction():
        conn.execute(CREATE_META)
        conn.execute(CREATE_TABLE)

        seeded = conn.execute(
            "SELECT 1 FROM _migration_meta WHERE key = %s",
            (MIGRATION_KEY,),
        ).fetchone()

        if not seeded:
            for patient_id, exam_date, notes in SEED_ROWS:
                conn.execute(INSERT_SEED, (patient_id, exam_date, notes))
            print(
                f"Seeded {len(SEED_ROWS)} rows (includes intentional duplicates).")
        else:
            print("Seed step skipped (already applied).")

        deleted = conn.execute(DEDUPE_SQL).rowcount
        if deleted:
            print(
                f"Deduplicated: removed {deleted} duplicate row(s). Keeper: lowest id per (patient_id, exam_date).")
        else:
            print("Dedup step: no duplicates found.")

        conn.execute(ADD_CONSTRAINT)
        print(
            f"Unique constraint '{CONSTRAINT}' ensured on ({TABLE}.patient_id, {TABLE}.exam_date).")

        conn.execute(MARK_MIGRATION, (MIGRATION_KEY,))


def main() -> int:
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            run_migration(conn)
    except psycopg.OperationalError as exc:
        print(f"Database connection failed: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1

    print("Migration completed successfully (safe to rerun).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
