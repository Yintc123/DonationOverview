import os

import psycopg
import redis
from dotenv import load_dotenv
from flask import Flask, jsonify

load_dotenv()


def check_postgres() -> str:
    conn_str = (
        f"host={os.environ['POSTGRES_HOST']} "
        f"port={os.environ['POSTGRES_PORT']} "
        f"user={os.environ['POSTGRES_USER']} "
        f"password={os.environ['POSTGRES_PASSWORD']} "
        f"dbname={os.environ['POSTGRES_DB']} "
        "connect_timeout=3"
    )
    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            row = cur.fetchone()
            return row[0]


def check_redis() -> bool:
    client = redis.Redis(
        host=os.environ["REDIS_HOST"],
        port=int(os.environ["REDIS_PORT"]),
        password=os.environ["REDIS_PASSWORD"],
        socket_connect_timeout=3,
        socket_timeout=3,
    )
    return client.ping()


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/health/postgres")
    def health_postgres():
        try:
            version = check_postgres()
            return jsonify({"status": "ok", "version": version})
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 503

    @app.get("/health/redis")
    def health_redis():
        try:
            check_redis()
            return jsonify({"status": "ok", "ping": "PONG"})
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 503

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=8080)
