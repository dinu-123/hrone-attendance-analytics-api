from app import main as main_module


def test_health_endpoint(api_client):
    response = api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_all_required_routes_are_registered(api_client):
    paths = api_client.get("/openapi.json").json()["paths"]

    expected_methods = {
        "/health": {"get"},
        "/employees": {"get", "post"},
        "/attendance/punch-in": {"post"},
        "/attendance/punch-out": {"post"},
        "/attendance": {"get"},
        "/attendance/{emp_code}/{date}": {"patch"},
        "/analytics/employees/{emp_code}/monthly": {"get"},
        "/analytics/departments/summary": {"get"},
        "/analytics/leaderboard/late": {"get"},
        "/analytics/departments/{department}/trend": {"get"},
        "/admin/explain/{endpoint}": {"get"},
    }

    for path, methods in expected_methods.items():
        assert path in paths, f"Missing required path: {path}"
        for method in methods:
            assert method in paths[path], (
                f"Missing {method.upper()} method for {path}"
            )


def test_startup_creates_required_named_indexes(api_client, test_database):
    employee_indexes = {
        item["name"]: item
        for item in test_database.employees.list_indexes()
    }
    attendance_indexes = {
        item["name"]: item
        for item in test_database.attendance_logs.list_indexes()
    }

    assert "uq_employees_emp_code" in employee_indexes
    assert "ix_employees_department_emp_code" in employee_indexes
    assert "ix_employees_joined_department" in employee_indexes
    assert employee_indexes["uq_employees_emp_code"]["unique"] is True

    assert "uq_attendance_emp_date" in attendance_indexes
    assert "ix_attendance_date_emp" in attendance_indexes
    assert "ix_attendance_status_date_emp" in attendance_indexes
    assert "ix_attendance_emp_punch_in" in attendance_indexes
    assert attendance_indexes["uq_attendance_emp_date"]["unique"] is True


def test_index_creation_is_idempotent(api_client, test_database):
    main_module.create_database_indexes()
    main_module.create_database_indexes()

    employee_names = {
        item["name"] for item in test_database.employees.list_indexes()
    }
    attendance_names = {
        item["name"] for item in test_database.attendance_logs.list_indexes()
    }

    assert "uq_employees_emp_code" in employee_names
    assert "uq_attendance_emp_date" in attendance_names
