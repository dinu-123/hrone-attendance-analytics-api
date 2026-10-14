import os

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

TEST_MONGO_URI = "mongodb://127.0.0.1:27017"
TEST_DB_NAME = f"attendance_test_pytest_{os.getpid()}"

if not TEST_DB_NAME.startswith("attendance_test_pytest_"):
    raise RuntimeError("Unsafe test database name")

os.environ["MONGO_URI"] = TEST_MONGO_URI
os.environ["MONGO_DB"] = TEST_DB_NAME

import app.main as main_module


@pytest.fixture(scope="session")
def test_database():
    mongo = MongoClient(
        TEST_MONGO_URI,
        serverSelectionTimeoutMS=3000,
    )

    try:
        mongo.admin.command("ping")
        mongo.drop_database(TEST_DB_NAME)
    except Exception as exc:
        mongo.close()
        pytest.fail(f"Test MongoDB setup failed: {exc}")

    try:
        yield mongo[TEST_DB_NAME]
    finally:
        try:
            mongo.drop_database(TEST_DB_NAME)
        finally:
            mongo.close()
            main_module.client.close()


@pytest.fixture
def api_client(test_database):
    test_database.employees.delete_many({})
    test_database.attendance_logs.delete_many({})

    with TestClient(main_module.app) as client:
        yield client
