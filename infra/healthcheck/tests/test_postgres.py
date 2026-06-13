from app import create_app


def test_postgres_health_returns_200_when_db_connects(mocker):
    mock_connect = mocker.patch("app.psycopg.connect")
    mock_cursor = mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = ("PostgreSQL 16.4 on aarch64",)

    client = create_app().test_client()
    response = client.get("/health/postgres")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    assert "PostgreSQL 16.4" in body["version"]


def test_postgres_health_returns_503_when_db_unreachable(mocker):
    mocker.patch(
        "app.psycopg.connect",
        side_effect=Exception("could not connect: Connection refused"),
    )

    client = create_app().test_client()
    response = client.get("/health/postgres")

    assert response.status_code == 503
    body = response.get_json()
    assert body["status"] == "error"
    assert "Connection refused" in body["error"]
