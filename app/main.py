"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
import json
from bson import json_util
from datetime import datetime, time, timedelta, timezone
from typing import Literal, Optional
from contextvars import ContextVar
from contextlib import asynccontextmanager

from decimal import Decimal, ROUND_HALF_UP

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from pymongo import MongoClient

from pymongo.errors import DuplicateKeyError

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_database_indexes()
    yield


app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0", lifespan=lifespan)

# Used by the admin explain endpoint to capture an aggregation pipeline.
_EXPLAIN_CAPTURE = ContextVar("EXPLAIN_CAPTURE", default=None)


def aggregate_results(collection, pipeline):
    capture = _EXPLAIN_CAPTURE.get()

    if capture is not None:
        # Capture the exact pipeline without executing it.
        capture["collection"] = collection.name
        capture["pipeline"] = pipeline
        return []

    return list(collection.aggregate(pipeline))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
# def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
#     h, m = map(int, shift_start.split(":"))
#     start = punch_in.replace(hour=h, minute=m, second=0, microsecond=0)
#     minutes = int((punch_in - start).total_seconds() / 60)
#     return minutes if minutes > 10 else 0

def compute_late_minutes(
    punch_in: datetime,
    shift_start: str,
    attendance_date: Optional[str] = None,
) -> int:
    if punch_in.tzinfo is None:
        punch_in = punch_in.replace(tzinfo=timezone.utc)

    punch_ist = punch_in.astimezone(IST)

    if attendance_date is None:
        shift_day = punch_ist.date()
    else:
        shift_day = datetime.fromisoformat(attendance_date).date()

    start_hour, start_minute = map(int, shift_start.split(":"))
    shift_start_at = datetime.combine(
        shift_day,
        time(start_hour, start_minute),
        tzinfo=IST,
    )

    elapsed_seconds = int(
        (punch_ist - shift_start_at).total_seconds()
    )

    # A punch is late only when it is strictly over 10 minutes late.
    if elapsed_seconds > 600:
        return elapsed_seconds // 60

    return 0

def datetime_to_epoch_ms(value: Optional[datetime]) -> Optional[int]:
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    value = value.replace(microsecond=0)
    return int(value.timestamp()) * 1000

def serialize_attendance(doc: dict) -> dict:
    history = []

    for entry in doc.get("history", []):
        changes = {}

        for field, change in (entry.get("changes") or {}).items():
            old_value = change.get("from")
            new_value = change.get("to")

            if field in ("punch_in", "punch_out"):
                if isinstance(old_value, datetime):
                    old_value = datetime_to_epoch_ms(old_value)

                if isinstance(new_value, datetime):
                    new_value = datetime_to_epoch_ms(new_value)

            changes[field] = {
                "from": old_value,
                "to": new_value,
            }

        history.append({
            "at": datetime_to_epoch_ms(entry.get("at")),
            "by": entry.get("by"),
            "reason": entry.get("reason"),
            "changes": changes,
        })

    return {
        "emp_code": doc.get("emp_code"),
        "date": doc.get("date"),
        "status": doc.get("status"),
        "punch_in": datetime_to_epoch_ms(doc.get("punch_in")),
        "punch_out": datetime_to_epoch_ms(doc.get("punch_out")),
        "work_hours": doc.get("work_hours"),
        "late_minutes": doc.get("late_minutes", 0),
        "overtime_minutes": doc.get("overtime_minutes", 0),
        "half_day": doc.get("half_day", False),
        "history": history,
    }


# def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
#     return round((punch_out - punch_in).total_seconds() / 3600, 2)

def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    if punch_in.tzinfo is None:
        punch_in = punch_in.replace(tzinfo=timezone.utc)

    if punch_out.tzinfo is None:
        punch_out = punch_out.replace(tzinfo=timezone.utc)

    seconds = int((punch_out - punch_in).total_seconds())

    hours = (
        Decimal(seconds) / Decimal(3600)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return float(hours)


# def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:
#     h, m = map(int, shift_end.split(":"))
#     end = datetime.fromisoformat(date_str).replace(hour=h, minute=m, tzinfo=IST)
#     return max(0, int((punch_out - end).total_seconds() / 60))

def compute_overtime(
    punch_out: datetime,
    shift_end: str,
    date_str: str,
    shift_start: str,
) -> int:
    end_hour, end_minute = map(int, shift_end.split(":"))
    shift_end_day = datetime.fromisoformat(date_str).date()

    if shift_end <= shift_start:
        shift_end_day += timedelta(days=1)

    shift_end_at = datetime.combine(
        shift_end_day,
        time(end_hour, end_minute),
        tzinfo=IST,
    )

    if punch_out.tzinfo is None:
        punch_out = punch_out.replace(tzinfo=timezone.utc)

    punch_out = punch_out.astimezone(timezone.utc)

    elapsed_seconds = int(
        (
            punch_out
            - shift_end_at.astimezone(timezone.utc)
        ).total_seconds()
    )

    overtime_minutes = max(0, elapsed_seconds // 60)

    return overtime_minutes if overtime_minutes >= 30 else 0


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
# class EmployeeIn(BaseModel):
#     emp_code: str
#     name: str
#     email: str
#     department: str
#     shift_start: str = "09:30"
#     shift_end: str = "18:30"
#     joined_on: str

class EmployeeIn(BaseModel):
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(
        max_length=120,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = Field(
        default="09:30",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
    )
    shift_end: str = Field(
        default="18:30",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
    )
    joined_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("joined_on")
    @classmethod
    def validate_joined_on(cls, value: str) -> str:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(
                "joined_on must be a valid YYYY-MM-DD date"
            ) from exc

        if parsed.isoformat() != value:
            raise ValueError(
                "joined_on must be a valid YYYY-MM-DD date"
            )

        return value


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[StrictInt] = None
    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"

class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[StrictInt] = None


class RegularizeIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: Optional[
        Literal["PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"]
    ] = None

    punch_in: Optional[StrictInt] = None
    punch_out: Optional[StrictInt] = None

    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)



# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #


def create_database_indexes():
    # Employees: unique business identifier.
    db.employees.create_index(
        [("emp_code", 1)],
        unique=True,
        name="uq_employees_emp_code",
    )

    # Employees: support department filtering and listing.
    db.employees.create_index(
        [("department", 1), ("emp_code", 1)],
        name="ix_employees_department_emp_code",
    )

    # Employees: support period-based headcount analytics.
    db.employees.create_index(
        [("joined_on", 1), ("department", 1)],
        name="ix_employees_joined_department",
    )

    # Attendance: only one record per employee per attendance date.
    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True,
        name="uq_attendance_emp_date",
    )

    # Attendance: support date sorting and pagination.
    db.attendance_logs.create_index(
        [("date", -1), ("emp_code", 1)],
        name="ix_attendance_date_emp",
    )

    # Attendance: support status-filtered date queries.
    db.attendance_logs.create_index(
        [("status", 1), ("date", -1), ("emp_code", 1)],
        name="ix_attendance_status_date_emp",
    )

    # Attendance: support finding an employee's latest punch-in.
    db.attendance_logs.create_index(
        [("emp_code", 1), ("punch_in", -1)],
        name="ix_attendance_emp_punch_in",
    )


@app.get("/health")
def health():
    try:
        client.admin.command("ping")
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="MongoDB unavailable"
        )

    return {"status": "ok"}



