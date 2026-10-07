"""Prepare and run the local development stack; invoked by run.sh."""

import argparse
import json
import os
import platform
import secrets
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal import auth
from portal.config import Settings
from portal.db import make_engine
from portal.models import User

PROJECT = Path(__file__).resolve().parent.parent
NATIVE_PACKAGES = [
    "orthanc", "orthanc-dicomweb", "nginx", "dcmtk-data", "liblua5.3-0", "libjsoncpp26",
    "libdcmtk19", "libcivetweb1", "libpugixml1v5", "libminizip1t64", "libboost-filesystem1.90.0",
    "libwrap0", "libxml2-16", "libtiff6",
]


def local_settings(project):
    path = project / ".env"
    if not path.exists():
        values = {
            "APP_SECRET": secrets.token_urlsafe(48),
            "DATABASE_URL": f"sqlite:///{project}/data/portal.sqlite3",
            "UPLOAD_DIR": str(project / "data/uploads"),
            "ORTHANC_URL": "http://127.0.0.1:8042",
            "ORTHANC_USER": "portal",
            "ORTHANC_PASSWORD": secrets.token_urlsafe(32),
            "PUBLIC_URL": "http://127.0.0.1:8080",
            "PUBLIC_HOST": "127.0.0.1:8080",
            "SECURE_COOKIES": "false",
            "DEV_LOGIN_USERNAME": "admin",
            "DEV_LOGIN_PASSWORD": "Asd@12345",
        }
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as out:
            out.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
        print("Created local development .env.", flush=True)
    return Settings.from_env()


