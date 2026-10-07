import socket
import subprocess
import sys
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parent.parent / "run.sh"


def listener(ignore_term=False):
    code = """
import signal
import socket
import sys
import time
if sys.argv[1] == 'ignore':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
sock = socket.socket()
sock.bind(('127.0.0.1', 0))
sock.listen()
print(sock.getsockname()[1], flush=True)
while True:
    time.sleep(1)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code, "ignore" if ignore_term else "normal"],
        stdout=subprocess.PIPE,
        text=True,
    )
    return process, int(process.stdout.readline())


@pytest.mark.parametrize("ignore_term", [False, True])
def test_port_cleanup_stops_selected_listener_and_preserves_other_ports(tmp_path, ignore_term):
    target, port = listener(ignore_term)
    unrelated, other_port = listener()
    try:
        result = subprocess.run(
            ["bash", "-c", 'source "$1"; free_ports "$2"', "launcher-test", str(LAUNCHER), str(port)],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        assert target.wait(timeout=1) < 0
        assert unrelated.poll() is None
        with socket.create_connection(("127.0.0.1", other_port), timeout=1):
            pass
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    finally:
        for process in [target, unrelated]:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
            process.stdout.close()