@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if body.shift_start == body.shift_end:
        raise HTTPException(
            status_code=422,
            detail="shift_start must differ from shift_end",
        )

    doc = body.model_dump()
    created_at = datetime.now(timezone.utc).replace(microsecond=0)
    doc["created_at"] = created_at

    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="emp_code already exists",
        )

    # Never expose MongoDB's internal _id.
    doc.pop("_id", None)

    # The API contract uses epoch milliseconds for instants.
    doc["created_at"] = int(created_at.timestamp()) * 1000

    return doc




@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    if page < 1:
        raise HTTPException(
            status_code=422,
            detail="page must be at least 1",
        )

    if page_size < 1 or page_size > 100:
        raise HTTPException(
            status_code=422,
            detail="page_size must be between 1 and 100",
        )

    query = {}
    if department is not None:
        query["department"] = department

    total = db.employees.count_documents(query)

    skip = (page - 1) * page_size

    items = list(
        db.employees.find(query, {"_id": 0})
        .sort("emp_code", 1)
        .skip(skip)
        .limit(page_size)
    )

    # Expose created_at as epoch milliseconds, not a datetime string.
    epoch = datetime(1970, 1, 1)
    for item in items:
        created_at = item.get("created_at")
        if isinstance(created_at, datetime):
            elapsed = created_at - epoch
            seconds = elapsed.days * 86400 + elapsed.seconds
            item["created_at"] = seconds * 1000

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }



# @app.post("/attendance/punch-in", status_code=201)
# def punch_in(body: PunchInIn):
#     emp = db.employees.find_one({"emp_code": body.emp_code})
#     ts = datetime.fromtimestamp(body.punched_at / 1000) if body.punched_at else datetime.now()
#     d = ts.date().isoformat()
#     if db.attendance_logs.find_one({"emp_code": body.emp_code, "date": d}):
#         raise HTTPException(409, "already punched in for this date")
#     doc = {
#         "emp_code": body.emp_code,
#         "date": d,
#         "status": body.status,
#         "punch_in": ts,
#         "punch_out": None,
#         "work_hours": None,
#         "late_minutes": compute_late_minutes(ts, emp["shift_start"]),
#         "overtime_minutes": 0,
#         "half_day": False,
#         "history": [],
#     }
#     res = db.attendance_logs.insert_one(doc)
#     doc["id"] = str(res.inserted_id)
#     doc.pop("_id", None)
#     return doc

