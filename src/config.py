"""Typed application configuration."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


Environment = Literal["local", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARN", "ERROR"]
RetrievalStyle = Literal["fulltext", "vector", "graph"]


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "config" / "defaults.toml"

LOG_LEVELS: tuple[LogLevel, ...] = ("DEBUG", "INFO", "WARN", "ERROR")
RETRIEVAL_STYLES: tuple[RetrievalStyle, ...] = ("fulltext", "vector", "graph")


@dataclass(frozen=True, slots=True)
class Settings:
    """Application settings loaded from environment variables."""

    environment: Environment
    glpi_url: str
    glpi_db_host: str
    glpi_db_port: int
    glpi_db_name: str
    glpi_db_user: str
    glpi_db_password: str | None
    glpi_app_token: str | None
    glpi_user_token: str | None
    glpi_list_page_size: int
    postgres_dsn: str
    phoenix_endpoint: str
    phoenix_project_name: str
    otel_exporter_otlp_endpoint: str
    groq_api_key: str | None
    groq_base_url: str
    groq_model: str
    http_timeout_seconds: float
    log_search_limit: int
    vector_search_limit: int
    recent_deploys_hours: int
    error_rate_window_minutes: int
    metric_window_minutes: int
    embedding_dimensions: int
    embedding_model: str
    agent_max_steps: int
    auto_write_confidence: float
    approval_token_ttl_seconds: int
    webhook_response_timeout_ms: int
    trace_sample_rate: float


def load_env_file(path: Path = DEFAULT_ENV_FILE) -> dict[str, str]:
    """Return key/value pairs from a dotenv-style file."""
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def get_env_value(name: str, env_file_values: dict[str, str]) -> str | None:
    """Return one setting value from process env or env file values."""
    return os.environ.get(name) or env_file_values.get(name)


def load_config_file(path: Path = DEFAULT_CONFIG_FILE) -> dict[str, Any]:
    """Return non-secret defaults from the project config file."""
    with path.open("rb") as config_file:
        return tomllib.load(config_file)


def require_config_value(config: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Return one required config value."""
    current: Any = config
    for key in path:
        if not isinstance(current, dict) or key not in current:
            dotted_path = ".".join(path)
            msg = f"Missing config value: {dotted_path}"
            raise KeyError(msg)
        current = current[key]
    return current


def get_string(
    name: str,
    default: str,
    env_file_values: dict[str, str],
) -> str:
    """Return a string setting."""
    value = get_env_value(name, env_file_values)
    return value if value is not None else default


def get_optional_string(name: str, env_file_values: dict[str, str]) -> str | None:
    """Return an optional string setting."""
    value = get_env_value(name, env_file_values)
    return value or None


def get_int(
    name: str,
    default: int,
    env_file_values: dict[str, str],
) -> int:
    """Return an integer setting."""
    value = get_env_value(name, env_file_values)
    return int(value) if value is not None else default


def get_float(
    name: str,
    default: float,
    env_file_values: dict[str, str],
) -> float:
    """Return a float setting."""
    value = get_env_value(name, env_file_values)
    return float(value) if value is not None else default


def get_environment(default: str, env_file_values: dict[str, str]) -> Environment:
    """Return a validated environment name."""
    value = get_string("APP_ENV", default, env_file_values)
    if value not in ("local", "test", "production"):
        msg = "APP_ENV must be one of: local, test, production"
        raise ValueError(msg)
    return value


