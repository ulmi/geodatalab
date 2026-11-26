"""Settings (geodatalab.toml), instances and the legacy .geodatalab migration.

geodatalab.toml holds the default instance at the top level and named
instances under [instance.<name>], each storing only what differs from the
default (plus its own port). Settings for gdl itself (not per instance) live
in [gdl]. Example: geodatalab.example.toml.

Where pixi puts environments is pixi's own setting (`detached-environments`
in <checkout>/.pixi/config.toml), read and written here but never copied into
geodatalab.toml: on a noexec drive it must exist before gdl can run at all.
"""
from __future__ import annotations

import os
import re
import secrets
import shlex
import socket
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

import tomli_w

ROOT = Path(__file__).resolve().parent.parent
STATE_ROOT = ROOT / ".gdl"
GDL_PYTHON = "3.13"  # debian:trixie python3 — keep in sync with PYTHON in envs/pixi/gen_pixi.py

PROFILES = {
    "kitchen": "Python GIS + ML/spatial stats + JupyterLab + whitebox",
    "lab": "kitchen + GRASS GIS + SAGA GIS",
    "institute": "lab + R + Julia",
    "r+julia": "JupyterLab + R + Julia only",
}
BACKENDS = {
    "container": "Podman / Docker image (full stack incl. SAGA)",
    "pixi": "pixi env on the host, no container (no SAGA yet)",
}
MODES = {"lab": "Start JupyterLab", "idle": "No Jupyter (Dev Containers / shell only)"}
LIMIT_KEYS = ("memory", "memory_reserve", "cpus")
INSTANCE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
DATA_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
GDL_KEYS = {"runtime": "", "theme": "gruvbox"}  # [gdl] in geodatalab.toml; "" runtime = auto
RUNTIMES = {"": "auto — podman if installed, else docker", "podman": "Podman", "docker": "Docker"}
PIXI_CONFIG = Path(".pixi") / "config.toml"     # relative to a pixi project folder


class GdlError(Exception):
    """A user-facing error (printed without a traceback)."""


@dataclass
class DataDir:
    name: str
    path: str
    ro: bool = False


@dataclass
class Instance:
    """One fully resolved instance (default + overrides): a Jupyter workbench,
    or a service container made from a template (kind = "service")."""
    name: str = "default"
    kind: str = "workbench"        # workbench | service
    template: str = ""             # service: templates/<template>.toml
    image: str = ""                # service: the image to run
    shm_size: str = ""             # container /dev/shm size, e.g. 2g
    env: dict[str, str] = field(default_factory=dict)   # extra container environment
    backend: str = "container"
    profile: str = "lab"
    mode: str = "lab"
    port: int = 8888
    workspace: str = ""
    open: str = ""
    image_tag: str = ""
    memory: str = ""
    memory_reserve: str = ""
    cpus: str = ""
    data: list[DataDir] = field(default_factory=list)

    @property
    def is_service(self) -> bool:
        return self.kind == "service"

    @property
    def container_name(self) -> str:
        return "geodatalab" if self.name == "default" else f"geodatalab-{self.name}"

    @property
    def state_dir(self) -> Path:
        return STATE_ROOT / self.name

    @property
    def env_name(self) -> str:  # pixi environment: r+julia -> r-julia
        return re.sub(r"[^a-z0-9-]", "-", self.profile)


KEYS = [f.name for f in fields(Instance) if f.name != "name"]


