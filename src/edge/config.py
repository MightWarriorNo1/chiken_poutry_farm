"""Layered configuration: defaults → YAML → env vars → CLI flags.

Pydantic Settings handles env-var binding (`EDGE_*`) and nested groups via the
`__` delimiter (e.g. `EDGE_CLOUD__BASE_URL`). YAML overlay loads from
`/etc/prosper-edge/config.yaml` if present, then `./config.yaml`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CloudSettings(BaseModel):
    base_url: str = "http://localhost:8080"
    ingest_path: str = "/v1/ingest"
    config_path: str = "/v1/edge/config"
    auth_token: str = ""
    request_timeout_seconds: float = 10.0


class StorageSettings(BaseModel):
    outbox_path: Path = Path("./outbox.db")


class MqttSettings(BaseModel):
    enabled: bool = False
    host: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    topic_prefix: str = "prosper/sensors"


class CadenceSettings(BaseModel):
    frame_interval_seconds: float = 2.0
    heartbeat_interval_seconds: int = 30
    config_poll_interval_seconds: int = 300
    sync_batch_size: int = 50
    sync_flush_interval_seconds: int = 5


class TelemetrySettings(BaseModel):
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    otel_exporter: Literal["console", "otlp", "none"] = "console"
    otel_otlp_endpoint: str = ""


class Settings(BaseSettings):
    """Root config. Env vars override; YAML overlay loaded explicitly via load_settings()."""

    model_config = SettingsConfigDict(
        env_prefix="EDGE_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    device_id: str = "edge-dev-001"
    device_name: str = "Dev Device"
    software_version: str = "0.1.0"

    # When set, use the on-disk file as the EdgeConfig source instead of polling the cloud.
    # Useful for offline dev/demos. See `example.config.yaml`.
    static_config_path: Path | None = None

    cloud: CloudSettings = Field(default_factory=CloudSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    mqtt: MqttSettings = Field(default_factory=MqttSettings)
    cadence: CadenceSettings = Field(default_factory=CadenceSettings)
    telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)


# Deep-merge helper for YAML overlay.
def _deep_merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


_YAML_CANDIDATES: tuple[Path, ...] = (
    Path("/etc/prosper-edge/config.yaml"),
    Path("./config.yaml"),
)


def load_settings(extra_yaml: Path | None = None) -> Settings:
    """Load settings with YAML files layered under env vars.

    Order (later wins):
      1. defaults
      2. YAML files in `_YAML_CANDIDATES` + `extra_yaml`
      3. environment variables / .env
    """
    yaml_data: dict = {}
    candidates = list(_YAML_CANDIDATES)
    if extra_yaml is not None:
        candidates.append(extra_yaml)
    for path in candidates:
        if path.is_file():
            with path.open("r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            yaml_data = _deep_merge(yaml_data, loaded)

    # Build a Settings instance from YAML, then let pydantic-settings overlay env.
    yaml_settings = Settings.model_validate(yaml_data) if yaml_data else Settings()
    env_settings = Settings()
    merged = _deep_merge(yaml_settings.model_dump(), env_settings.model_dump())
    return Settings.model_validate(merged)