@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    if "punched_at" in body.model_fields_set and body.punched_at is None:
            raise HTTPException(
                status_code=422,
                detail="punched_at must be epoch milliseconds",
            )
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    # Use current UTC time if punched_at was omitted.
    if body.punched_at is None:
        ts = datetime.now(timezone.utc).replace(microsecond=0)
    else:
        punched_at = body.punched_at

        # Reject seconds-like timestamps and out-of-range values.
        if (
            punched_at < 100_000_000_000
            or punched_at > 4_102_444_800_000
        ):
            raise HTTPException(
                status_code=422,
                detail="punched_at must be epoch milliseconds",
            )

        try:
            # Integer division truncates milliseconds to whole seconds.
            ts = datetime.fromtimestamp(
                punched_at // 1000,
                tz=timezone.utc,
            )
        except (OverflowError, OSError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="punched_at is out of range",
            )

    punch_ist = ts.astimezone(IST)
    attendance_day = punch_ist.date()

    shift_start = emp["shift_start"]
    shift_end = emp["shift_end"]

    # Overnight shift: an early-morning punch belongs to the
    # shift that started on the previous calendar day.
    if shift_end <= shift_start:
        end_hour, end_minute = map(int, shift_end.split(":"))
        shift_end_time = time(end_hour, end_minute)

        if punch_ist.time() < shift_end_time:
            attendance_day -= timedelta(days=1)

    attendance_date = attendance_day.isoformat()

    doc = {
        "emp_code": body.emp_code,
        "date": attendance_date,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(
            ts,
            shift_start,
            attendance_date,
        ),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        # The unique (emp_code, date) index is the concurrency safeguard.
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="already punched in for this date",
        )

    # Return the public API fields only; never expose MongoDB _id.
    doc.pop("_id", None)
    doc["punch_in"] = datetime_to_epoch_ms(doc["punch_in"])
    doc["punch_out"] = None

    return doc


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    if "punched_at" in body.model_fields_set and body.punched_at is None:
        raise HTTPException(
            status_code=422,
            detail="punched_at must be epoch milliseconds",
        )
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    if body.punched_at is None:
        ts = datetime.now(timezone.utc).replace(microsecond=0)
    else:
        punched_at = body.punched_at

        if (
            punched_at < 100_000_000_000
            or punched_at > 4_102_444_800_000
        ):
            raise HTTPException(
                status_code=422,
                detail="punched_at must be epoch milliseconds",
            )

        try:
            ts = datetime.fromtimestamp(
                punched_at // 1000,
                tz=timezone.utc,
            )
        except (OverflowError, OSError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="punched_at is out of range",
            )

    # Find the most recent punch-in at or before this punch-out.
    record = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "punch_in": {"$ne": None, "$lte": ts},
        },
        sort=[("punch_in", -1)],
    )

    if record is None:
        # Distinguish an earlier-than-punch-in timestamp from an
        # employee who has no punch-in record at all.
        later_record = db.attendance_logs.find_one(
            {
                "emp_code": body.emp_code,
                "punch_in": {"$ne": None},
            },
            sort=[("punch_in", -1)],
        )

        if later_record is not None:
            prior_punch_in = later_record["punch_in"]

            if prior_punch_in.tzinfo is None:
                prior_punch_in = prior_punch_in.replace(
                    tzinfo=timezone.utc
                )

            if ts <= prior_punch_in:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Punch-out must be after punch-in "
                        "and within 24 hours"
                    ),
                )

        raise HTTPException(
            status_code=404,
            detail="No punch-in found",
        )

    if record.get("punch_out") is not None:
        raise HTTPException(
            status_code=409,
            detail="This attendance record is already punched out",
        )

    punch_in_at = record["punch_in"]

    if punch_in_at.tzinfo is None:
        punch_in_at = punch_in_at.replace(tzinfo=timezone.utc)

    elapsed_seconds = (ts - punch_in_at).total_seconds()

    if elapsed_seconds <= 0 or elapsed_seconds > 24 * 60 * 60:
        raise HTTPException(
            status_code=422,
            detail="Punch-out must be after punch-in and within 24 hours",
        )

    work_hours = compute_work_hours(punch_in_at, ts)

    overtime_minutes = compute_overtime(
        ts,
        emp["shift_end"],
        record["date"],
        emp["shift_start"],
    )

    half_day = work_hours < 4.50

    # Atomic update: only one simultaneous punch-out can succeed.
    result = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
            "punch_out": None,
        },
        {
            "$set": {
                "punch_out": ts,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            }
        },
    )

    if result.modified_count != 1:
        raise HTTPException(
            status_code=409,
            detail="This attendance record was already updated",
        )

    updated = db.attendance_logs.find_one(
        {"_id": record["_id"]}
    )

    return serialize_attendance(updated)



# @app.get("/attendance")
# def list_attendance(
#     emp_code: Optional[str] = None,
#     date_from: Optional[str] = None,
#     date_to: Optional[str] = None,
#     status: Optional[str] = None,
#     page: int = 1,
#     page_size: int = 20,
# ):
#     q = {}
#     if emp_code:
#         q["emp_code"] = emp_code
#     if date_from or date_to:
#         q["date"] = {}
#         if date_from:
#             q["date"]["$gte"] = date_from
#         if date_to:
#             q["date"]["$lte"] = date_to
#     if status:
#         q["status"] = status
#     docs = list(db.attendance_logs.find(q))
#     docs.sort(key=lambda d: d["date"], reverse=True)
#     total = len(docs)
#     page_docs = docs[(page - 1) * page_size : page * page_size]
#     for d in page_docs:
#         d["id"] = str(d.pop("_id"))
#     return {"items": page_docs, "total": total, "page": page, "page_size": page_size}


