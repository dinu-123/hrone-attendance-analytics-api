"""Regression checks ensuring unfiltered list totals use an index hint."""

import app.main as main_module


def test_unfiltered_attendance_total_uses_date_index_hint(api_client, monkeypatch):
    collection_type = type(main_module.db.attendance_logs)
    original = collection_type.count_documents
    observed_calls = []

    def spy(collection, filter, *args, **kwargs):
        if collection.name == "attendance_logs":
            observed_calls.append((dict(filter), dict(kwargs)))
        return original(collection, filter, *args, **kwargs)

    monkeypatch.setattr(collection_type, "count_documents", spy)
    response = api_client.get("/attendance")

    assert response.status_code == 200, response.text
    assert any(
        query == {} and kwargs.get("hint") == "ix_attendance_date_emp"
        for query, kwargs in observed_calls
    )


def test_unfiltered_employee_total_uses_employee_index_hint(api_client, monkeypatch):
    collection_type = type(main_module.db.employees)
    original = collection_type.count_documents
    observed_calls = []

    def spy(collection, filter, *args, **kwargs):
        if collection.name == "employees":
            observed_calls.append((dict(filter), dict(kwargs)))
        return original(collection, filter, *args, **kwargs)

    monkeypatch.setattr(collection_type, "count_documents", spy)
    response = api_client.get("/employees")

    assert response.status_code == 200, response.text
    assert any(
        query == {} and kwargs.get("hint") == "uq_employees_emp_code"
        for query, kwargs in observed_calls
    )
