import re
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("template", ["nginx.conf.template", "nginx.tls.conf.template"])
@pytest.mark.parametrize("endpoint", ["/_auth", "/health"])
def test_internal_portal_requests_preserve_public_host(template, endpoint):
    text = (ROOT / "deploy" / template).read_text()
    block = re.search(r"location = " + re.escape(endpoint) + r"\s*\{([^}]+)\}", text).group(1)
    # Without this nginx sends portal:8000, which the app correctly rejects.
    assert "proxy_set_header Host $http_host;" in block
