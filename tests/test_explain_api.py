import pytest


@pytest.mark.parametrize(
    ("endpoint", "params"),
    [
        ("attendance_list", {"page": 1, "page_size": 10}),
        ("employee_monthly", {"emp_code": "EMP9001", "month": "2026-10"}),
        (
            "department_summary",
            {"month": "2026-10", "department": "Engineering"},
        ),
        (
            "late_leaderboard",
            {"month": "2026-10", "limit": 10, "department": "Engineering"},
        ),
        (
            "department_trend",
            {
                "department": "Engineering",
                "from": "2026-10-01",
                "to": "2026-10-07",
            },
        ),
    ],
)
def test_explain_endpoints_return_execution_details(
    api_client, endpoint, params
):
    if endpoint == "department_trend":
        seed = api_client.post(
            "/employees",
            json={
                "emp_code": "EMP9002",
                "name": "Explain Test",
                "email": "explain@example.com",
                "department": "Engineering",
                "shift_start": "09:30",
                "shift_end": "18:30",
                "joined_on": "2026-01-05",
            },
        )
        assert seed.status_code == 201, seed.text

    response = api_client.get(
        f"/admin/explain/{endpoint}",
        params=params,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["endpoint"] == endpoint
    assert data["collection"]
    assert isinstance(data["explain"], dict)


def test_explain_rejects_unknown_endpoint(api_client):
    response = api_client.get("/admin/explain/not_a_real_endpoint")
    assert response.status_code == 422, response.text
