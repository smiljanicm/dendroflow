import pytest

from dendroflow import config, database


def test_target_uses_process_environment_over_dotenv_and_is_immutable(monkeypatch):
    dotenv = {
        "DENDROFLOW_ENVIRONMENT": "from-file",
        "POSTGRES_HOST": "db-from-file",
        "POSTGRES_PORT": "5544",
        "POSTGRES_USER": "user-from-file",
        "POSTGRES_PASSWORD": "secret-from-file",
    }
    monkeypatch.setattr(config, "load_env", lambda _path: dotenv)
    for key in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DENDROFLOW_ENVIRONMENT", "local-dev")
    monkeypatch.setenv("POSTGRES_HOST", "localhost")

    target = config.get_database_target()

    assert target.environment == "local-dev"
    assert dict(target.connection_parameters) == {
        "host": "localhost",
        "port": "5544",
        "user": "user-from-file",
        "password": "secret-from-file",
    }
    assert "secret-from-file" not in repr(target)
    with pytest.raises(TypeError):
        target.connection_parameters["host"] = "changed"


@pytest.mark.parametrize(
    "label",
    ["", "  local-dev", "local-dev  ", "local\ndev", "x" * 129],
)
def test_invalid_environment_label_is_rejected(monkeypatch, label):
    monkeypatch.setattr(config, "load_env", lambda _path: {})
    monkeypatch.setenv("DENDROFLOW_ENVIRONMENT", label)

    with pytest.raises(RuntimeError, match="DENDROFLOW_ENVIRONMENT"):
        config.get_target_environment()


def test_environment_label_can_be_read_without_database_credentials(monkeypatch):
    monkeypatch.setattr(config, "load_env", lambda _path: {})
    monkeypatch.setenv("DENDROFLOW_ENVIRONMENT", "local-dev")
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    assert config.get_target_environment() == "local-dev"


def test_environment_label_defaults_to_local(monkeypatch):
    monkeypatch.setattr(config, "load_env", lambda _path: {})
    monkeypatch.delenv("DENDROFLOW_ENVIRONMENT", raising=False)
    monkeypatch.setenv("POSTGRES_USER", "test-user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password")

    assert config.get_target_environment() == "local"
    assert config.get_database_target().environment == "local"


def test_database_connections_share_the_active_target(monkeypatch):
    target = config.DatabaseTarget(
        environment="test-target",
        connection_parameters={
            "host": "db.example",
            "port": "5433",
            "user": "tester",
            "password": "secret",
        },
    )
    calls = []
    monkeypatch.setattr(database.psycopg, "connect", lambda **kwargs: calls.append(kwargs))

    with database.use_database_target(target):
        database.connect("dendroflow_metadata")
        database.connect("dendroflow_raw")

    assert calls == [
        {
            "dbname": "dendroflow_metadata",
            "host": "db.example",
            "port": "5433",
            "user": "tester",
            "password": "secret",
        },
        {
            "dbname": "dendroflow_raw",
            "host": "db.example",
            "port": "5433",
            "user": "tester",
            "password": "secret",
        },
    ]


def test_database_target_context_is_restored_after_failure(monkeypatch):
    target = config.DatabaseTarget("outer", {"host": "outer-host"})
    monkeypatch.setattr(database.psycopg, "connect", lambda **kwargs: kwargs)

    with database.use_database_target(target):
        with pytest.raises(ValueError), database.use_database_target(
            config.DatabaseTarget("inner", {})
        ):
            raise ValueError("test")
        assert database.connect("dendroflow_raw")["host"] == "outer-host"
