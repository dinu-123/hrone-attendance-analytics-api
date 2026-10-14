from datetime import datetime, timezone

import pytest


UTC = timezone.utc


def employee_doc(
    emp_code,
    department="Engineering",
    joined_on="2026-10-01",
):
    return {
        "emp_code": emp_code,
        "name": f"Employee {emp_code}",
        "email": f"{emp_code.lower()}@example.com",
        "department": department,
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": joined_on,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }


def attendance_doc(
    emp_code,
    date,
    status="PRESENT",
    late_minutes=0,
    overtime_minutes=0,
    work_hours=None,
    half_day=False,
):
    return {
        "emp_code": emp_code,
        "date": date,
        "status": status,
        "punch_in": None,
        "punch_out": None,
        "work_hours": work_hours,
        "late_minutes": late_minutes,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day,
        "history": [],
    }


def seed_employee(db, **kwargs):
    db.employees.insert_one(employee_doc(**kwargs))


def seed_log(db, **kwargs):
    db.attendance_logs.insert_one(attendance_doc(**kwargs))


def test_monthly_analytics_counts_weekdays_half_days_and_weekends(
    api_client, test_database
):
    db = test_database
    seed_employee(
        db,
        emp_code="EMP9001",
        department="Engineering",
        joined_on="2026-10-05",
    )

    seed_log(
        db,
        emp_code="EMP9001",
        date="2026-10-05",
        status="PRESENT",
        late_minutes=15,
        overtime_minutes=40,
        work_hours=4.25,
        half_day=True,
    )
    seed_log(
        db,
        emp_code="EMP9001",
        date="2026-10-06",
        status="WFH",
        work_hours=8.0,
    )
    seed_log(
        db,
        emp_code="EMP9001",
        date="2026-10-07",
        status="LEAVE",
    )
    seed_log(
        db,
        emp_code="EMP9001",
        date="2026-10-10",
        status="ON_DUTY",
        late_minutes=20,
        overtime_minutes=10,
        work_hours=2.0,
    )

    response = api_client.get(
        "/analytics/employees/EMP9001/monthly",
        params={"month": "2026-10"},
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["emp_code"] == "EMP9001"
    assert body["month"] == "2026-10"
    assert body["working_days"] == 20
    assert body["present_days"] == 1.5
    assert body["leave_days"] == 1
    assert body["late_count"] == 2
    assert body["total_late_minutes"] == 35
    assert body["total_overtime_minutes"] == 50
    assert body["attendance_pct"] == 7.5


def test_monthly_analytics_returns_null_rate_when_no_working_days(
    api_client, test_database
):
    seed_employee(
        test_database,
        emp_code="EMP9001",
        joined_on="2026-11-01",
    )

    response = api_client.get(
        "/analytics/employees/EMP9001/monthly",
        params={"month": "2026-10"},
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["working_days"] == 0
    assert body["present_days"] == 0
    assert body["attendance_pct"] is None


def test_monthly_analytics_unknown_employee_returns_404(api_client):
    response = api_client.get(
        "/analytics/employees/EMP9999/monthly",
        params={"month": "2026-10"},
    )
    assert response.status_code == 404


@pytest.mark.parametrize("month", ["2026-13", "2026-00", "2026-2", "bad"])
def test_monthly_analytics_rejects_invalid_month(api_client, month):
    response = api_client.get(
        "/analytics/employees/EMP9001/monthly",
        params={"month": month},
    )
    assert response.status_code == 422


def test_department_summary_includes_zero_log_headcount(api_client, test_database):
    db = test_database

    seed_employee(
        db,
        emp_code="EMP9001",
        department="Engineering",
        joined_on="2026-10-05",
    )
    seed_employee(
        db,
        emp_code="EMP9002",
        department="Engineering",
        joined_on="2026-10-20",
    )
    seed_employee(
        db,
        emp_code="EMP9003",
        department="Finance",
        joined_on="2026-11-01",
    )

    seed_log(
        db,
        emp_code="EMP9001",
        date="2026-10-05",
        status="PRESENT",
        late_minutes=15,
        work_hours=4.25,
        half_day=True,
    )
    seed_log(
        db,
        emp_code="EMP9001",
        date="2026-10-06",
        status="WFH",
        work_hours=8.0,
    )
    seed_log(
        db,
        emp_code="EMP9001",
        date="2026-10-07",
        status="LEAVE",
    )
    seed_log(
        db,
        emp_code="EMP9001",
        date="2026-10-10",
        status="ON_DUTY",
        late_minutes=20,
        work_hours=2.0,
    )

    response = api_client.get(
        "/analytics/departments/summary",
        params={"month": "2026-10"},
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["month"] == "2026-10"
    items = body["items"]
    assert [item["department"] for item in items] == ["Engineering"]

    engineering = items[0]
    assert engineering["headcount"] == 2
    assert engineering["present_days"] == 1.5
    assert engineering["avg_work_hours"] == 4.75
    assert engineering["late_count"] == 2
    assert engineering["total_late_minutes"] == 35
    assert engineering["leave_count"] == 1
    assert engineering["on_duty_count"] == 1


def test_department_summary_supports_exact_department_filter(
    api_client, test_database
):
    seed_employee(
        test_database,
        emp_code="EMP9001",
        department="Engineering",
    )
    seed_employee(
        test_database,
        emp_code="EMP9002",
        department="Finance",
    )

    response = api_client.get(
        "/analytics/departments/summary",
        params={"month": "2026-10", "department": "Finance"},
    )

    assert response.status_code == 200, response.text
    assert [
        item["department"] for item in response.json()["items"]
    ] == ["Finance"]


def test_late_leaderboard_uses_competition_rank_and_includes_ties(
    api_client, test_database
):
    db = test_database
    seed_employee(db, emp_code="EMP9001", department="Engineering")
    seed_employee(db, emp_code="EMP9002", department="Engineering")
    seed_employee(db, emp_code="EMP9003", department="Finance")

    # EMP9001 and EMP9002 tie on total late minutes, at rank 1.
    seed_log(db, emp_code="EMP9001", date="2026-10-05",
             late_minutes=20)
    seed_log(db, emp_code="EMP9001", date="2026-10-06",
             late_minutes=20)
    seed_log(db, emp_code="EMP9002", date="2026-10-05",
             late_minutes=40)
    seed_log(db, emp_code="EMP9003", date="2026-10-05",
             late_minutes=15)

    response = api_client.get(
        "/analytics/leaderboard/late",
        params={"month": "2026-10", "limit": 1},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["month"] == "2026-10"

    items = body["items"]
    assert [item["emp_code"] for item in items] == [
        "EMP9001",
        "EMP9002",
    ]
    assert [item["rank"] for item in items] == [1, 1]
    assert [item["total_late_minutes"] for item in items] == [40, 40]
    assert [item["late_count"] for item in items] == [2, 1]


def test_late_leaderboard_filters_department_before_ranking(
    api_client, test_database
):
    db = test_database
    seed_employee(db, emp_code="EMP9001", department="Engineering")
    seed_employee(db, emp_code="EMP9002", department="Finance")

    seed_log(db, emp_code="EMP9001", date="2026-10-05",
             late_minutes=40)
    seed_log(db, emp_code="EMP9002", date="2026-10-05",
             late_minutes=15)

    response = api_client.get(
        "/analytics/leaderboard/late",
        params={
            "month": "2026-10",
            "department": "Finance",
        },
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["emp_code"] == "EMP9002"
    assert items[0]["rank"] == 1


@pytest.mark.parametrize("limit", [0, 51])
def test_late_leaderboard_rejects_out_of_range_limit(api_client, limit):
    response = api_client.get(
        "/analytics/leaderboard/late",
        params={"month": "2026-10", "limit": limit},
    )
    assert response.status_code == 422


def test_department_trend_fills_days_and_updates_mid_month_headcount(
    api_client, test_database
):
    db = test_database
    seed_employee(
        db,
        emp_code="EMP9001",
        department="Engineering",
        joined_on="2026-10-05",
    )
    seed_employee(
        db,
        emp_code="EMP9002",
        department="Engineering",
        joined_on="2026-10-06",
    )

    seed_log(
        db,
        emp_code="EMP9001",
        date="2026-10-05",
        status="PRESENT",
        late_minutes=5,
        half_day=True,
    )
    seed_log(
        db,
        emp_code="EMP9001",
        date="2026-10-06",
        status="WFH",
    )

    response = api_client.get(
        "/analytics/departments/Engineering/trend",
        params={"from": "2026-10-05", "to": "2026-10-08"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["department"] == "Engineering"

    items = body["items"]
    assert [item["date"] for item in items] == [
        "2026-10-05",
        "2026-10-06",
        "2026-10-07",
        "2026-10-08",
    ]

    assert [item["headcount"] for item in items] == [1, 2, 2, 2]
    assert [item["present_count"] for item in items] == [0.5, 1, 0, 0]
    assert [item["late_count"] for item in items] == [1, 0, 0, 0]
    assert [item["attendance_rate"] for item in items] == [
        0.5, 0.5, 0.0, 0.0
    ]
    assert [item["moving_avg_7d"] for item in items] == [
        0.5, 0.5, 0.3333, 0.25
    ]
    assert all(item["is_working_day"] for item in items)


def test_department_trend_weekends_have_null_rates_in_weekend_only_range(
    api_client, test_database
):
    seed_employee(
        test_database,
        emp_code="EMP9001",
        department="Engineering",
        joined_on="2026-10-01",
    )
    seed_log(
        test_database,
        emp_code="EMP9001",
        date="2026-10-10",
        status="WFH",
        late_minutes=5,
    )

    response = api_client.get(
        "/analytics/departments/Engineering/trend",
        params={"from": "2026-10-10", "to": "2026-10-11"},
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]

    assert len(items) == 2
    assert [item["is_working_day"] for item in items] == [False, False]
    assert [item["attendance_rate"] for item in items] == [None, None]
    assert [item["moving_avg_7d"] for item in items] == [None, None]
    assert items[0]["present_count"] == 1
    assert items[0]["late_count"] == 1


def test_department_trend_rejects_invalid_ranges(api_client, test_database):
    seed_employee(
        test_database,
        emp_code="EMP9001",
        department="Engineering",
    )

    reversed_range = api_client.get(
        "/analytics/departments/Engineering/trend",
        params={"from": "2026-10-10", "to": "2026-10-01"},
    )
    assert reversed_range.status_code == 422

    too_long = api_client.get(
        "/analytics/departments/Engineering/trend",
        params={"from": "2026-01-01", "to": "2026-04-03"},
    )
    assert too_long.status_code == 422

    bad_date = api_client.get(
        "/analytics/departments/Engineering/trend",
        params={"from": "2026-02-30", "to": "2026-03-01"},
    )
    assert bad_date.status_code == 422


def test_department_trend_unknown_department_returns_404(api_client):
    response = api_client.get(
        "/analytics/departments/Unknown/trend",
        params={"from": "2026-10-05", "to": "2026-10-06"},
    )
    assert response.status_code == 404
