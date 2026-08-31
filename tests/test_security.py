from app.config import Settings, get_settings
from app.production_main import app


def _hosted_settings() -> Settings:
    return Settings(
        deployment_mode="hosted",
        docflow_api_key="k" * 32,
        database_url="postgresql+asyncpg://docflow_app@db/docflow_ai",
        cors_allow_origins="https://documents.example.test",
        trusted_hosts="documents.example.test,testserver",
    )


def test_hosted_mode_requires_correct_key(client):
    app.dependency_overrides[get_settings] = _hosted_settings
    try:
        missing = client.get("/documents/metrics/summary")
        wrong = client.get(
            "/documents/metrics/summary", headers={"X-DocFlow-Key": "wrong"}
        )
        correct = client.get(
            "/documents/metrics/summary", headers={"X-DocFlow-Key": "k" * 32}
        )
        public = client.get("/about")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert correct.status_code == 200
    assert public.status_code == 200


def test_explicit_local_mode_allows_keyless_access(client):
    response = client.get("/documents/metrics/summary")
    assert response.status_code == 200


def test_hosted_settings_fail_closed():
    try:
        Settings(
            deployment_mode="hosted",
            database_url="postgresql+asyncpg://docflow_app@db/docflow_ai",
            cors_allow_origins="https://documents.example.test",
            trusted_hosts="documents.example.test",
        )
    except ValueError as exc:
        assert "DOCFLOW_API_KEY" in str(exc)
    else:
        raise AssertionError("hosted mode accepted a missing access key")
