"""Generate local secrets once. Never includes an account or a default password."""

import argparse
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    url = args.url.rstrip("/")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
    ):
        parser.error("Use an origin only, such as https://pacs.example.com")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        parser.error("A public server requires an HTTPS URL.")
    path = ROOT / ".env"
    if path.exists():
        parser.error(".env already exists. Edit it manually; secrets will not be overwritten.")
    db_secret, archive_secret = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    lines = {
        "APP_SECRET": secrets.token_urlsafe(48),
        "POSTGRES_PASSWORD": db_secret,
        "DATABASE_URL": f"postgresql+psycopg://pacs:{db_secret}@db:5432/pacs_portal",
        "ORTHANC_URL": "http://orthanc:8042",
        "ORTHANC_USER": "portal",
        "ORTHANC_PASSWORD": archive_secret,
        "PUBLIC_URL": url,
        "PUBLIC_HOST": parsed.netloc,
        "SECURE_COOKIES": str(parsed.scheme == "https").lower(),
        "UPLOAD_DIR": "/data/uploads",
        "HTTP_BIND": "127.0.0.1",
        "HTTP_PORT": "8080",
        "MAX_UPLOAD_FILES": "5000",
        "MAX_UPLOAD_BYTES": "2000000000",
        "MAX_INSTANCE_BYTES": "128000000",
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write("\n".join(f"{key}={value}" for key, value in lines.items()) + "\n")
    print("Created .env. Keep this file private and include it in encrypted backups.")


if __name__ == "__main__":
    main()