@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(
    emp_code: str,
    date: str,
    body: RegularizeIn,
):
    # Validate the attendance date.
    try:
        parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
        if parsed_date.isoformat() != date:
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="date must use YYYY-MM-DD",
        )

    reason = body.reason.strip()
    regularized_by = body.regularized_by.strip()

    if not 5 <= len(reason) <= 200:
        raise HTTPException(
            status_code=422,
            detail="reason must contain 5 to 200 non-space characters",
        )

    if not 1 <= len(regularized_by) <= 50:
        raise HTTPException(
            status_code=422,
            detail="regularized_by must contain 1 to 50 characters",
        )

    employee = db.employees.find_one({"emp_code": emp_code})

    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    record = db.attendance_logs.find_one(
        {"emp_code": emp_code, "date": date}
    )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Attendance record not found",
        )

    supplied = body.model_fields_set

    # A supplied null is not a valid epoch-millisecond timestamp.
    for field in ("punch_in", "punch_out"):
        if field in supplied and getattr(body, field) is None:
            raise HTTPException(
                status_code=422,
                detail=f"{field} must be epoch milliseconds",
            )

    def parse_timestamp(field: str) -> datetime:
        value = getattr(body, field)

        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 100_000_000_000
            or value > 4_102_444_800_000
        ):
            raise HTTPException(
                status_code=422,
                detail=f"{field} must be a valid epoch-millisecond timestamp",
            )

        try:
            return datetime.fromtimestamp(
                value // 1000,
                tz=timezone.utc,
            )
        except (OverflowError, OSError, ValueError):
            raise HTTPException(
                status_code=422,
                detail=f"{field} is out of range",
            )

    # Work out the final status and punch times.
    final_status = (
        body.status if "status" in supplied else record["status"]
    )

    if "status" in supplied and body.status is None:
        raise HTTPException(
            status_code=422,
            detail="status cannot be null",
        )

    if final_status in ("ABSENT", "LEAVE"):
        if "punch_in" in supplied or "punch_out" in supplied:
            raise HTTPException(
                status_code=422,
                detail="ABSENT and LEAVE cannot include punch times",
            )

        final_punch_in = None
        final_punch_out = None
        late_minutes = 0
        work_hours = None
        overtime_minutes = 0
        half_day = False

    else:
        if "punch_in" in supplied:
            final_punch_in = parse_timestamp("punch_in")
        else:
            final_punch_in = record.get("punch_in")

        if "punch_out" in supplied:
            final_punch_out = parse_timestamp("punch_out")
        else:
            final_punch_out = record.get("punch_out")

        if final_punch_in is None:
            raise HTTPException(
                status_code=422,
                detail="Presence statuses require a punch_in",
            )

        # PyMongo may return naive datetimes. Treat them as UTC.
        if final_punch_in.tzinfo is None:
            final_punch_in = final_punch_in.replace(
                tzinfo=timezone.utc
            )
        else:
            final_punch_in = final_punch_in.astimezone(
                timezone.utc
            )

        if final_punch_out is not None:
            if final_punch_out.tzinfo is None:
                final_punch_out = final_punch_out.replace(
                    tzinfo=timezone.utc
                )
            else:
                final_punch_out = final_punch_out.astimezone(
                    timezone.utc
                )

        # Validate that punch-in belongs to this attendance date
        # in IST, including the overnight-shift rule.
        punch_in_ist = final_punch_in.astimezone(IST)
        attendance_day = punch_in_ist.date()

        shift_start = employee["shift_start"]
        shift_end = employee["shift_end"]

        if shift_end <= shift_start:
            end_hour, end_minute = map(int, shift_end.split(":"))
            if punch_in_ist.time() < time(end_hour, end_minute):
                attendance_day -= timedelta(days=1)

        if attendance_day.isoformat() != date:
            raise HTTPException(
                status_code=422,
                detail="punch_in must belong to the record's attendance date",
            )

        late_minutes = compute_late_minutes(
            final_punch_in,
            employee["shift_start"],
            date,
        )

        if final_punch_out is None:
            work_hours = None
            overtime_minutes = 0
            half_day = False
        else:
            elapsed_seconds = (
                final_punch_out - final_punch_in
            ).total_seconds()

            if elapsed_seconds <= 0 or elapsed_seconds > 24 * 60 * 60:
                raise HTTPException(
                    status_code=422,
                    detail="punch_out must be after punch_in and within 24 hours",
                )

            work_hours = compute_work_hours(
                final_punch_in,
                final_punch_out,
            )

            overtime_minutes = compute_overtime(
                final_punch_out,
                employee["shift_end"],
                date,
                employee["shift_start"],
            )

            half_day = work_hours < 4.50

    # Only changed fields belong in the audit entry.
    old_values = {
        "status": record.get("status"),
        "punch_in": record.get("punch_in"),
        "punch_out": record.get("punch_out"),
        "work_hours": record.get("work_hours"),
        "late_minutes": record.get("late_minutes", 0),
        "overtime_minutes": record.get("overtime_minutes", 0),
        "half_day": record.get("half_day", False),
    }

    new_values = {
        "status": final_status,
        "punch_in": final_punch_in,
        "punch_out": final_punch_out,
        "work_hours": work_hours,
        "late_minutes": late_minutes,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day,
    }

    changes = {}

    for field, new_value in new_values.items():
        old_value = old_values[field]

        if field in ("punch_in", "punch_out"):
            old_comparable = datetime_to_epoch_ms(old_value)
            new_comparable = datetime_to_epoch_ms(new_value)
        else:
            old_comparable = old_value
            new_comparable = new_value

        if old_comparable != new_comparable:
            changes[field] = {
                "from": old_value,
                "to": new_value,
            }

    if not changes:
        raise HTTPException(
            status_code=422,
            detail="The request does not change the attendance record",
        )

    history_entry = {
        "at": datetime.now(timezone.utc).replace(microsecond=0),
        "by": regularized_by,
        "reason": reason,
        "changes": changes,
    }

    # Optimistic concurrency: prevent two edits from silently
    # overwriting each other's changes or audit history.
    guard_fields = (
        "status",
        "punch_in",
        "punch_out",
        "work_hours",
        "late_minutes",
        "overtime_minutes",
        "half_day",
        "history",
    )

    guards = []

    for field in guard_fields:
        if field in record:
            guards.append({field: record[field]})
        else:
            guards.append({field: {"$exists": False}})

    result = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
            "$and": guards,
        },
        {
            "$set": new_values,
            "$push": {"history": history_entry},
        },
    )

    if result.modified_count != 1:
        raise HTTPException(
            status_code=409,
            detail="Attendance record changed concurrently; retry the request",
        )

    updated = db.attendance_logs.find_one(
        {"_id": record["_id"]}
    )

    return serialize_attendance(updated)



@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    # Validate pagination.
    if page < 1:
        raise HTTPException(
            status_code=422,
            detail="page must be at least 1",
        )

    if page_size < 1 or page_size > 100:
        raise HTTPException(
            status_code=422,
            detail="page_size must be between 1 and 100",
        )

    # Validate inclusive date filters.
    for field_name, value in (
        ("date_from", date_from),
        ("date_to", date_to),
    ):
        if value is not None:
            try:
                parsed_date = datetime.fromisoformat(value).date()
                if parsed_date.isoformat() != value:
                    raise ValueError
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"{field_name} must use YYYY-MM-DD",
                )

    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from must not be after date_to",
        )

    allowed_statuses = {
        "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
    }

    if status is not None and status not in allowed_statuses:
        raise HTTPException(
            status_code=422,
            detail="Invalid attendance status",
        )

    # Build one filter for both counting and retrieving records.
    query = {}

    if emp_code is not None:
        query["emp_code"] = emp_code

    if status is not None:
        query["status"] = status

    if date_from is not None or date_to is not None:
        date_filter = {}

        if date_from is not None:
            date_filter["$gte"] = date_from

        if date_to is not None:
            date_filter["$lte"] = date_to

        query["date"] = date_filter

    total = db.attendance_logs.count_documents(query)
    skip = (page - 1) * page_size

    records = list(
        db.attendance_logs.find(query)
        .sort([("date", -1), ("emp_code", 1)])
        .skip(skip)
        .limit(page_size)
    )

    # Convert stored BSON datetimes to epoch milliseconds.
    # The serializer excludes MongoDB's internal _id.
    items = [
        serialize_attendance(record)
        for record in records
    ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }



# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #

@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str):
    # Validate month format: YYYY-MM.
    try:
        parsed_month = datetime.strptime(month, "%Y-%m")
        if parsed_month.strftime("%Y-%m") != month:
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM format",
        )

    month_start = f"{month}-01"

    if parsed_month.month == 12:
        next_month_start = f"{parsed_month.year + 1:04d}-01-01"
    else:
        next_month_start = (
            f"{parsed_month.year:04d}-"
            f"{parsed_month.month + 1:02d}-01"
        )

    present_statuses = ["PRESENT", "WFH", "ON_DUTY"]

    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
            }
        },
        {"$limit": 1},
        {
            "$addFields": {
                "_joined_date": {
                    "$dateFromString": {
                        "dateString": "$joined_on",
                    }
                },
                "_month_start": {
                    "$dateFromString": {
                        "dateString": month_start,
                    }
                },
                "_next_month_start": {
                    "$dateFromString": {
                        "dateString": next_month_start,
                    }
                },
            }
        },
        {
            "$addFields": {
                "_effective_start": {
                    "$cond": [
                        {
                            "$gt": [
                                "$_joined_date",
                                "$_month_start",
                            ]
                        },
                        "$_joined_date",
                        "$_month_start",
                    ]
                }
            }
        },
        {
            "$addFields": {
                "_working_days": {
                    "$size": {
                        "$filter": {
                            "input": {
                                "$map": {
                                    "input": {
                                        "$range": [
                                            0,
                                            {
                                                "$max": [
                                                    0,
                                                    {
                                                        "$dateDiff": {
                                                            "startDate": "$_effective_start",
                                                            "endDate": "$_next_month_start",
                                                            "unit": "day",
                                                        }
                                                    },
                                                ]
                                            },
                                        ]
                                    },
                                    "as": "offset",
                                    "in": {
                                        "$dateAdd": {
                                            "startDate": "$_effective_start",
                                            "unit": "day",
                                            "amount": "$$offset",
                                        }
                                    },
                                }
                            },
                            "as": "calendar_day",
                            "cond": {
                                "$not": [
                                    {
                                        "$in": [
                                            {
                                                "$dayOfWeek": "$$calendar_day"
                                            },
                                            [1, 7],
                                        ]
                                    }
                                ]
                            },
                        }
                    }
                }
            }
        },
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {
                    "employee_code": "$emp_code",
                },
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {
                                        "$eq": [
                                            "$emp_code",
                                            "$$employee_code",
                                        ]
                                    },
                                    {
                                        "$gte": [
                                            "$date",
                                            month_start,
                                        ]
                                    },
                                    {
                                        "$lt": [
                                            "$date",
                                            next_month_start,
                                        ]
                                    },
                                ]
                            }
                        }
                    }
                ],
                "as": "_monthly_logs",
            }
        },
        {
            "$addFields": {
                "_weekday_present_logs": {
                    "$filter": {
                        "input": "$_monthly_logs",
                        "as": "log",
                        "cond": {
                            "$and": [
                                {
                                    "$in": [
                                        "$$log.status",
                                        present_statuses,
                                    ]
                                },
                                {
                                    "$not": [
                                        {
                                            "$in": [
                                                {
                                                    "$dayOfWeek": {
                                                        "$dateFromString": {
                                                            "dateString": "$$log.date",
                                                        }
                                                    }
                                                },
                                                [1, 7],
                                            ]
                                        }
                                    ]
                                },
                            ]
                        },
                    }
                }
            }
        },
        {
            "$addFields": {
                "_present_days": {
                    "$sum": {
                        "$map": {
                            "input": "$_weekday_present_logs",
                            "as": "log",
                            "in": {
                                "$cond": [
                                    {
                                        "$eq": [
                                            {
                                                "$ifNull": [
                                                    "$$log.half_day",
                                                    False,
                                                ]
                                            },
                                            True,
                                        ]
                                    },
                                    0.5,
                                    1,
                                ]
                            },
                        }
                    }
                },
                "_leave_days": {
                    "$size": {
                        "$filter": {
                            "input": "$_monthly_logs",
                            "as": "log",
                            "cond": {
                                "$eq": [
                                    "$$log.status",
                                    "LEAVE",
                                ]
                            },
                        }
                    }
                },
                "_late_count": {
                    "$size": {
                        "$filter": {
                            "input": "$_monthly_logs",
                            "as": "log",
                            "cond": {
                                "$gt": [
                                    {
                                        "$ifNull": [
                                            "$$log.late_minutes",
                                            0,
                                        ]
                                    },
                                    0,
                                ]
                            },
                        }
                    }
                },
                "_total_late_minutes": {
                    "$sum": {
                        "$map": {
                            "input": "$_monthly_logs",
                            "as": "log",
                            "in": {
                                "$ifNull": [
                                    "$$log.late_minutes",
                                    0,
                                ]
                            },
                        }
                    }
                },
                "_total_overtime_minutes": {
                    "$sum": {
                        "$map": {
                            "input": "$_monthly_logs",
                            "as": "log",
                            "in": {
                                "$ifNull": [
                                    "$$log.overtime_minutes",
                                    0,
                                ]
                            },
                        }
                    }
                },
            }
        },
        {
            "$addFields": {
                "_attendance_pct": {
                    "$cond": [
                        {"$gt": ["$_working_days", 0]},
                        {
                            "$divide": [
                                {
                                    "$floor": {
                                        "$add": [
                                            {
                                                "$multiply": [
                                                    {
                                                        "$divide": [
                                                            "$_present_days",
                                                            "$_working_days",
                                                        ]
                                                    },
                                                    1000000,
                                                ]
                                            },
                                            0.5,
                                        ]
                                    }
                                },
                                10000,
                            ]
                        },
                        None,
                    ]
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "emp_code": 1,
                "month": {"$literal": month},
                "working_days": "$_working_days",
                "present_days": "$_present_days",
                "leave_days": "$_leave_days",
                "late_count": "$_late_count",
                "total_late_minutes": "$_total_late_minutes",
                "total_overtime_minutes": "$_total_overtime_minutes",
                "attendance_pct": "$_attendance_pct",
            }
        },
    ]

    try:
        results = aggregate_results(db.employees, pipeline)
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Unable to calculate monthly analytics",
        )

    if not results:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    return results[0]


