from datetime import datetime, timezone


def epoch_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(parsed.timestamp()) * 1000


def create_employee(client):
    response = client.post(
        "/employees",
        json={
            "emp_code": "EMP9001",
            "name": "Test Employee",
            "email": "emp9001@example.com",
            "department": "Engineering",
            "shift_start": "09:30",
            "shift_end": "18:30",
            "joined_on": "2026-01-05",
        },
    )
    assert response.status_code == 201, response.text


def punch_in(client, timestamp="2026-10-14T04:35:00Z"):
    response = client.post(
        "/attendance/punch-in",
        json={
            "emp_code": "EMP9001",
            "punched_at": epoch_ms(timestamp),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_regularization_recomputes_fields_and_appends_history(api_client):
    create_employee(api_client)
    punch_in(api_client)

    response = api_client.patch(
        "/attendance/EMP9001/2026-10-14",
        json={
            "punch_in": epoch_ms("2026-10-14T03:58:00Z"),
            "reason": "Correct biometric error",
            "regularized_by": "qa.admin",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["punch_in"] == epoch_ms("2026-10-14T03:58:00Z")
    assert body["late_minutes"] == 0
    assert body["work_hours"] is None
    assert body["overtime_minutes"] == 0
    assert body["half_day"] is False
    assert len(body["history"]) == 1

    entry = body["history"][0]
    assert entry["by"] == "qa.admin"
    assert entry["reason"] == "Correct biometric error"
    assert isinstance(entry["at"], int)
    assert entry["changes"]["punch_in"]["from"] == epoch_ms(
        "2026-10-14T04:35:00Z"
    )
    assert entry["changes"]["punch_in"]["to"] == epoch_ms(
        "2026-10-14T03:58:00Z"
    )
    assert entry["changes"]["late_minutes"] == {
        "from": 35,
        "to": 0,
    }
    assert "_id" not in body
    assert "id" not in body


def test_regularization_ignores_client_supplied_derived_fields(api_client):
    create_employee(api_client)
    punch_in(api_client)

    response = api_client.patch(
        "/attendance/EMP9001/2026-10-14",
        json={
            "punch_in": epoch_ms("2026-10-14T03:58:00Z"),
            "work_hours": 999,
            "late_minutes": 888,
            "overtime_minutes": 777,
            "half_day": True,
            "reason": "Correct biometric error",
            "regularized_by": "qa.admin",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["work_hours"] is None
    assert body["late_minutes"] == 0
    assert body["overtime_minutes"] == 0
    assert body["half_day"] is False


def test_noop_regularization_returns_422(api_client):
    create_employee(api_client)
    punch_in(api_client)

    response = api_client.patch(
        "/attendance/EMP9001/2026-10-14",
        json={
            "reason": "No actual changes",
            "regularized_by": "qa.admin",
        },
    )

    assert response.status_code == 422


def test_regularization_missing_record_returns_404(api_client):
    create_employee(api_client)

    response = api_client.patch(
        "/attendance/EMP9001/2026-10-14",
        json={
            "status": "LEAVE",
            "reason": "Approved leave",
            "regularized_by": "qa.admin",
        },
    )

    assert response.status_code == 404


def test_absent_status_cannot_include_punch_times(api_client):
    create_employee(api_client)
    punch_in(api_client)

    response = api_client.patch(
        "/attendance/EMP9001/2026-10-14",
        json={
            "status": "ABSENT",
            "punch_in": epoch_ms("2026-10-14T03:58:00Z"),
            "reason": "Correct attendance",
            "regularized_by": "qa.admin",
        },
    )

    assert response.status_code == 422


def test_regularization_can_convert_record_to_leave(api_client):
    create_employee(api_client)
    punch_in(api_client)

    response = api_client.patch(
        "/attendance/EMP9001/2026-10-14",
        json={
            "status": "LEAVE",
            "reason": "Approved annual leave",
            "regularized_by": "qa.admin",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "LEAVE"
    assert body["punch_in"] is None
    assert body["punch_out"] is None
    assert body["work_hours"] is None
    assert body["late_minutes"] == 0
    assert body["overtime_minutes"] == 0
    assert body["half_day"] is False
    assert len(body["history"]) == 1


def test_invalid_regularization_date_returns_422(api_client):
    create_employee(api_client)

    response = api_client.patch(
        "/attendance/EMP9001/not-a-date",
        json={
            "status": "LEAVE",
            "reason": "Approved annual leave",
            "regularized_by": "qa.admin",
        },
    )

    assert response.status_code == 422