def load_settings(
    env_file: Path = DEFAULT_ENV_FILE,
    config_file: Path = DEFAULT_CONFIG_FILE,
) -> Settings:
    """Return typed project settings."""
    env_file_values = load_env_file(env_file)
    config = load_config_file(config_file)
    return Settings(
        environment=get_environment(
            require_config_value(config, ("environment",)),
            env_file_values,
        ),
        glpi_url=get_string(
            "GLPI_URL",
            require_config_value(config, ("glpi", "url")),
            env_file_values,
        ),
        glpi_db_host=get_string(
            "GLPI_DB_HOST",
            require_config_value(config, ("glpi", "db_host")),
            env_file_values,
        ),
        glpi_db_port=get_int(
            "GLPI_DB_PORT",
            require_config_value(config, ("glpi", "db_port")),
            env_file_values,
        ),
        glpi_db_name=get_string(
            "GLPI_DB_NAME",
            require_config_value(config, ("glpi", "db_name")),
            env_file_values,
        ),
        glpi_db_user=get_string(
            "GLPI_DB_USER",
            require_config_value(config, ("glpi", "db_user")),
            env_file_values,
        ),
        glpi_db_password=get_optional_string("GLPI_DB_PASSWORD", env_file_values),
        glpi_app_token=get_optional_string("GLPI_APP_TOKEN", env_file_values),
        glpi_user_token=get_optional_string("GLPI_USER_TOKEN", env_file_values),
        glpi_list_page_size=get_int(
            "GLPI_LIST_PAGE_SIZE",
            require_config_value(config, ("glpi", "list_page_size")),
            env_file_values,
        ),
        postgres_dsn=get_string(
            "DB_DSN",
            require_config_value(config, ("postgres", "dsn")),
            env_file_values,
        ),
        phoenix_endpoint=get_string(
            "PHOENIX_ENDPOINT",
            require_config_value(config, ("phoenix", "endpoint")),
            env_file_values,
        ),
        phoenix_project_name=get_string(
            "PHOENIX_PROJECT_NAME",
            require_config_value(config, ("phoenix", "project_name")),
            env_file_values,
        ),
        otel_exporter_otlp_endpoint=get_string(
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            require_config_value(config, ("otel", "exporter_otlp_endpoint")),
            env_file_values,
        ),
        groq_api_key=get_optional_string("GROQ_API_KEY", env_file_values),
        groq_base_url=get_string(
            "GROQ_BASE_URL",
            require_config_value(config, ("groq", "base_url")),
            env_file_values,
        ),
        groq_model=get_string(
            "GROQ_MODEL",
            require_config_value(config, ("groq", "model")),
            env_file_values,
        ),
        http_timeout_seconds=get_float(
            "HTTP_TIMEOUT_SECONDS",
            require_config_value(config, ("http", "timeout_seconds")),
            env_file_values,
        ),
        log_search_limit=get_int(
            "LOG_SEARCH_LIMIT",
            require_config_value(config, ("tools", "log_search_limit")),
            env_file_values,
        ),
        vector_search_limit=get_int(
            "VECTOR_SEARCH_LIMIT",
            require_config_value(config, ("tools", "vector_search_limit")),
            env_file_values,
        ),
        recent_deploys_hours=get_int(
            "RECENT_DEPLOYS_HOURS",
            require_config_value(config, ("tools", "recent_deploys_hours")),
            env_file_values,
        ),
        error_rate_window_minutes=get_int(
            "ERROR_RATE_WINDOW_MINUTES",
            require_config_value(config, ("tools", "error_rate_window_minutes")),
            env_file_values,
        ),
        metric_window_minutes=get_int(
            "METRIC_WINDOW_MINUTES",
            require_config_value(config, ("tools", "metric_window_minutes")),
            env_file_values,
        ),
        embedding_dimensions=get_int(
            "EMBEDDING_DIMENSIONS",
            require_config_value(config, ("tools", "embedding_dimensions")),
            env_file_values,
        ),
        embedding_model=get_string(
            "EMBEDDING_MODEL",
            require_config_value(config, ("tools", "embedding_model")),
            env_file_values,
        ),
        agent_max_steps=get_int(
            "AGENT_MAX_STEPS",
            require_config_value(config, ("agent", "max_steps")),
            env_file_values,
        ),
        auto_write_confidence=get_float(
            "AUTO_WRITE_CONFIDENCE",
            require_config_value(config, ("agent", "auto_write_confidence")),
            env_file_values,
        ),
        approval_token_ttl_seconds=get_int(
            "APPROVAL_TOKEN_TTL_SECONDS",
            require_config_value(config, ("agent", "approval_token_ttl_seconds")),
            env_file_values,
        ),
        webhook_response_timeout_ms=get_int(
            "WEBHOOK_RESPONSE_TIMEOUT_MS",
            require_config_value(config, ("api", "webhook_response_timeout_ms")),
            env_file_values,
        ),
        trace_sample_rate=get_float(
            "TRACE_SAMPLE_RATE",
            require_config_value(config, ("tracing", "sample_rate")),
            env_file_values,
        ),
    )