def settings_path() -> Path:
    return Path(os.environ.get("GDL_CONFIG", ROOT / "geodatalab.toml"))


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or settings_path()
        self.base: dict = {}
        self.instances: dict[str, dict] = {}
        self.gdl: dict = dict(GDL_KEYS)
        if self.path.exists():
            raw = tomllib.loads(self.path.read_text(encoding="utf-8"))
            self.instances = {n: _flat(d) for n, d in raw.pop("instance", {}).items()}
            self.gdl.update({k: v for k, v in raw.pop("gdl", {}).items() if k in GDL_KEYS})
            self.base = _flat(raw)

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def names(self) -> list[str]:
        """Instance names. 'default' is the top level of the file; it is gone
        only after being deleted (file exists, top level empty)."""
        has_default = bool(self.base) or not self.exists
        return (["default"] if has_default else []) + sorted(self.instances)

    def get(self, name: str = "default") -> Instance:
        if name not in self.names():
            others = ", ".join(self.names()) or "none"
            raise GdlError(f"No instance '{name}' (instances: {others}).")
        inst = self._resolve(name)
        if inst.is_service:
            inst.backend = "container"  # services are always containers
        elif os.environ.get("GDL_BACKEND"):  # one-off override, never saved
            inst.backend = os.environ["GDL_BACKEND"]
        if inst.backend not in BACKENDS:
            raise GdlError(f"Unknown backend '{inst.backend}' (valid: {', '.join(BACKENDS)})")
        return inst

    def _resolve(self, name: str) -> Instance:
        """Top-level values + the instance's overrides (no existence check)."""
        merged = {**self.base, **(self.instances.get(name, {}) if name != "default" else {})}
        inst = Instance(name=name)
        for k, v in merged.items():
            if k == "data":
                inst.data = [DataDir(d["name"], d["path"], bool(d.get("ro", False))) for d in v]
            elif k in KEYS:
                setattr(inst, k, int(v) if k == "port" else v)
        return inst

    def set_gdl(self, **changes) -> None:
        """Change settings of gdl itself ([gdl]) and save."""
        for k, v in changes.items():
            if k not in GDL_KEYS:
                raise KeyError(k)
            self.gdl[k] = v
        self.save()

    def update(self, inst: Instance, **changes) -> Instance:
        """Apply changes to an instance and save. Named instances keep only
        the keys that differ from the default (and always their port)."""
        for k, v in changes.items():
            if k not in KEYS:
                raise KeyError(k)
            setattr(inst, k, v)
        self._store(inst)
        self.save()
        return inst

    def _store(self, inst: Instance) -> None:
        values = {k: _plain(getattr(inst, k)) for k in KEYS}
        if inst.name == "default":
            self.base = {k: v for k, v in values.items() if v not in ("", [], {})}
            return
        base = self._resolve("default")
        self.instances[inst.name] = {
            k: v for k, v in values.items()
            if k == "port" or v != _plain(getattr(base, k))
        }

    def new_instance(self, name: str, template: str = "", variant: str = "") -> Instance:
        """A new workbench, or a service made from `template` (image `variant`)."""
        if not INSTANCE_RE.match(name):
            raise GdlError("Instance names: lowercase letters, digits and '-'.")
        if self.exists and name in self.names():  # before the file exists, nothing is taken
            raise GdlError(f"Instance '{name}' already exists.")
        inst = self._resolve(name) if name != "default" else Instance()
        inst.name = name
        if template:
            from .templates import get as get_template
            t = get_template(template)
            if variant and variant not in t.images:
                raise GdlError(f"Template '{template}' has no image variant '{variant}'.")
            inst.kind, inst.template, inst.backend = "service", template, "container"
            inst.image = t.images[variant or next(iter(t.images))]
            inst.shm_size = t.shm_size
            inst.env = {**t.env, **{k: secrets.token_urlsafe(18) for k in t.secrets}}
            inst.port = self.free_port(exclude=name, start=t.port)
        else:  # a workbench, even if the default instance is a service
            inst.kind, inst.template, inst.image, inst.env = "workbench", "", "", {}
            if inst.backend not in BACKENDS:
                inst.backend = "container"
            inst.port = self.free_port(exclude=name)
        if name == "default":
            self.base = {}
        self._store(inst)
        self.save()
        return self.get(name)

    def remove_instance(self, name: str) -> None:
        """Forget an instance. Deleting 'default' first writes the values the
        other instances inherited from it into their own tables."""
        if name == "default":
            plain = Instance()
            for n in self.instances:
                inst = self._resolve(n)
                self.instances[n] = {k: _plain(getattr(inst, k)) for k in KEYS
                                     if k == "port" or _plain(getattr(inst, k)) != _plain(getattr(plain, k))}
            self.base = {}
        else:
            self.instances.pop(name, None)
        self.save()

    def free_port(self, exclude: str = "", start: int = 8888) -> int:
        used = {self.get(n).port for n in (self.names() if self.exists else []) if n != exclude}
        p = start
        while p in used or port_open(p):
            p += 1
        return p

    def save(self) -> None:
        doc = _nest(self.base)
        gdl = {k: v for k, v in self.gdl.items() if v != GDL_KEYS[k]}
        if gdl:
            doc["gdl"] = gdl
        if self.instances:
            doc["instance"] = {n: _nest(d) for n, d in sorted(self.instances.items())}
        header = "# geodatalab settings — edited by `pixi run gdl` or by hand. Not committed.\n"
        self.path.write_text(header + tomli_w.dumps(doc), encoding="utf-8")


def _plain(v):
    if isinstance(v, list):
        return [{"name": d.name, "path": d.path, **({"ro": True} if d.ro else {})} for d in v]
    return v


