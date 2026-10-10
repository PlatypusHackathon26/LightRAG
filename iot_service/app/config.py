from pathlib import Path
from typing import Dict, Literal, Optional
import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MetricConfig(BaseModel):
    label: str
    unit: str
    direction: Literal["above", "below", "info"]
    normal_min: Optional[float] = None
    normal_max: Optional[float] = None
    warn: Optional[float] = None
    critical: Optional[float] = None
    display_min: Optional[float] = None
    display_max: Optional[float] = None
    decimals: int = Field(default=1, ge=0, le=4)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "MetricConfig":
        if self.direction == "above":
            if self.warn is not None and self.critical is not None:
                if self.warn >= self.critical:
                    raise ValueError(
                        f"For direction 'above', warn ({self.warn}) must be strictly less than critical ({self.critical})"
                    )
        elif self.direction == "below":
            if self.warn is not None and self.critical is not None:
                if self.warn <= self.critical:
                    raise ValueError(
                        f"For direction 'below', warn ({self.warn}) must be strictly greater than critical ({self.critical})"
                    )
        if self.display_min is not None and self.display_max is not None:
            if self.display_min >= self.display_max:
                raise ValueError(
                    f"display_min ({self.display_min}) must be strictly less than display_max ({self.display_max})"
                )
        return self


class MachineConfig(BaseModel):
    name: str
    description: Optional[str] = ""
    rpm_setpoint: float = Field(default=1500.0, ge=0.0)
    rpm_min_safe: float = Field(default=800.0, ge=0.0)
    rpm_max: float = Field(default=3000.0, ge=0.0)
    metrics: Dict[str, MetricConfig]

    @model_validator(mode="after")
    def validate_rpm_limits(self) -> "MachineConfig":
        if self.rpm_min_safe > self.rpm_max:
            raise ValueError(
                f"Machine {self.name}: rpm_min_safe ({self.rpm_min_safe}) cannot be greater than rpm_max ({self.rpm_max})"
            )
        if not (self.rpm_min_safe <= self.rpm_setpoint <= self.rpm_max):
            raise ValueError(
                f"Machine {self.name}: rpm_setpoint ({self.rpm_setpoint}) must be between {self.rpm_min_safe} and {self.rpm_max}"
            )
        return self


class MachinesConfig(BaseModel):
    machines: Dict[str, MachineConfig]


def evaluate_metric_status(value: float, metric_config: MetricConfig) -> Literal["normal", "warn", "critical"]:
    """
    Evaluates metric status considering the direction and warn/critical thresholds.
    Edge values:
      direction 'above': value >= critical -> critical, value >= warn -> warn, else normal
      direction 'below': value <= critical -> critical, value <= warn -> warn, else normal
      direction 'info': always normal
    """
    direction = metric_config.direction
    if direction == "info":
        return "normal"

    crit = metric_config.critical
    warn = metric_config.warn

    if direction == "above":
        if crit is not None and value >= crit:
            return "critical"
        if warn is not None and value >= warn:
            return "warn"
        return "normal"
    elif direction == "below":
        if crit is not None and value <= crit:
            return "critical"
        if warn is not None and value <= warn:
            return "warn"
        return "normal"

    return "normal"


def resolve_file_path(target_path: str) -> Path:
    """Find file in common candidate locations relative to cwd and iot_service."""
    candidates = [
        Path(target_path),
        Path("iot_service") / target_path,
        Path(__file__).resolve().parent.parent / target_path,
        Path(__file__).resolve().parent / target_path,
    ]
    for p in candidates:
        if p.exists():
            return p.resolve()
    return Path(target_path).resolve()


def load_machines_config(config_path: str = "config/machines.yaml") -> MachinesConfig:
    resolved = resolve_file_path(config_path)
    if not resolved.exists():
        raise FileNotFoundError(f"Machines config file not found at: {resolved}")
    with open(resolved, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return MachinesConfig.model_validate(data)


class Settings(BaseSettings):
    IOT_API_KEY: str = "test-api-key-denso-2026"
    IOT_ADMIN_KEY: str = "test-admin-key-denso-2026"

    MQTT_HOST: str = "localhost"
    MQTT_PORT: int = 1883

    # 127.0.0.1, not localhost: on Windows the async pool tried ::1 first and never connected to the
    # container, which publishes the port on 127.0.0.1 only (iot_service/docker-compose.yml).
    DB_DSN: str = "postgresql://postgres:postgres@127.0.0.1:5433/denso_iot"
    DB_REQUIRED: bool = True
    DB_MODE: str = "timescale"  # "timescale" or "memory"
    # 9700 is the DENSO Agent Gateway (denso/gateway), the UI's single entry point; it forwards
    # incidents, telemetry and actions here. Localhost only: the /agent/* routes have no auth.
    GATEWAY_HOST: str = "127.0.0.1"
    GATEWAY_PORT: int = 9710

    PUBLISH_INTERVAL_S: float = 5.0
    SIM_SPEEDUP: float = 1.0
    DEDUP_WINDOW_S: int = 600

    ACTION_TTL_S: int = 60
    AUTONOMY_MODE: str = "hitl"
    AGENT_ENABLED: bool = True
    AGENT_MODE: str = "rules"

    DASHBOARD_TOKEN: str = ""
    SSE_MAX_CLIENTS: int = 50
    WEBUI_URL: str = "http://localhost:5173"

    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_API_KEY: str = "dummy-llm-key"
    LLM_MODEL: str = "gpt-4o-mini"

    RAG_BASE_URL: str = "http://localhost:9621"
    RAG_API_KEY: str = "dummy-rag-key"
    RAG_MODE: str = "auto"
    # Ask through the DENSO Agent Gateway (POST /agent/chat): access level, answer language and page
    # citations as in the UI. Empty = query LightRAG at RAG_BASE_URL directly (no citations by page).
    RAG_GATEWAY_URL: str = "http://127.0.0.1:9700"
    RAG_GATEWAY_TOKEN: str = ""  # a token from denso/gateway/users.json; empty = guest (level 1)
    # A gateway answer takes ~20-25 s on the free API; under this the "auto" mode fell back to the stub.
    RAG_TIMEOUT_S: float = 90.0

    MACHINES_CONFIG_PATH: str = "config/machines.yaml"

    model_config = SettingsConfigDict(
        env_file=(".env", "iot_service/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
