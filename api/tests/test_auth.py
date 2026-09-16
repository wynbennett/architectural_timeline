import json

from app.llm import client as llm_client


def test_auth_source_precedence(monkeypatch, tmp_path):
    for v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "ANTHROPIC_IDENTITY_TOKEN", "ANTHROPIC_IDENTITY_TOKEN_FILE"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path))
    assert llm_client.auth_source() == "none"

    (tmp_path / "credentials").mkdir()
    (tmp_path / "credentials" / "default.json").write_text(json.dumps({"access_token": "x"}))
    assert llm_client.auth_source() == "oauth profile 'default' (ant auth login)"

    (tmp_path / "active_config").write_text("work\n")
    assert llm_client.auth_source() == "none"  # active profile named but has no files
    (tmp_path / "credentials" / "work.json").write_text("{}")
    assert llm_client.auth_source() == "oauth profile 'work' (ant auth login)"

    monkeypatch.setenv("ANTHROPIC_PROFILE", "default")
    assert "'default'" in llm_client.auth_source()

    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    assert llm_client.auth_source().startswith("bearer token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    assert llm_client.auth_source().startswith("api key")


def test_health_reports_auth(monkeypatch):
    from app import create_app

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    body = create_app().test_client().get("/api/health").get_json()
    assert body["auth"].startswith("api key")