class LocalRunner:
    def __init__(self, project, settings):
        self.project = project
        self.settings = settings
        self.runtime = project / "data/runtime"
        self.root = self.runtime / "root"
        self.state = self.runtime / "services.json"
        self.services = {}
        self.processes = {}
        self.env = dict(os.environ)
        self.native_env = dict(
            self.env,
            LD_LIBRARY_PATH=str(self.root / "usr/lib/x86_64-linux-gnu"),
            DCMDICTPATH=str(self.root / "usr/share/dcmtk/dicom.dic"),
        )

    def validate_settings(self):
        origin = urlsplit(self.settings.public_url)
        if (
            origin.scheme != "http"
            or origin.hostname not in {"127.0.0.1", "localhost"}
            or origin.port != 8080
            or origin.path
            or origin.query
            or origin.fragment
            or origin.username
            or self.settings.secure_cookies
            or not self.settings.database_url.startswith("sqlite:///")
            or self.settings.orthanc_url != "http://127.0.0.1:8042"
        ):
            raise ValueError(
                "Local startup requires HTTP on localhost:8080, SQLite, and Orthanc on 127.0.0.1:8042. "
                "Existing deployment settings were preserved; use scripts/start.sh for Docker."
            )

    def native_ready(self):
        for relative in ["usr/sbin/Orthanc", "usr/sbin/nginx", "usr/share/orthanc/plugins/libOrthancDicomWeb.so"]:
            path = self.root / relative
            if not path.exists():
                return False
            result = subprocess.run(["ldd", str(path)], env=self.native_env, text=True, capture_output=True)
            if result.returncode or "not found" in result.stdout:
                return False
        return (self.root / "usr/share/dcmtk/dicom.dic").exists()

    def prepare(self):
        self.validate_settings()
        if platform.machine() != "x86_64":
            raise ValueError("This local launcher supports Linux x86_64.")
        self.runtime.mkdir(parents=True, exist_ok=True)
        if not self.native_ready():
            for tool in ["apt", "dpkg-deb", "ldd"]:
                if not shutil.which(tool):
                    raise RuntimeError(f"Install {tool} or use the Docker startup instructions.")
            packages = self.runtime / "debs"
            packages.mkdir(exist_ok=True)
            print("Downloading native Orthanc and Nginx packages for Ubuntu 26.04...", flush=True)
            subprocess.run(["apt", "download", *NATIVE_PACKAGES], cwd=packages, check=True)
            for package in packages.glob("*.deb"):
                subprocess.run(["dpkg-deb", "-x", str(package), str(self.root)], check=True)
            if not self.native_ready():
                raise RuntimeError("Native libraries are missing; check the downloaded Ubuntu packages.")
        assets = self.runtime / "ohif"
        ready = assets / ".ready"
        if not (
            ready.exists()
            and ready.read_text().strip()
            == "sha256:dee5c696c712082fdd4321b6f5ad94846dc97df5d970548ca0e1d5289667b047"
            and (assets / "index.html").is_file()
            and (assets / "app.bundle.css.gz").is_file()
            and any(assets.glob("app.bundle.*.js.gz"))
        ):
            subprocess.run([sys.executable, "-m", "scripts.fetch_ohif"], cwd=self.project, check=True)
        self.write_configs()
        subprocess.run(self.nginx_command() + ["-t"], check=True)
        # A fresh local database gets the development login; existing accounts are preserved.
        engine = make_engine(self.settings.database_url)
        try:
            with Session(engine) as db:
                if (
                    db.scalar(select(User).limit(1)) is None
                    and self.settings.dev_login_username
                    and self.settings.dev_login_password
                ):
                    user = User(
                        username=auth.valid_username(self.settings.dev_login_username),
                        display_name="مدیر مرکز",
                        role="admin",
                        password_hash=auth.hasher.hash(self.settings.dev_login_password),
                    )
                    db.add(user)
                    db.flush()
                    auth.audit(db, None, "account_create-admin", user.id)
                    db.commit()
                    credentials = self.project / "data/local-admin.txt"
                    fd = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "w") as out:
                        out.write(
                            f"URL: {self.settings.public_url}/portal\n"
                            f"Username: {self.settings.dev_login_username}\n"
                            f"Password: {self.settings.dev_login_password}\n"
                        )
        finally:
            engine.dispose()

    def write_configs(self):
        for folder in ["orthanc", "ohif", "nginx"]:
            (self.runtime / folder).mkdir(exist_ok=True)
        config = {
            "Name": "Local development PACS",
            "StorageDirectory": str(self.runtime / "orthanc/storage"),
            "IndexDirectory": str(self.runtime / "orthanc/index"),
            "Plugins": [str(self.root / "usr/share/orthanc/plugins/libOrthancDicomWeb.so")],
            "HttpServerEnabled": True, "HttpPort": 8042, "HttpBindAddresses": ["127.0.0.1"],
            "RemoteAccessAllowed": False, "AuthenticationEnabled": True,
            "RegisteredUsers": {self.settings.orthanc_user: self.settings.orthanc_password},
            "DicomServerEnabled": False, "OverwriteInstances": False,
            "RestApiWriteToFileSystemEnabled": False,
            "DicomWeb": {"Enable": True, "Root": "/dicom-web/", "EnableWado": False},
            "DicomDictionary": [str(self.root / "usr/share/dcmtk/dicom.dic")],
        }
        fd = os.open(self.runtime / "orthanc/config.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as out:
            json.dump(config, out, indent=2)
        shutil.copyfile(self.project / "deploy/ohif-config.js", self.runtime / "ohif/app-config.js")
        gateway = (self.project / "deploy/nginx.conf.template").read_text()
        gateway = gateway.replace("listen 8080;", "listen 127.0.0.1:8080;")
        gateway = gateway.replace("http://portal:8000", "http://127.0.0.1:8000")
        gateway = gateway.replace("http://ohif:8080", "http://127.0.0.1:8081")
        viewer = (self.project / "deploy/ohif-nginx.conf").read_text()
        viewer = viewer.replace("listen 8080;", "listen 127.0.0.1:8081;")
        viewer = viewer.replace("/usr/share/nginx/html", str(self.runtime / "ohif"))
        header = """worker_processes 1;
pid nginx.pid;
error_log error.log;
events { worker_connections 1024; }
http {
    access_log access.log;
    client_body_temp_path temp/body;
    proxy_temp_path temp/proxy;
    fastcgi_temp_path temp/fastcgi;
    uwsgi_temp_path temp/uwsgi;
    scgi_temp_path temp/scgi;
    default_type application/octet-stream;
    types {
        text/html html; text/css css; application/javascript js mjs;
        application/json json map; application/wasm wasm;
        image/svg+xml svg; image/png png; image/jpeg jpg jpeg; image/x-icon ico;
        font/woff woff; font/woff2 woff2; font/ttf ttf;
    }
"""
        (self.runtime / "nginx/nginx.conf").write_text(header + gateway + "\n" + viewer + "\n}\n")
        for folder in ["body", "proxy", "fastcgi", "uwsgi", "scgi"]:
            (self.runtime / "nginx/temp" / folder).mkdir(parents=True, exist_ok=True)

    def nginx_command(self):
        return [
            str(self.root / "usr/sbin/nginx"), "-p", str(self.runtime / "nginx") + "/",
            "-c", "nginx.conf",
        ]

    def owned(self, service):
        pid = service["pid"]
        try:
            return (
                service["marker"].encode() in Path(f"/proc/{pid}/cmdline").read_bytes()
                and Path(f"/proc/{pid}/cwd").resolve() == self.project
            )
        except (FileNotFoundError, PermissionError):
            return False

    def stop_one(self, service):
        if not self.owned(service):
            return
        try:
            os.kill(service["pid"], signal.SIGTERM)
            for _ in range(25):
                if not self.owned(service):
                    return
                time.sleep(0.2)
            if self.owned(service):
                os.kill(service["pid"], signal.SIGKILL)
        except ProcessLookupError:
            pass

    def stop(self):
        if self.state.exists():
            services = json.loads(self.state.read_text())
            for name in ["gateway", "worker", "portal", "orthanc"]:
                if name in services:
                    self.stop_one(services[name])
        old_pid = self.project / "data/portal.pid"
        if old_pid.exists():
            self.stop_one({"pid": int(old_pid.read_text()), "marker": "portal.app:create_from_env"})

    def launch(self, name, command, marker, env=None):
        with (self.runtime / (name + ".log")).open("ab") as log:
            process = subprocess.Popen(
                command, cwd=self.project, env=self.env if env is None else env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True,
            )
        self.processes[name] = process
        self.services[name] = {"pid": process.pid, "marker": marker}
        self.state.write_text(json.dumps(self.services, indent=2) + "\n")
        print(f"Started {name} (PID {process.pid})", flush=True)

    def wait_for(self, url, name, auth_pair=None):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.processes[name].poll() is not None:
                break
            try:
                if httpx.get(url, auth=auth_pair, timeout=1, trust_env=False).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise RuntimeError(f"{name} failed to start; read {self.runtime / (name + '.log')}")

    def start(self):
        self.prepare()
        self.stop()
        try:
            self.launch(
                "orthanc", [str(self.root / "usr/sbin/Orthanc"), str(self.runtime / "orthanc/config.json")],
                "orthanc/config.json", self.native_env,
            )
            self.wait_for(
                "http://127.0.0.1:8042/system", "orthanc",
                (self.settings.orthanc_user, self.settings.orthanc_password),
            )
            self.launch(
                "portal", [sys.executable, "-m", "uvicorn", "portal.app:create_from_env", "--factory",
                           "--host", "127.0.0.1", "--port", "8000", "--no-proxy-headers"],
                "portal.app:create_from_env",
            )
            self.wait_for("http://127.0.0.1:8000/health", "portal")
            (self.project / "data/portal.pid").write_text(str(self.services["portal"]["pid"]) + "\n")
            self.launch("worker", [sys.executable, "-m", "portal.worker"], "portal.worker")
            self.launch("gateway", self.nginx_command() + ["-g", "daemon off;"], "nginx.conf")
            self.wait_for("http://127.0.0.1:8080/health", "gateway")
            self.wait_for("http://127.0.0.1:8081/", "gateway")
            if self.processes["worker"].poll() is not None:
                raise RuntimeError(f"Worker exited; read {self.runtime / 'worker.log'}")
            print(f"\nPortal ready: {self.settings.public_url}/portal", flush=True)
            print(f"Logs: {self.runtime}", flush=True)
        except BaseException:
            for service in reversed(list(self.services.values())):
                self.stop_one(service)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    runner = LocalRunner(PROJECT, local_settings(PROJECT))
    if args.prepare:
        runner.prepare()
    elif args.stop:
        runner.stop()
    else:
        runner.start()


if __name__ == "__main__":
    main()