@app.get("/analytics/departments/summary")
def department_summary(
    month: str,
    department: Optional[str] = None,
):
    # Validate month format: YYYY-MM
    try:
        parsed_month = datetime.strptime(month, "%Y-%m")
        if parsed_month.strftime("%Y-%m") != month:
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM format",
        )

    month_start = parsed_month.strftime("%Y-%m-01")

    if parsed_month.month == 12:
        next_month = parsed_month.replace(
            year=parsed_month.year + 1,
            month=1,
        )
    else:
        next_month = parsed_month.replace(
            month=parsed_month.month + 1,
        )

    month_end = (next_month - timedelta(days=1)).strftime("%Y-%m-%d")

    # Start with employees who had joined by the end of the month.
    employee_filter = {
        "joined_on": {"$lte": month_end}
    }

    if department is not None:
        employee_filter["department"] = department

    pipeline = [
        {"$match": employee_filter},

        # Include each employee's attendance records for this month.
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"employee_code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "date": {
                                "$gte": month_start,
                                "$lte": month_end,
                            }
                        }
                    },
                    {
                        "$match": {
                            "$expr": {
                                "$eq": [
                                    "$emp_code",
                                    "$$employee_code",
                                ]
                            }
                        }
                    },
                    {
                        "$project": {
                            "_id": 0,
                            "emp_code": 1,
                            "date": 1,
                            "status": 1,
                            "half_day": 1,
                            "work_hours": 1,
                            "late_minutes": 1,
                        }
                    },
                ],
                "as": "logs",
            }
        },

        # Keep employees even if they have no attendance records.
        {
            "$unwind": {
                "path": "$logs",
                "preserveNullAndEmptyArrays": True,
            }
        },

        {
            "$addFields": {
                "_has_log": {
                    "$ne": [
                        {"$ifNull": ["$logs.emp_code", None]},
                        None,
                    ]
                },
                "_is_present": {
                    "$in": [
                        "$logs.status",
                        ["PRESENT", "WFH", "ON_DUTY"],
                    ]
                },
                "_has_hours": {
                    "$ne": [
                        {"$ifNull": ["$logs.work_hours", None]},
                        None,
                    ]
                },
                "_is_weekday": {
                    "$cond": [
                        {
                            "$ne": [
                                {"$ifNull": ["$logs.date", None]},
                                None,
                            ]
                        },
                        {
                            "$in": [
                                {
                                    "$dayOfWeek": {
                                        "$dateFromString": {
                                            "dateString": "$logs.date"
                                        }
                                    }
                                },
                                [2, 3, 4, 5, 6],
                            ]
                        },
                        False,
                    ]
                },
            }
        },

        # Group records by the employee's department.
        {
            "$group": {
                "_id": "$department",

                # Distinct employees ensure people without logs count.
                "employees": {"$addToSet": "$emp_code"},

                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$_has_log",
                                    "$_is_present",
                                    "$_is_weekday",
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$logs.half_day", True]},
                                    0.5,
                                    1,
                                ]
                            },
                            0,
                        ]
                    }
                },

                "hours_sum": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$_has_log",
                                    "$_is_present",
                                    "$_has_hours",
                                ]
                            },
                            "$logs.work_hours",
                            0,
                        ]
                    }
                },

                "hours_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$_has_log",
                                    "$_is_present",
                                    "$_has_hours",
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },

                "late_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$_has_log",
                                    {
                                        "$gt": [
                                            {"$ifNull": ["$logs.late_minutes", 0]},
                                            0,
                                        ]
                                    },
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },

                "total_late_minutes": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$_has_log",
                                    {
                                        "$gt": [
                                            {"$ifNull": ["$logs.late_minutes", 0]},
                                            0,
                                        ]
                                    },
                                ]
                            },
                            {"$ifNull": ["$logs.late_minutes", 0]},
                            0,
                        ]
                    }
                },

                "leave_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$_has_log",
                                    {"$eq": ["$logs.status", "LEAVE"]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },

                "on_duty_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$_has_log",
                                    {"$eq": ["$logs.status", "ON_DUTY"]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
            }
        },

        {
            "$addFields": {
                "headcount": {"$size": "$employees"},
                "avg_work_hours": {
                    "$cond": [
                        {"$gt": ["$hours_count", 0]},
                        {
                            "$divide": [
                                {
                                    "$floor": {
                                        "$add": [
                                            {
                                                "$multiply": [
                                                    {
                                                        "$divide": [
                                                            "$hours_sum",
                                                            "$hours_count",
                                                        ]
                                                    },
                                                    100,
                                                ]
                                            },
                                            0.5,
                                        ]
                                    }
                                },
                                100,
                            ]
                        },
                        None,
                    ]
                },
            }
        },

        {
            "$project": {
                "_id": 0,
                "department": "$_id",
                "headcount": 1,
                "present_days": 1,
                "avg_work_hours": 1,
                "late_count": 1,
                "total_late_minutes": 1,
                "leave_count": 1,
                "on_duty_count": 1,
            }
        },

        {"$sort": {"department": 1}},
    ]

    items = aggregate_results(db.employees, pipeline)

    return {
        "month": month,
        "items": items,
    }


