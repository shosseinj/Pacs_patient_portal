from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    secret: str
    database_url: str = "sqlite:///data/portal.sqlite3"
    upload_dir: Path = Path("data/uploads")
    orthanc_url: str = "http://127.0.0.1:8042"
    orthanc_user: str = "portal"
    orthanc_password: str = ""
    public_url: str = "http://127.0.0.1:8080"
    secure_cookies: bool = False
    max_files: int = 5000
    max_upload_bytes: int = 2_000_000_000
    max_instance_bytes: int = 128_000_000
    session_seconds: int = 8 * 3600
    login_limit: int = 8
    dev_login_username: str = ""
    dev_login_password: str = ""

    @classmethod
    def from_env(cls):
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        secret = os.environ.get("APP_SECRET", "")
        if len(secret) < 32:
            raise ValueError(
                "Run python scripts/configure.py first; APP_SECRET must have at least 32 characters."
            )
        return cls(
            secret=secret,
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            upload_dir=Path(os.getenv("UPLOAD_DIR", "data/uploads")),
            orthanc_url=os.getenv("ORTHANC_URL", cls.orthanc_url).rstrip("/"),
            orthanc_user=os.getenv("ORTHANC_USER", "portal"),
            orthanc_password=os.getenv("ORTHANC_PASSWORD", ""),
            public_url=os.getenv("PUBLIC_URL", cls.public_url).rstrip("/"),
            secure_cookies=os.getenv("SECURE_COOKIES", "false").lower() == "true",
            dev_login_username=os.getenv("DEV_LOGIN_USERNAME", ""),
            dev_login_password=os.getenv("DEV_LOGIN_PASSWORD", ""),
            max_files=int(os.getenv("MAX_UPLOAD_FILES", "5000")),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", "2000000000")),
            max_instance_bytes=int(os.getenv("MAX_INSTANCE_BYTES", "128000000")),
        )
