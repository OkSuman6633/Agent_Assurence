from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field, HttpUrl, field_validator

class AdapterType(str, Enum):
    http = "http"
    synthetic = "synthetic"

class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    adapter_type: AdapterType = AdapterType.http
    endpoint_url: HttpUrl | None = None
    allowed_hosts: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    functions: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Name of an environment variable holding the token, never the token itself.
    auth_env_var: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{1,127}$")
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    authorised: bool = False
    scope_description: str = Field(default="", max_length=2000)

    @field_validator("allowed_hosts")
    @classmethod
    def validate_allowed_hosts(cls, v: list[str], info: Any) -> list[str]:
        # If adapter is http, allowed_hosts cannot be empty
        # Pydantic v2 validator
        return v

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint(cls, v: HttpUrl | None, info: Any) -> HttpUrl | None:
        if v is not None:
            if v.scheme not in ("http", "https"):
                raise ValueError("endpoint_url must use http or https")
            if v.username or v.password:
                raise ValueError("credentials must not be embedded in endpoint_url")
        return v

    def model_post_init(self, __context: Any) -> None:
        if self.adapter_type == AdapterType.http:
            if not self.endpoint_url:
                raise ValueError("endpoint_url is required when adapter_type is http")
            if not self.allowed_hosts:
                raise ValueError("allowed_hosts must contain at least one host when adapter_type is http")
        if self.adapter_type == AdapterType.synthetic:
            if self.endpoint_url:
                raise ValueError("endpoint_url must not be set when adapter_type is synthetic")
            if self.allowed_hosts:
                raise ValueError("allowed_hosts must be empty when adapter_type is synthetic")

class AgentRead(BaseModel):
    id: str
    tenant_id: str
    name: str
    adapter_type: AdapterType
    endpoint_url: HttpUrl | None
    allowed_hosts: list[str]
    capabilities: list[str] = Field(default_factory=list)
    functions: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float
    authorised: bool
    scope_description: str