@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str,
    limit: int = 10,
    department: Optional[str] = None,
):
    # Validate month format: YYYY-MM
    try:
        parsed_month = datetime.strptime(month, "%Y-%m")
        if parsed_month.strftime("%Y-%m") != month:
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM format",
        )

    # Validate leaderboard limit.
    if limit < 1 or limit > 50:
        raise HTTPException(
            status_code=422,
            detail="limit must be between 1 and 50",
        )

    month_start = f"{month}-01"

    # Calculate the final calendar day of the requested month.
    if parsed_month.month == 12:
        next_month = parsed_month.replace(
            year=parsed_month.year + 1,
            month=1,
        )
    else:
        next_month = parsed_month.replace(
            month=parsed_month.month + 1,
        )

    month_end = (next_month - timedelta(days=1)).strftime("%Y-%m-%d")

    # Aggregate attendance records in MongoDB.
    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": month_start,
                    "$lte": month_end,
                },
                "late_minutes": {"$gt": 0},
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {"$sum": 1},
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee",
            }
        },
        {"$unwind": "$employee"},
    ]

    # Apply department filtering before calculating ranks.
    if department is not None:
        pipeline.append(
            {"$match": {"employee.department": department}}
        )

    pipeline.extend([
        {
            "$project": {
                "_id": 0,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_count": 1,
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"total_late_minutes": -1},
                "output": {
                    "rank": {"$rank": {}}
                },
            }
        },
        # Apply the limit after ranking so tied employees are included.
        {"$match": {"rank": {"$lte": limit}}},
        {
            "$sort": {
                "total_late_minutes": -1,
                "emp_code": 1,
            }
        },
        {
            "$project": {
                "_id": 0,
                "rank": 1,
                "emp_code": 1,
                "name": 1,
                "department": 1,
                "total_late_minutes": 1,
                "late_count": 1,
            }
        },
    ])

    items = aggregate_results(db.attendance_logs, pipeline)

    return {
        "month": month,
        "items": items,
    }


@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
):
    # Validate the date format.
    try:
        start_day = datetime.strptime(from_date, "%Y-%m-%d")
        end_day = datetime.strptime(to_date, "%Y-%m-%d")

        if (
            start_day.strftime("%Y-%m-%d") != from_date
            or end_day.strftime("%Y-%m-%d") != to_date
        ):
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="from and to must use YYYY-MM-DD format",
        )

    if end_day < start_day:
        raise HTTPException(
            status_code=422,
            detail="to must not be earlier than from",
        )

    day_count = (end_day - start_day).days + 1

    if day_count > 92:
        raise HTTPException(
            status_code=422,
            detail="Date range must not exceed 92 days",
        )

    # Keep the required 404 for a department that has no employees.
    if db.employees.find_one(
        {"department": department},
        {"_id": 1},
    ) is None:
        raise HTTPException(
            status_code=404,
            detail="Department not found",
        )

    # Collect this department's employee codes once. The array-valued localField
    # joins only these employees' logs through the {emp_code, date} index.
    # Attendance is grouped by date before the inclusive date series is expanded.
    pipeline = [
        {"$match": {"department": department}},
        {
            "$group": {
                "_id": "$department",
                "employee_codes": {"$addToSet": "$emp_code"},
            }
        },
        {
            "$project": {
                "_id": 0,
                "department": "$_id",
                "employee_codes": 1,
                "dates": {
                    "$map": {
                        "input": {"$range": [0, day_count]},
                        "as": "offset",
                        "in": {
                            "$dateToString": {
                                "format": "%Y-%m-%d",
                                "date": {
                                    "$add": [
                                        {"$dateFromString": {"dateString": from_date}},
                                        {"$multiply": ["$$offset", 86400000]},
                                    ]
                                },
                            }
                        },
                    }
                },
            }
        },
        {
            "$lookup": {
                "from": "attendance_logs",
                "localField": "employee_codes",
                "foreignField": "emp_code",
                "pipeline": [
                    {"$match": {"date": {"$gte": from_date, "$lte": to_date}}},
                    {
                        "$group": {
                            "_id": "$date",
                            "present_count": {
                                "$sum": {
                                    "$cond": [
                                        {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                        {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]},
                                        0,
                                    ]
                                }
                            },
                            "late_count": {
                                "$sum": {
                                    "$cond": [
                                        {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]},
                                        1,
                                        0,
                                    ]
                                }
                            },
                        }
                    },
                ],
                "as": "attendance_by_date",
            }
        },
        {"$unwind": "$dates"},
        {
            "$project": {
                "_id": 0,
                "department": 1,
                "date": "$dates",
                "attendance_by_date": 1,
            }
        },
        # Headcount remains based on employment date, not attendance records.
        {
            "$lookup": {
                "from": "employees",
                "let": {"target_date": "$date", "target_department": "$department"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$department", "$$target_department"]},
                                    {"$lte": ["$joined_on", "$$target_date"]},
                                ]
                            }
                        }
                    },
                    {"$count": "count"},
                ],
                "as": "headcount_data",
            }
        },
        {
            "$addFields": {
                "headcount": {
                    "$ifNull": [{"$arrayElemAt": ["$headcount_data.count", 0]}, 0]
                },
                "present_count": {
                    "$let": {
                        "vars": {
                            "day_counts": {
                                "$arrayElemAt": [
                                    {
                                        "$filter": {
                                            "input": "$attendance_by_date",
                                            "as": "day_counts",
                                            "cond": {"$eq": ["$$day_counts._id", "$date"]},
                                        }
                                    },
                                    0,
                                ]
                            }
                        },
                        "in": {"$ifNull": ["$$day_counts.present_count", 0]},
                    }
                },
                "late_count": {
                    "$let": {
                        "vars": {
                            "day_counts": {
                                "$arrayElemAt": [
                                    {
                                        "$filter": {
                                            "input": "$attendance_by_date",
                                            "as": "day_counts",
                                            "cond": {"$eq": ["$$day_counts._id", "$date"]},
                                        }
                                    },
                                    0,
                                ]
                            }
                        },
                        "in": {"$ifNull": ["$$day_counts.late_count", 0]},
                    }
                },
                "is_working_day": {
                    "$in": [
                        {"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}},
                        [2, 3, 4, 5, 6],
                    ]
                },
            }
        },
        # Attendance rate is null on weekends or when headcount is zero.
        # floor(x + 0.5) implements four-decimal half-up rounding for nonnegative rates.
        {
            "$addFields": {
                "attendance_rate": {
                    "$cond": [
                        {"$and": ["$is_working_day", {"$gt": ["$headcount", 0]}]},
                        {
                            "$divide": [
                                {
                                    "$floor": {
                                        "$add": [
                                            {
                                                "$multiply": [
                                                    {"$divide": ["$present_count", "$headcount"]},
                                                    10000,
                                                ]
                                            },
                                            0.5,
                                        ]
                                    }
                                },
                                10000,
                            ]
                        },
                        None,
                    ]
                }
            }
        },
        # The window starts at the beginning of the requested range.
        {
            "$setWindowFields": {
                "sortBy": {"date": 1},
                "output": {"_avg7_raw": {"$avg": "$attendance_rate", "window": {"documents": [-6, 0]}}},
            }
        },
        {
            "$addFields": {
                "moving_avg_7d": {
                    "$cond": [
                        {"$eq": [{"$ifNull": ["$_avg7_raw", None]}, None]},
                        None,
                        {
                            "$divide": [
                                {"$floor": {"$add": [{"$multiply": ["$_avg7_raw", 10000]}, 0.5]}},
                                10000,
                            ]
                        },
                    ]
                }
            }
        },
        {"$sort": {"date": 1}},
        {
            "$project": {
                "_id": 0,
                "department": 1,
                "date": 1,
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": 1,
                "moving_avg_7d": 1,
            }
        },
    ]

    items = aggregate_results(db.employees, pipeline)

    return {
        "department": department,
        "items": items,
    }


