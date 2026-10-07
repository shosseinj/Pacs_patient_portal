from portal.orthanc import OrthancArchive


def test_archive_does_not_inherit_system_proxy(app, monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:9999")
    monkeypatch.setenv("NO_PROXY", "")
    archive = OrthancArchive(app.state.settings)
    try:
        assert archive.client.trust_env is False
    finally:
        archive.close()
