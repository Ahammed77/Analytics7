"""Run the chatbot without Docker: a bundled Postgres (pgserver) loaded with the demo dataset, plus the app.

    python dev_server.py [--port 8000]

Uses the same db/*.sql files as docker-compose. The database lives in a temp folder and is rebuilt on each start.
The tests use start_reporting_db() too.
"""
import argparse
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg

HERE = Path(__file__).resolve().parent


def start_reporting_db(data_dir: Path):
    """Start pgserver in data_dir, load schema, seed and the read-only role. Returns (server, admin_url, reader_url)."""
    import pgserver

    server = pgserver.get_server(data_dir, cleanup_mode="stop")
    admin_url = server.get_uri()
    with psycopg.connect(admin_url, autocommit=True) as conn:
        for name in ("schema.sql", "seed.sql", "roles.sql"):
            conn.execute((HERE / "db" / name).read_text(encoding="utf-8"))
    parts = urlsplit(admin_url)
    reader_url = urlunsplit(parts._replace(netloc=f"a7_reader:a7_reader@{parts.hostname}:{parts.port}"))
    return server, admin_url, reader_url


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # A fresh folder each start: a killed run can leave files behind that block initdb.
    for old in Path(tempfile.gettempdir()).glob("a7chat-devdb*"):
        shutil.rmtree(old, ignore_errors=True)
    data_dir = Path(tempfile.mkdtemp(prefix="a7chat-devdb-"))
    server, _, reader_url = start_reporting_db(data_dir)
    os.environ["A7_DATABASE_URL"] = reader_url
    print(f"reporting DB ready; chat at http://127.0.0.1:{args.port}  (query model: {os.environ.get('A7_QUERY_MODEL', 'claude')})")
    try:
        uvicorn.run("a7chat.api:create_app", factory=True, host="127.0.0.1", port=args.port, app_dir=str(HERE))
    finally:
        server.cleanup()
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