def _valid_month(value: str) -> bool:
    try:
        parsed = datetime.strptime(value, "%Y-%m")
        return parsed.strftime("%Y-%m") == value
    except ValueError:
        return False


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: Literal[
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend",
    ],
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    limit: int = 10,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    page: int = 1,
    page_size: int = 20,
):
    # Validate pagination.
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(
            status_code=422,
            detail="Invalid page or page_size",
        )

    # attendance_list uses a find query, not an aggregation.
    if endpoint == "attendance_list":
        query = {}

        if emp_code is not None:
            query["emp_code"] = emp_code

        if status is not None:
            if status not in {
                "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
            }:
                raise HTTPException(
                    status_code=422,
                    detail="Invalid attendance status",
                )
            query["status"] = status

        if date_from is not None or date_to is not None:
            for field_name, value in (
                ("date_from", date_from),
                ("date_to", date_to),
            ):
                if value is not None:
                    try:
                        parsed = datetime.fromisoformat(value).date()
                        if parsed.isoformat() != value:
                            raise ValueError
                    except ValueError:
                        raise HTTPException(
                            status_code=422,
                            detail=f"{field_name} must use YYYY-MM-DD",
                        )

            if date_from and date_to and date_from > date_to:
                raise HTTPException(
                    status_code=422,
                    detail="date_from must not be after date_to",
                )

            query["date"] = {}
            if date_from is not None:
                query["date"]["$gte"] = date_from
            if date_to is not None:
                query["date"]["$lte"] = date_to

        cursor = (
            db.attendance_logs.find(query)
            .sort([("date", -1), ("emp_code", 1)])
            .skip((page - 1) * page_size)
            .limit(page_size)
        )

        try:
            raw_explain = raw_explain = db.command(
    "explain",
    {
        "find": "attendance_logs",
        "filter": query,
        "sort": {"date": -1, "emp_code": 1},
        "skip": (page - 1) * page_size,
        "limit": page_size,
    },
    verbosity="executionStats",
)
        except Exception:
            raise HTTPException(
                status_code=503,
                detail="Unable to explain attendance query",
            )

        return {
            "endpoint": endpoint,
            "collection": "attendance_logs",
            "explain": json.loads(json_util.dumps(raw_explain)),
        }

    # The analytics endpoints build their real aggregation pipelines
    # through aggregate_results(). Capture the pipeline while calling
    # the corresponding endpoint with the supplied parameters.
    if endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(
                status_code=422,
                detail="emp_code and month are required",
            )
        if not _valid_month(month):
            raise HTTPException(
                status_code=422,
                detail="month must use YYYY-MM format",
            )

    elif endpoint in ("department_summary", "late_leaderboard"):
        if not month:
            raise HTTPException(
                status_code=422,
                detail="month is required",
            )
        if not _valid_month(month):
            raise HTTPException(
                status_code=422,
                detail="month must use YYYY-MM format",
            )

        if endpoint == "late_leaderboard" and not 1 <= limit <= 50:
            raise HTTPException(
                status_code=422,
                detail="limit must be between 1 and 50",
            )

    elif endpoint == "department_trend":
        if not department or not from_date or not to_date:
            raise HTTPException(
                status_code=422,
                detail="department, from and to are required",
            )

    capture = {}
    token = _EXPLAIN_CAPTURE.set(capture)

    try:
        try:
            if endpoint == "employee_monthly":
                employee_monthly(emp_code, month)

            elif endpoint == "department_summary":
                department_summary(month, department)

            elif endpoint == "late_leaderboard":
                late_leaderboard(month, limit, department)

            elif endpoint == "department_trend":
                department_trend(department, from_date, to_date)

        except HTTPException:
            # A captured aggregation returns no result rows. The monthly
            # endpoint can consequently raise its normal "not found"
            # response after its pipeline has already been captured.
            if "pipeline" not in capture:
                raise

    finally:
        _EXPLAIN_CAPTURE.reset(token)

    if "collection" not in capture or "pipeline" not in capture:
        raise HTTPException(
            status_code=500,
            detail="Unable to capture the endpoint aggregation",
        )

    try:
        raw_explain = db.command(
            "explain",
            {
                "aggregate": capture["collection"],
                "pipeline": capture["pipeline"],
                "cursor": {},
            },
            verbosity="executionStats",
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Unable to explain MongoDB aggregation",
        )

    return {
        "endpoint": endpoint,
        "collection": capture["collection"],
        "explain": json.loads(json_util.dumps(raw_explain)),
    }
