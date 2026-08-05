"""Configuration validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pathable_api.core.config import (
    ConfigurationError,
    Settings,
    get_settings,
    reset_settings_cache,
)
from tests.conftest import build_settings, settings_from


class TestDefaults:
    def test_development_defaults_are_usable(self) -> None:
        settings = settings_from({})

        assert settings.environment == "development"
        assert settings.service_name == "pathable-api"
        assert settings.api_port == 8000
        assert settings.database_url is None
        assert settings.is_production is False
        assert settings.docs_enabled is True

    def test_enum_values_are_case_insensitive(self) -> None:
        settings = settings_from(
            {"environment": "TEST", "log_level": "debug", "log_format": "JSON"}
        )

        assert settings.environment == "test"
        assert settings.log_level == "DEBUG"
        assert settings.log_format == "json"


@pytest.mark.usefixtures("clean_env")
class TestEnvironmentSource:
    """The pydantic-settings environment source itself, not just field validation."""

    def test_values_are_read_from_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("API_PORT", "9001")
        monkeypatch.setenv("LOG_LEVEL", "debug")
        monkeypatch.setenv("ALLOWED_ORIGINS", "http://a.example,http://b.example")

        settings = Settings(_env_file=None)

        assert settings.environment == "test"
        assert settings.api_port == 9001
        assert settings.log_level == "DEBUG"
        assert settings.allowed_origins == ("http://a.example", "http://b.example")

    def test_invalid_environment_value_fails_loudly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_PORT", "not-a-port")

        with pytest.raises(ValidationError, match="api_port"):
            Settings(_env_file=None)


class TestPortAndHost:
    @pytest.mark.parametrize("port", [0, -1, 65536, 99999])
    def test_out_of_range_port_is_rejected(self, port: int) -> None:
        with pytest.raises(ValidationError, match="api_port"):
            build_settings(api_port=port)

    @pytest.mark.parametrize("port", [1, 8000, 65535])
    def test_valid_port_is_accepted(self, port: int) -> None:
        assert build_settings(api_port=port).api_port == port

    @pytest.mark.parametrize("host", ["", "   ", "bad host"])
    def test_blank_or_spaced_host_is_rejected(self, host: str) -> None:
        with pytest.raises(ValidationError):
            build_settings(api_host=host)


class TestAllowedOrigins:
    def test_comma_separated_string_is_parsed(self) -> None:
        settings = settings_from(
            {"allowed_origins": "http://localhost:3000, https://pathable.example"}
        )

        assert settings.allowed_origins == (
            "http://localhost:3000",
            "https://pathable.example",
        )

    def test_trailing_slash_is_normalised_away(self) -> None:
        # Browsers compare the Origin header byte-for-byte; a trailing slash would
        # silently never match and produce a baffling CORS failure.
        settings = settings_from({"allowed_origins": "http://localhost:3000/"})

        assert settings.allowed_origins == ("http://localhost:3000",)

    def test_duplicates_are_collapsed_preserving_order(self) -> None:
        settings = settings_from(
            {"allowed_origins": "https://b.example,https://a.example,https://b.example/"}
        )

        assert settings.allowed_origins == ("https://b.example", "https://a.example")

    @pytest.mark.parametrize(
        "origin",
        [
            "localhost:3000",
            "ftp://example.com",
            "http://",
            "https://example.com/some/path",
            "https://example.com?q=1",
        ],
    )
    def test_malformed_origin_is_rejected(self, origin: str) -> None:
        with pytest.raises(ValidationError, match="Invalid CORS origin"):
            settings_from({"allowed_origins": origin})

    def test_wildcard_is_allowed_outside_production(self) -> None:
        assert settings_from({"allowed_origins": "*"}).allowed_origins == ("*",)

    def test_credentials_are_never_enabled(self) -> None:
        # Structurally prevents the allow_origins=['*'] + credentials=True footgun.
        assert build_settings().cors_allow_credentials is False


class TestDatabaseUrl:
    def test_bare_postgresql_scheme_is_normalised_to_psycopg(self) -> None:
        settings = build_settings(database_url="postgresql://u:p@db:5432/pathable")

        assert settings.database_url == "postgresql+psycopg://u:p@db:5432/pathable"

    def test_postgres_alias_is_normalised(self) -> None:
        settings = build_settings(database_url="postgres://u:p@db:5432/pathable")

        assert settings.database_url == "postgresql+psycopg://u:p@db:5432/pathable"

    def test_already_qualified_url_is_left_alone(self) -> None:
        url = "postgresql+psycopg://u:p@db:5432/pathable"

        assert build_settings(database_url=url).database_url == url

    @pytest.mark.parametrize(
        "url",
        [
            "mysql://u:p@db:3306/pathable",
            "sqlite:///./local.db",
            "postgresql+asyncpg://u:p@db:5432/pathable",
        ],
    )
    def test_unsupported_driver_is_rejected(self, url: str) -> None:
        with pytest.raises(ValidationError, match="postgresql\\+psycopg"):
            build_settings(database_url=url)

    def test_missing_database_name_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="database name"):
            build_settings(database_url="postgresql://u:p@db:5432")

    def test_missing_host_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must include a host"):
            build_settings(database_url="postgresql:///pathable")

    def test_blank_url_becomes_none(self) -> None:
        assert build_settings(database_url="   ").database_url is None

    def test_require_database_url_names_the_missing_variable(self) -> None:
        with pytest.raises(ConfigurationError, match="DATABASE_URL"):
            build_settings(database_url=None).require_database_url()

    def test_require_database_url_returns_configured_value(self) -> None:
        settings = build_settings(database_url="postgresql://u:p@db:5432/pathable")

        assert settings.require_database_url() == settings.database_url


class TestCredentialSafety:
    def test_safe_database_target_excludes_credentials(self) -> None:
        settings = build_settings(
            database_url="postgresql://pathable:sup3r-s3cret@db.internal:5432/pathable"
        )

        target = settings.safe_database_target()

        assert target == "db.internal:5432/pathable"
        assert "sup3r-s3cret" not in target
        assert "pathable:" not in target

    def test_safe_database_target_without_configuration(self) -> None:
        assert build_settings(database_url=None).safe_database_target() == "unconfigured"

    def test_safe_database_target_without_explicit_port(self) -> None:
        settings = build_settings(database_url="postgresql://u:p@db.internal/pathable")

        assert settings.safe_database_target() == "db.internal/pathable"


class TestReadinessTimeout:
    @pytest.mark.parametrize("timeout", [0.0, -1.0, 30.1, 120.0])
    def test_out_of_range_timeout_is_rejected(self, timeout: float) -> None:
        with pytest.raises(ValidationError, match="readiness_timeout_seconds"):
            build_settings(readiness_timeout_seconds=timeout)

    @pytest.mark.parametrize("timeout", [0.1, 2.0, 30.0])
    def test_valid_timeout_is_accepted(self, timeout: float) -> None:
        assert (
            build_settings(readiness_timeout_seconds=timeout).readiness_timeout_seconds == timeout
        )


class TestVersion:
    @pytest.mark.parametrize("version", ["0.1.0", "1.2.3-rc.1", "0.1.0+build.7"])
    def test_valid_versions(self, version: str) -> None:
        assert build_settings(app_version=version).app_version == version

    @pytest.mark.parametrize("version", ["1.0 beta", "v1/2", "release candidate"])
    def test_invalid_versions_are_rejected(self, version: str) -> None:
        with pytest.raises(ValidationError, match="APP_VERSION"):
            build_settings(app_version=version)


class TestProductionHardening:
    def test_production_requires_a_database_url(self) -> None:
        with pytest.raises(ValidationError, match="DATABASE_URL is required in production"):
            build_settings(
                environment="production",
                database_url=None,
                allowed_origins=("https://pathable.example",),
                log_format="json",
            )

    def test_production_requires_explicit_origins(self) -> None:
        with pytest.raises(ValidationError, match="at least one explicit origin"):
            build_settings(
                environment="production",
                database_url="postgresql://u:p@db:5432/pathable",
                allowed_origins=(),
                log_format="json",
            )

    def test_production_rejects_wildcard_origin(self) -> None:
        with pytest.raises(ValidationError, match="must not contain"):
            build_settings(
                environment="production",
                database_url="postgresql://u:p@db:5432/pathable",
                allowed_origins=("*",),
                log_format="json",
            )

    def test_production_requires_json_logs(self) -> None:
        with pytest.raises(ValidationError, match="LOG_FORMAT must be 'json'"):
            build_settings(
                environment="production",
                database_url="postgresql://u:p@db:5432/pathable",
                allowed_origins=("https://pathable.example",),
                log_format="console",
            )

    def test_every_production_problem_is_reported_at_once(self) -> None:
        # A deployer fixing one variable at a time across four restarts is a bad
        # afternoon; the validator reports the full set.
        with pytest.raises(ValidationError) as raised:
            build_settings(
                environment="production",
                database_url=None,
                allowed_origins=(),
                log_format="console",
            )

        message = str(raised.value)
        assert "DATABASE_URL is required" in message
        assert "at least one explicit origin" in message
        assert "LOG_FORMAT must be 'json'" in message

    def test_valid_production_configuration_is_accepted(self) -> None:
        settings = build_settings(
            environment="production",
            database_url="postgresql://u:p@db:5432/pathable",
            allowed_origins=("https://pathable.example",),
            log_format="json",
        )

        assert settings.is_production is True
        assert settings.docs_enabled is False


@pytest.mark.usefixtures("clean_env")
class TestSettingsCache:
    def test_get_settings_is_cached(self) -> None:
        reset_settings_cache()
        try:
            assert get_settings() is get_settings()
        finally:
            reset_settings_cache()

    def test_reset_returns_a_fresh_instance(self) -> None:
        reset_settings_cache()
        first = get_settings()
        reset_settings_cache()
        try:
            assert get_settings() is not first
        finally:
            reset_settings_cache()
