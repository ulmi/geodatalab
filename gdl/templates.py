"""Service templates: ready-made containers (PostGIS, ...) described in TOML.

Built-in templates live in templates/, your own in templates.d/ (gitignored;
a file there with the same name replaces the built-in one).
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field

from .config import ROOT, GdlError


@dataclass
class Template:
    key: str
    name: str
    description: str = ""
    port: int = 0                     # port inside the container
    images: dict[str, str] = field(default_factory=dict)   # variant -> image; first = default
    env: dict[str, str] = field(default_factory=dict)
    secrets: list[str] = field(default_factory=list)
    volume: str = ""                  # persistent data path inside the container
    shm_size: str = ""
    health: str = ""                  # shell command; exit 0 = healthy
    shell: list[str] = field(default_factory=lambda: ["sh"])
    url: str = ""

    def fill(self, text: str, env: dict[str, str], **extra) -> str:
        """Replace {ENV_VAR} / {host} / {port} placeholders; unknown ones stay as is."""
        values = {**env, **{k: str(v) for k, v in extra.items()}}
        return text.format_map(_Keep(values))


class _Keep(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def load() -> dict[str, Template]:
    found: dict[str, Template] = {}
    for folder in (ROOT / "templates", ROOT / "templates.d"):
        for f in sorted(folder.glob("*.toml")) if folder.is_dir() else []:
            raw = tomllib.loads(f.read_text(encoding="utf-8"))
            if not raw.get("images"):
                raise GdlError(f"Template {f.name}: needs an [images] table.")
            found[f.stem] = Template(key=f.stem, **raw)
    return found


def get(key: str) -> Template:
    try:
        return load()[key]
    except KeyError:
        raise GdlError(f"No template '{key}' (in templates/ or templates.d/).") from None
