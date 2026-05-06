from pydantic import model_validator
from pydantic_settings import BaseSettings

from env_expand import expand_env


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 9000
    # Optional shared secret. If set, requests must include
    # Authorization: Bearer <shared_secret> (only enforced on port 9000)
    shared_secret: str | None = None

    # Dev port — auth is skipped when running on this port
    dev_port: int = 9001

    # Paths for persistent data
    amazon_session_dir: str = "~/.config/octo-satellite/amazon"
    monarch_session_dir: str = "~/.config/octo-satellite/monarch"
    audit_log_dir: str = "~/.config/octo-satellite/logs"

    model_config = {"env_prefix": "OCTO_"}

    @model_validator(mode="after")
    def _expand_env_vars(self):
        """Expand ${VAR} references in string fields."""
        for field_name in type(self).model_fields:
            value = getattr(self, field_name)
            if isinstance(value, str):
                setattr(self, field_name, expand_env(value))
        return self


settings = Settings()
