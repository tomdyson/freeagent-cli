from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from platformdirs import user_config_dir

PROD_BASE = "https://api.freeagent.com"
SANDBOX_BASE = "https://api.sandbox.freeagent.com"
DEFAULT_REDIRECT = "http://localhost:7878/callback"
DEFAULT_PORT = 7878


@dataclass
class Config:
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = DEFAULT_REDIRECT
    api_base: str = PROD_BASE
    refresh_token: str = ""
    access_token: str = ""
    access_token_expires_at: float = 0.0


def config_path() -> Path:
    d = Path(user_config_dir("freeagent-cli"))
    d.mkdir(parents=True, exist_ok=True)
    return d / "config.json"


def load() -> Config:
    p = config_path()
    if not p.exists():
        return Config()
    data = json.loads(p.read_text())
    return Config(**{k: v for k, v in data.items() if k in Config.__dataclass_fields__})


def save(config: Config) -> None:
    p = config_path()
    p.write_text(json.dumps(asdict(config), indent=2))
    os.chmod(p, 0o600)
