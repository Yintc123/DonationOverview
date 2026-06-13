from app import create_app


def test_redis_health_returns_200_when_redis_responds(mocker):
    mock_redis_class = mocker.patch("app.redis.Redis")
    mock_redis_class.return_value.ping.return_value = True

    client = create_app().test_client()
    response = client.get("/health/redis")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "ping": "PONG"}


def test_redis_health_returns_503_when_redis_unreachable(mocker):
    import redis

    mock_redis_class = mocker.patch("app.redis.Redis")
    mock_redis_class.return_value.ping.side_effect = redis.ConnectionError(
        "Error connecting to test-host:6379"
    )

    client = create_app().test_client()
    response = client.get("/health/redis")

    assert response.status_code == 503
    body = response.get_json()
    assert body["status"] == "error"
    assert "Error connecting" in body["error"]