def _flat(d: dict) -> dict:
    """[limits] table -> top-level keys."""
    d = dict(d)
    d.update(d.pop("limits", {}))
    return d


def _nest(d: dict) -> dict:
    out = {k: v for k, v in d.items() if k not in LIMIT_KEYS and k != "data"}
    limits = {k: d[k] for k in LIMIT_KEYS if k in d}
    if limits:
        out["limits"] = limits
    if "data" in d:
        out["data"] = d["data"]
    return out


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def check_data_name(name: str, existing: list[DataDir]) -> None:
    if not DATA_RE.match(name) or name == "dirs":
        raise GdlError(f"Invalid data folder name '{name}': lowercase letters, digits, - and _.")
    if any(d.name == name for d in existing):
        raise GdlError(f"Data folder '{name}' already exists.")


# ── Where pixi puts environments (pixi's `detached-environments`) ──────────────

def pixi_env_location(project: Path = ROOT) -> str:
    """'' = inside the project (.pixi/envs), 'cache' = pixi's cache folder, else a folder."""
    cfg = project / PIXI_CONFIG
    try:
        v = tomllib.loads(cfg.read_text(encoding="utf-8")).get("detached-environments", False)
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    return "cache" if v is True else (v if isinstance(v, str) else "")


def write_pixi_env_location(value: str, project: Path = ROOT) -> None:
    """Set (or clear, for '') detached-environments in a project's .pixi/config.toml,
    keeping its other keys."""
    cfg = project / PIXI_CONFIG
    try:
        doc = tomllib.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        doc = {}
    if value:
        doc["detached-environments"] = True if value == "cache" else value
    else:
        doc.pop("detached-environments", None)
    if doc:
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(tomli_w.dumps(doc), encoding="utf-8")
    else:
        cfg.unlink(missing_ok=True)


def noexec(path: Path) -> bool:
    """True if programs can't run from `path` (a noexec mount). Linux only; False elsewhere."""
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        return bool(os.statvfs(path).f_flag & getattr(os, "ST_NOEXEC", 0))
    except (OSError, AttributeError):
        return False


# ── Legacy .geodatalab (sourced shell file) → geodatalab.toml ─────────────────

_LEGACY = {
    "BACKEND": "backend", "WORKSPACE": "workspace", "PROFILE": "profile",
    "GDL_MODE": "mode", "GDL_PORT": "port", "IMAGE_TAG": "image_tag",
    "GDL_OPEN": "open", "GDL_MEMORY": "memory", "GDL_MEMORY_RESERVE": "memory_reserve",
    "GDL_CPUS": "cpus",
}


def parse_legacy(text: str) -> dict:
    out: dict = {}
    for line in text.splitlines():
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            continue
        if not tokens or "=" not in tokens[0]:
            continue
        key, _, value = tokens[0].partition("=")
        if key == "GDL_DATA_DIRS":
            data = []
            for entry in tokens[1:]:
                if entry == ")" or "=" not in entry:
                    continue
                name, _, path = entry.partition("=")
                ro = path.endswith(":ro")
                data.append({"name": name, "path": path[:-3] if ro else path, **({"ro": True} if ro else {})})
            out["data"] = data
        elif key in _LEGACY:
            k = _LEGACY[key]
            if k == "port":
                value = int(value or 8888)
            elif k == "mode" and value == "server":
                value = "lab"  # JupyterLab 4: server IS lab
            elif k == "backend" and value == "mamba":
                value = "pixi"
            if value != "":
                out[k] = value
    return out


def migrate_legacy(root: Path = ROOT, target: Path | None = None) -> bool:
    """Convert .geodatalab + .geodatalab.d/* once; keep the originals as .bak."""
    target = target or settings_path()
    legacy, legacy_dir = root / ".geodatalab", root / ".geodatalab.d"
    if target.exists() or not (legacy.is_file() or legacy_dir.is_dir()):
        return False
    s = Settings(target)
    if legacy.is_file():
        s.base = parse_legacy(legacy.read_text(encoding="utf-8"))
    if legacy_dir.is_dir():
        for f in sorted(legacy_dir.iterdir()):
            if f.is_file() and INSTANCE_RE.match(f.name):
                s.instances[f.name] = parse_legacy(f.read_text(encoding="utf-8"))
    s.save()
    if legacy.is_file():
        legacy.rename(legacy.with_name(".geodatalab.bak"))
    if legacy_dir.is_dir():
        legacy_dir.rename(legacy_dir.with_name(".geodatalab.d.bak"))
    return True
