import pytest


@pytest.fixture(autouse=True)
def fake_env(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "test-host")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_USER", "test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    monkeypatch.setenv("POSTGRES_DB", "test")
    monkeypatch.setenv("REDIS_HOST", "test-host")
    monkeypatch.setenv("REDIS_PORT", "6379")
    monkeypatch.setenv("REDIS_PASSWORD", "test")
