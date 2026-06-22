from datetime import date
from typing import Annotated

import psycopg
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from app.database import get_connection

app = FastAPI(title="Patient Exams API", version="1.0.0")


class ExamRow(BaseModel):
    id: int
    patient_id: int
    exam_date: date
    notes: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/exams", response_model=list[ExamRow])
def list_exams(
    patient_id: Annotated[int | None, Query(
        description="Filter by patient")] = None,
) -> list[ExamRow]:
    """Return deduplicated exam rows from patient_exams."""
    sql = """
        SELECT id, patient_id, exam_date, notes
        FROM patient_exams
    """
    params: list[int] = []
    if patient_id is not None:
        sql += " WHERE patient_id = %s"
        params.append(patient_id)
    sql += " ORDER BY patient_id, exam_date, id"

    try:
        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
    except psycopg.OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable. Check that Postgres is running and DATABASE_URL is correct.",
        ) from exc
    except psycopg.Error as exc:
        raise HTTPException(
            status_code=500,
            detail="Database query failed.",
        ) from exc

    return [ExamRow(**row) for row in rows]
