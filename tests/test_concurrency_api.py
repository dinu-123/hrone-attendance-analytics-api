from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from app.main import app
from fastapi.testclient import TestClient


def epoch_ms(value):
    return int(
        datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).timestamp()
    ) * 1000


def create_employee(client):
    response = client.post(
        "/employees",
        json={
            "emp_code": "EMP9001",
            "name": "Concurrent Test",
            "email": "concurrent@example.com",
            "department": "Engineering",
            "shift_start": "09:30",
            "shift_end": "18:30",
            "joined_on": "2026-01-05",
        },
    )
    assert response.status_code == 201, response.text


def concurrent_posts(client, path, payload, workers=8):
    def send_request(_):
        return client.post(path, json=payload).status_code

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(send_request, range(workers)))


def test_concurrent_duplicate_employee_creates(api_client):
    payload = {
        "emp_code": "EMP9001",
        "name": "Concurrent Test",
        "email": "concurrent@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-05",
    }

    statuses = concurrent_posts(api_client, "/employees", payload)

    assert statuses.count(201) == 1, statuses
    assert statuses.count(409) == 7, statuses


def test_concurrent_punch_ins_create_exactly_one_record(api_client):
    create_employee(api_client)

    payload = {
        "emp_code": "EMP9001",
        "punched_at": epoch_ms("2026-10-14T04:00:00Z"),
    }
    statuses = concurrent_posts(
        api_client, "/attendance/punch-in", payload
    )

    assert statuses.count(201) == 1, statuses
    assert statuses.count(409) == 7, statuses

    listed = api_client.get(
        "/attendance",
        params={"emp_code": "EMP9001"},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


def test_concurrent_punch_out_closes_record_once(api_client):
    create_employee(api_client)

    punch_in = api_client.post(
        "/attendance/punch-in",
        json={
            "emp_code": "EMP9001",
            "punched_at": epoch_ms("2026-10-14T04:00:00Z"),
        },
    )
    assert punch_in.status_code == 201, punch_in.text

    payload = {
        "emp_code": "EMP9001",
        "punched_at": epoch_ms("2026-10-14T13:30:00Z"),
    }
    statuses = concurrent_posts(
        api_client, "/attendance/punch-out", payload
    )

    assert statuses.count(200) == 1, statuses
    assert statuses.count(409) == 7, statuses


def test_concurrent_regularizations_preserve_successful_history(
    api_client,
):
    create_employee(api_client)

    punch_in = api_client.post(
        "/attendance/punch-in",
        json={
            "emp_code": "EMP9001",
            "punched_at": epoch_ms("2026-10-14T04:35:00Z"),
        },
    )
    assert punch_in.status_code == 201, punch_in.text

    changes = [
        {
            "punch_in": epoch_ms("2026-10-14T04:00:00Z"),
            "reason": "Correct first time",
            "regularized_by": "qa.first",
        },
        {
            "punch_in": epoch_ms("2026-10-14T04:05:00Z"),
            "reason": "Correct second time",
            "regularized_by": "qa.second",
        },
    ]

    def send_patch(payload):
        with TestClient(app) as client:
            return client.patch(
                "/attendance/EMP9001/2026-10-14",
                json=payload,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send_patch, changes))

    statuses = [response.status_code for response in responses]
    assert all(status in (200, 409) for status in statuses), statuses
    assert statuses.count(200) >= 1, statuses

    final_record = api_client.get(
        "/attendance",
        params={"emp_code": "EMP9001"},
    )
    assert final_record.status_code == 200

    history = final_record.json()["items"][0]["history"]
    assert len(history) == statuses.count(200)
