from datetime import datetime


def epoch_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(parsed.timestamp()) * 1000


def create_employee(client, emp_code, department="Engineering"):
    response = client.post(
        "/employees",
        json={
            "emp_code": emp_code,
            "name": f"Employee {emp_code}",
            "email": f"{emp_code.lower()}@example.com",
            "department": department,
            "shift_start": "09:30",
            "shift_end": "18:30",
            "joined_on": "2026-01-05",
        },
    )
    assert response.status_code == 201, response.text


def add_attendance(client, emp_code, timestamp, status="PRESENT"):
    response = client.post(
        "/attendance/punch-in",
        json={
            "emp_code": emp_code,
            "punched_at": epoch_ms(timestamp),
            "status": status,
        },
    )
    assert response.status_code == 201, response.text


def test_attendance_is_sorted_by_date_then_employee_code(api_client):
    create_employee(api_client, "EMP9003")
    create_employee(api_client, "EMP9002")
    create_employee(api_client, "EMP9001")

    add_attendance(api_client, "EMP9003", "2026-10-13T04:00:00Z")
    add_attendance(api_client, "EMP9002", "2026-10-14T04:00:00Z")
    add_attendance(api_client, "EMP9001", "2026-10-14T04:00:00Z")

    response = api_client.get("/attendance")

    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 3
    assert [
        (item["date"], item["emp_code"])
        for item in body["items"]
    ] == [
        ("2026-10-14", "EMP9001"),
        ("2026-10-14", "EMP9002"),
        ("2026-10-13", "EMP9003"),
    ]


def test_attendance_filters_are_inclusive_and_total_is_filtered(api_client):
    create_employee(api_client, "EMP9001")
    create_employee(api_client, "EMP9002")

    add_attendance(api_client, "EMP9001", "2026-10-14T04:00:00Z", "WFH")
    add_attendance(api_client, "EMP9002", "2026-10-13T04:00:00Z", "PRESENT")

    response = api_client.get(
        "/attendance",
        params={
            "date_from": "2026-10-14",
            "date_to": "2026-10-14",
            "status": "WFH",
            "page": 1,
            "page_size": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["emp_code"] == "EMP9001"
    assert body["items"][0]["status"] == "WFH"


def test_attendance_pagination_limits_items_but_preserves_total(api_client):
    create_employee(api_client, "EMP9001")
    create_employee(api_client, "EMP9002")

    add_attendance(api_client, "EMP9001", "2026-10-14T04:00:00Z")
    add_attendance(api_client, "EMP9002", "2026-10-14T04:00:00Z")

    response = api_client.get(
        "/attendance",
        params={"page": 2, "page_size": 1},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 2
    assert body["page"] == 2
    assert body["page_size"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["emp_code"] == "EMP9002"


def test_attendance_rejects_reversed_date_range(api_client):
    response = api_client.get(
        "/attendance",
        params={
            "date_from": "2026-10-15",
            "date_to": "2026-10-14",
        },
    )
    assert response.status_code == 422


def test_attendance_rejects_invalid_calendar_date(api_client):
    response = api_client.get(
        "/attendance",
        params={"date_from": "2026-02-30"},
    )
    assert response.status_code == 422


def test_attendance_rejects_unknown_status(api_client):
    response = api_client.get(
        "/attendance",
        params={"status": "UNKNOWN"},
    )
    assert response.status_code == 422


def test_attendance_rejects_invalid_pagination(api_client):
    for params in ({"page": 0}, {"page_size": 101}):
        response = api_client.get("/attendance", params=params)
        assert response.status_code == 422
