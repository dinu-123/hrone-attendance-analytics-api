from datetime import datetime, timezone

import pytest


def epoch_ms(value: str) -> int:
    """Convert an ISO UTC timestamp into epoch milliseconds."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(parsed.timestamp()) * 1000


def employee_payload(
    emp_code="EMP9001",
    department="Engineering",
    shift_start="09:30",
    shift_end="18:30",
):
    return {
        "emp_code": emp_code,
        "name": "Test Employee",
        "email": f"{emp_code.lower()}@example.com",
        "department": department,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "joined_on": "2026-01-05",
    }


def create_employee(client, **kwargs):
    response = client.post(
        "/employees",
        json=employee_payload(**kwargs),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_employee_returns_contract_fields(api_client):
    response = api_client.post(
        "/employees",
        json=employee_payload(),
    )

    assert response.status_code == 201
    body = response.json()

    assert body["emp_code"] == "EMP9001"
    assert body["name"] == "Test Employee"
    assert body["department"] == "Engineering"
    assert body["shift_start"] == "09:30"
    assert body["shift_end"] == "18:30"
    assert isinstance(body["created_at"], int)
    assert "_id" not in body
    assert "id" not in body


def test_duplicate_employee_code_returns_conflict(api_client):
    create_employee(api_client)

    response = api_client.post(
        "/employees",
        json=employee_payload(),
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    "overrides",
    [
        {"emp_code": "BAD1"},
        {"email": "not-an-email"},
        {"joined_on": "2026-02-30"},
        {"shift_start": "25:00"},
        {"name": ""},
        {"shift_start": "09:30", "shift_end": "09:30"},
    ],
)
def test_invalid_employee_data_returns_422(api_client, overrides):
    payload = employee_payload()
    payload.update(overrides)

    response = api_client.post("/employees", json=payload)

    assert response.status_code == 422


def test_employee_list_filters_sorts_and_paginates(api_client):
    create_employee(api_client, emp_code="EMP9003")
    create_employee(
        api_client,
        emp_code="EMP9002",
        department="Finance",
    )
    create_employee(api_client, emp_code="EMP9001")

    response = api_client.get(
        "/employees",
        params={"department": "Engineering", "page": 1, "page_size": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 1
    assert [item["emp_code"] for item in body["items"]] == ["EMP9001"]


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page": -1},
        {"page_size": 0},
        {"page_size": 101},
    ],
)
def test_employee_list_rejects_invalid_pagination(api_client, params):
    response = api_client.get("/employees", params=params)
    assert response.status_code == 422


def test_punch_in_returns_computed_fields_and_no_database_id(api_client):
    create_employee(api_client)

    response = api_client.post(
        "/attendance/punch-in",
        json={
            "emp_code": "EMP9001",
            "punched_at": epoch_ms("2026-10-14T04:10:01Z"),
            "status": "WFH",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()

    assert body["emp_code"] == "EMP9001"
    assert body["date"] == "2026-10-14"
    assert body["status"] == "WFH"
    assert body["late_minutes"] == 10
    assert body["punch_in"] == epoch_ms("2026-10-14T04:10:01Z")
    assert body["punch_out"] is None
    assert body["work_hours"] is None
    assert body["overtime_minutes"] == 0
    assert body["half_day"] is False
    assert body["history"] == []
    assert "_id" not in body
    assert "id" not in body


def test_punch_in_for_unknown_employee_returns_404(api_client):
    response = api_client.post(
        "/attendance/punch-in",
        json={
            "emp_code": "EMP9999",
            "punched_at": epoch_ms("2026-10-14T04:00:00Z"),
        },
    )

    assert response.status_code == 404


def test_duplicate_punch_in_returns_conflict(api_client):
    create_employee(api_client)
    request_body = {
        "emp_code": "EMP9001",
        "punched_at": epoch_ms("2026-10-14T04:00:00Z"),
    }

    first = api_client.post("/attendance/punch-in", json=request_body)
    second = api_client.post("/attendance/punch-in", json=request_body)

    assert first.status_code == 201
    assert second.status_code == 409


@pytest.mark.parametrize(
    "timestamp",
    [
        1_700_000_000,       # Seconds, not milliseconds
        1_800_000_000_000.0, # Float, not strict integer
        "1800000000000",     # String, not integer
        5_000_000_000_000,   # Beyond allowed range
        None,                # Explicit null is not omission
    ],
)
def test_invalid_punch_in_timestamp_returns_422(api_client, timestamp):
    create_employee(api_client)

    response = api_client.post(
        "/attendance/punch-in",
        json={
            "emp_code": "EMP9001",
            "punched_at": timestamp,
        },
    )

    assert response.status_code == 422


def test_punch_out_computes_derived_values(api_client):
    create_employee(api_client)

    punch_in = api_client.post(
        "/attendance/punch-in",
        json={
            "emp_code": "EMP9001",
            "punched_at": epoch_ms("2026-10-14T04:00:00Z"),
        },
    )
    assert punch_in.status_code == 201, punch_in.text

    response = api_client.post(
        "/attendance/punch-out",
        json={
            "emp_code": "EMP9001",
            "punched_at": epoch_ms("2026-10-14T13:30:00Z"),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["punch_in"] == epoch_ms("2026-10-14T04:00:00Z")
    assert body["punch_out"] == epoch_ms("2026-10-14T13:30:00Z")
    assert body["work_hours"] == 9.5
    assert body["overtime_minutes"] == 30
    assert body["half_day"] is False
    assert body["history"] == []
    assert "_id" not in body
    assert "id" not in body


def test_invalid_punch_out_does_not_close_record(api_client):
    create_employee(api_client)

    punch_in = api_client.post(
        "/attendance/punch-in",
        json={
            "emp_code": "EMP9001",
            "punched_at": epoch_ms("2026-10-14T04:00:00Z"),
        },
    )
    assert punch_in.status_code == 201

    response = api_client.post(
        "/attendance/punch-out",
        json={
            "emp_code": "EMP9001",
            "punched_at": epoch_ms("2026-10-14T03:59:00Z"),
        },
    )
    assert response.status_code == 422

    listed = api_client.get(
        "/attendance",
        params={"emp_code": "EMP9001"},
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["punch_out"] is None


def test_punch_out_without_matching_punch_in_returns_404(api_client):
    create_employee(api_client)

    response = api_client.post(
        "/attendance/punch-out",
        json={
            "emp_code": "EMP9001",
            "punched_at": epoch_ms("2026-10-14T13:30:00Z"),
        },
    )

    assert response.status_code == 404


def test_overnight_punch_in_uses_shift_start_date(api_client):
    create_employee(
        api_client,
        shift_start="22:00",
        shift_end="06:00",
    )

    response = api_client.post(
        "/attendance/punch-in",
        json={
            "emp_code": "EMP9001",
            "punched_at": epoch_ms("2026-10-13T19:00:00Z"),
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["date"] == "2026-10-13"


@pytest.mark.parametrize("route", ["/attendance/punch-in", "/attendance/punch-out"])
@pytest.mark.parametrize("timestamp", [None, 1_700_000_000, 5_000_000_000_000])
def test_invalid_timestamp_precedes_unknown_employee_lookup(
    api_client, route, timestamp
):
    response = api_client.post(
        route,
        json={"emp_code": "EMP_UNKNOWN", "punched_at": timestamp},
    )
    assert response.status_code == 422, response.text
