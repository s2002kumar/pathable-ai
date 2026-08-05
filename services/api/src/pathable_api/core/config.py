"""Validated application configuration.

Every value the service depends on is declared here and validated at startup, so
a misconfigured deployment fails immediately and loudly instead of surfacing as a
confusing runtime error later. Production is held to stricter rules than local
development — see :meth:`Settings._enforce_production_requirements`.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Final, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormat = Literal["json", "console"]

#: SQLAlchemy driver PathAble standardises on. Psycopg 3 serves both the async
#: application engine and Alembic's synchronous engine from one URL, which is why
#: a bare ``postgresql://`` URL is normalised rather than rejected.
_REQUIRED_DRIVER: Final = "postgresql+psycopg"

_WILDCARD_ORIGIN: Final = "*"

#: ``src/pathable_api/core/config.py`` -> ``services/api``
_SERVICE_ROOT: Final = Path(__file__).resolve().parents[3]
#: ``services/api`` -> repository root
_REPO_ROOT: Final = _SERVICE_ROOT.parents[1]

#: Resolved from the package location rather than the process CWD, so `uv run`
#: from services/api and `uvicorn` from the repo root both read the same files.
#: A service-local .env wins over the shared root one.
_ENV_FILES: Final = (_REPO_ROOT / ".env", _SERVICE_ROOT / ".env")


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class ConfigurationError(RuntimeError):
    """Raised when configuration is structurally valid but unsafe for the environment."""


class Settings(BaseSettings):
    """Runtime configuration, sourced from environment variables and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Identity ---------------------------------------------------------
    environment: Environment = "development"
    service_name: str = Field(default="pathable-api", min_length=1, max_length=64)
    app_version: str = Field(default="0.1.0", min_length=1, max_length=32)

    # --- HTTP -------------------------------------------------------------
    api_host: str = Field(default="127.0.0.1", min_length=1)
    api_port: Annotated[int, Field(ge=1, le=65535)] = 8000
    # NoDecode disables pydantic-settings' default JSON decoding for complex types.
    # Without it, ALLOWED_ORIGINS="http://a,http://b" is fed to json.loads and blows
    # up before the comma-splitting validator below ever runs.
    allowed_origins: Annotated[tuple[str, ...], NoDecode] = ()

    # --- Data -------------------------------------------------------------
    database_url: str | None = None
    readiness_timeout_seconds: Annotated[float, Field(gt=0.0, le=30.0)] = 2.0
    db_pool_size: Annotated[int, Field(ge=1, le=50)] = 5
    db_pool_max_overflow: Annotated[int, Field(ge=0, le=50)] = 5

    # --- Observability ----------------------------------------------------
    log_level: LogLevel = "INFO"
    log_format: LogFormat = "json"

    # ------------------------------------------------------------------
    # Field validation
    # ------------------------------------------------------------------
    @field_validator("environment", "log_level", "log_format", mode="before")
    @classmethod
    def _normalise_enums(cls, value: object, info: ValidationInfo) -> object:
        """Accept ``production``/``PRODUCTION`` and ``info``/``INFO`` alike."""
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped.upper() if info.field_name == "log_level" else stripped.lower()

    @field_validator("app_version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9A-Za-z.\-+]+", value):
            msg = "APP_VERSION may only contain alphanumerics, '.', '-' and '+'"
            raise ValueError(msg)
        return value

    @field_validator("api_host")
    @classmethod
    def _validate_host(cls, value: str) -> str:
        host = value.strip()
        if not host or any(character.isspace() for character in host):
            msg = "API_HOST must be a non-empty value without whitespace"
            raise ValueError(msg)
        return host

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(_split_csv(value))
        return value

    @field_validator("allowed_origins", mode="after")
    @classmethod
    def _validate_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned: list[str] = []
        for origin in value:
            if origin == _WILDCARD_ORIGIN:
                cleaned.append(origin)
                continue
            parts = urlsplit(origin)
            if parts.scheme not in {"http", "https"} or not parts.netloc:
                msg = (
                    f"Invalid CORS origin {origin!r}: expected scheme://host[:port] "
                    f"(for example http://localhost:3000) or '*'"
                )
                raise ValueError(msg)
            if parts.path not in {"", "/"} or parts.query or parts.fragment:
                msg = f"Invalid CORS origin {origin!r}: origins must not include a path or query"
                raise ValueError(msg)
            # Browsers compare origins byte-for-byte, and a trailing slash never matches.
            cleaned.append(f"{parts.scheme}://{parts.netloc}")

        # Preserve declaration order but drop duplicates.
        return tuple(dict.fromkeys(cleaned))

    @field_validator("database_url", mode="after")
    @classmethod
    def _validate_database_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        url = value.strip()
        if not url:
            return None

        parts = urlsplit(url)
        if parts.scheme in {"postgres", "postgresql"}:
            url = url.replace(f"{parts.scheme}://", f"{_REQUIRED_DRIVER}://", 1)
            parts = urlsplit(url)
        if parts.scheme != _REQUIRED_DRIVER:
            msg = (
                f"DATABASE_URL must use the {_REQUIRED_DRIVER} driver "
                f"(got {parts.scheme!r}); psycopg 3 backs both the async app engine "
                f"and Alembic's synchronous engine"
            )
            raise ValueError(msg)
        if not parts.hostname:
            msg = "DATABASE_URL must include a host"
            raise ValueError(msg)
        if not parts.path.lstrip("/"):
            msg = "DATABASE_URL must include a database name"
            raise ValueError(msg)
        return url

    # ------------------------------------------------------------------
    # Cross-field validation
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _enforce_production_requirements(self) -> Self:
        if self.environment != "production":
            return self

        problems: list[str] = []
        if not self.database_url:
            problems.append("DATABASE_URL is required in production")
        if not self.allowed_origins:
            problems.append("ALLOWED_ORIGINS must list at least one explicit origin in production")
        if _WILDCARD_ORIGIN in self.allowed_origins:
            problems.append(
                "ALLOWED_ORIGINS must not contain '*' in production; list exact origins"
            )
        if self.log_format != "json":
            problems.append("LOG_FORMAT must be 'json' in production for log ingestion")

        if problems:
            raise ValueError("; ".join(problems))
        return self

    # ------------------------------------------------------------------
    # Derived values
    # ------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_allow_credentials(self) -> bool:
        """Phase 0 has no authentication, so credentialed CORS is never enabled.

        This also structurally prevents the ``allow_origins=['*']`` +
        ``allow_credentials=True`` combination, which browsers reject and which is
        a common source of accidental cross-origin exposure.
        """
        return False

    @property
    def docs_enabled(self) -> bool:
        """Interactive docs are a development affordance, not a production surface."""
        return not self.is_production

    def require_database_url(self) -> str:
        """Return the database URL or explain precisely what is missing."""
        if not self.database_url:
            msg = (
                "DATABASE_URL is not configured. Set it in .env "
                "(see .env.example) or export it in the environment."
            )
            raise ConfigurationError(msg)
        return self.database_url

    def safe_database_target(self) -> str:
        """A ``host:port/database`` summary that never contains credentials.

        Used in logs and health payloads so operators can tell *which* database was
        unreachable without the password ever leaving the process.
        """
        if not self.database_url:
            return "unconfigured"
        parts = urlsplit(self.database_url)
        host = parts.hostname or "unknown-host"
        port = f":{parts.port}" if parts.port else ""
        database = parts.path.lstrip("/") or "unknown-db"
        return f"{host}{port}/{database}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached because configuration is immutable for the lifetime of the process;
    tests clear the cache via :func:`reset_settings_cache`.
    """
    return Settings()


def reset_settings_cache() -> None:
    """Drop the cached settings so the next call re-reads the environment."""
    get_settings.cache_clear()
