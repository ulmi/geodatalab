"""Recipes: an instance's environment as one plain-text TOML file — settings
without machine paths, plus the exact pixi manifest + lock of its env (or the
image reference for containers). The basis for snapshots and export/import.

An instance either uses the shared env of its profile (root pixi.toml/pixi.lock)
or owns an env project in .gdl/<instance>/env/ (pixi.toml + pixi.lock with one
environment, "default"). Owning one means restoring or importing a recipe never
changes the env of other instances on the same profile."""
from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import tomli_w

from .backends import Pixi, capture
from .config import ROOT, GdlError, Instance, pixi_env_location, write_pixi_env_location

VERSION = 1
ROOT_MANIFEST = ROOT / "pixi.toml"
ROOT_LOCK = ROOT / "pixi.lock"
# settings that travel (machine paths don't: workspace, data paths)
PORTABLE = ("backend", "profile", "mode", "open", "image_tag", "shm_size", "memory", "memory_reserve", "cpus")


@dataclass
class Recipe:
    name: str
    settings: dict
    data: list[dict] = field(default_factory=list)      # data folders: {name, ro}; paths are asked on import
    created: str = ""
    geodatalab: str = ""                                # git commit of the checkout it came from
    label: str = ""
    manifest: str = ""                                  # pixi.toml with one environment
    lock: str = ""                                      # its pixi.lock
    image: str = ""                                     # container: image reference

    def dumps(self) -> str:
        """TOML with the manifest and lock as literal multi-line strings (kept verbatim,
        readable, diffable), the short fields first."""
        body = {k: v for k, v in asdict(self).items() if v not in ("", [], {})}
        texts = {k: body.pop(k) for k in ("manifest", "lock") if k in body}
        settings = body.pop("settings", {})
        data = body.pop("data", [])
        out = ["# geodatalab recipe — the environment of one instance (no data).\n"
               "# Import it in the manager: n → From a recipe file.\n",
               tomli_w.dumps({"version": VERSION, **body}),
               f'data = [{", ".join(_inline(d) for d in data)}]\n' if data else "",
               f"settings = {_inline(settings)}\n\n"]
        for k, v in texts.items():
            if "'''" in v or not v.endswith("\n"):
                out.append(tomli_w.dumps({k: v}, multiline_strings=True))
            else:
                out.append(f"{k} = '''\n{v}'''\n")
        return "".join(out)

    def summary(self) -> str:
        s = self.settings
        parts = [f"{s.get('backend', '?')} · profile {s.get('profile', '?')}"]
        if self.created:
            parts.append(self.created.replace("T", " ")[:16])
        if self.geodatalab:
            parts.append(f"geodatalab {self.geodatalab}")
        if self.label:
            parts.append(f"“{self.label}”")
        return " · ".join(parts)

    @classmethod
    def loads(cls, text: str) -> Recipe:
        try:
            d = tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            raise GdlError(f"Not a geodatalab recipe: {e}") from None
        if d.pop("version", None) != VERSION:
            raise GdlError("Not a geodatalab recipe (or one from a newer geodatalab).")
        try:
            return cls(**d)
        except TypeError as e:
            raise GdlError(f"Not a geodatalab recipe: {e}") from None

    def save(self, path: Path) -> None:
        path.write_text(self.dumps(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Recipe:
        return cls.loads(path.read_text(encoding="utf-8"))


def _inline(d: dict) -> str:
    return "{ " + ", ".join(tomli_w.dumps({k: v}).strip() for k, v in d.items()) + " }"


# ── env projects ───────────────────────────────────────────────────────────────

env_project = Pixi.own_project


def owns_env(inst: Instance) -> bool:
    return (env_project(inst) / "pixi.toml").exists()


def write_env_project(inst: Instance, manifest: str, lock: str) -> Path:
    """Give `inst` its own env project (replacing any previous one). Build installs it."""
    d = env_project(inst)
    d.mkdir(parents=True, exist_ok=True)
    (d / "pixi.toml").write_text(manifest, encoding="utf-8")
    (d / "pixi.lock").write_text(lock, encoding="utf-8")
    (d / "profile").write_text(inst.profile + "\n")  # a later profile change returns to the shared env
    write_pixi_env_location(pixi_env_location(ROOT), d)  # nested projects don't inherit the checkout's
    Pixi._prefixes.pop(str(d / "pixi.toml"), None)
    return d


# ── one environment out of the shared root project ─────────────────────────────

def env_manifest(env: str, name: str, root: dict | None = None) -> str:
    """A standalone pixi.toml whose default environment equals `env` of the root manifest."""
    root = root or tomllib.loads(ROOT_MANIFEST.read_text(encoding="utf-8"))
    if env not in root.get("environments", {}):
        raise GdlError(f"No pixi environment '{env}' in pixi.toml.")
    ws = root["workspace"]
    features = root["environments"][env]["features"]
    deps = dict(root.get("dependencies", {}))
    pypi = dict(root.get("pypi-dependencies", {}))
    platforms = ws["platforms"]
    for f in features:
        feat = root.get("feature", {}).get(f, {})
        deps.update(feat.get("dependencies", {}))
        pypi.update(feat.get("pypi-dependencies", {}))
        platforms = feat.get("platforms", platforms)
    doc = {"workspace": {"name": name, "channels": ws["channels"], "platforms": platforms},
           "dependencies": deps}
    if pypi:
        doc["pypi-dependencies"] = pypi
    return (f"# geodatalab env of instance '{name}' (from profile env '{env}').\n"
            "# Managed by the geodatalab manager; edit with care.\n" + tomli_w.dumps(doc))


def _blocks(lines: list[str], start: int, end: int, opener) -> list[list[str]]:
    """Split lines[start:end] into blocks, each starting at a line where opener(line)."""
    out: list[list[str]] = []
    for line in lines[start:end]:
        if opener(line) or not out:
            out.append([])
        out[-1].append(line)
    return out


def extract_lock(text: str, env: str) -> str:
    """The part of a pixi.lock (v6/v7 layout) that `env` needs, renamed to 'default'.
    Text-level, so pixi's own formatting is kept byte for byte."""
    lines = text.splitlines(keepends=True)
    try:
        i_env = lines.index("environments:\n")
        i_pkg = lines.index("packages:\n")
    except ValueError:
        raise GdlError("pixi.lock has an unexpected layout.") from None
    envs = _blocks(lines, i_env + 1, i_pkg, lambda l: l.startswith("  ") and not l.startswith("   "))
    block = next((b for b in envs if b[0] == f"  {env}:\n"), None)
    if not block:
        raise GdlError(f"pixi.lock has no environment '{env}'. Run Lock first.")
    used = {l.strip()[2:] for l in block if l.lstrip().startswith(("- conda: ", "- pypi: "))}
    plats = {l.strip()[:-1] for l in block if l.startswith("      ") and not l.startswith("       ")
             and l.rstrip().endswith(":")}
    # header: keep only the platforms this env is locked for
    head = lines[:i_env]
    try:
        i_plat = head.index("platforms:\n")
    except ValueError:
        i_plat = -1
    if i_plat >= 0:
        end = next((k for k in range(i_plat + 1, len(head)) if not head[k].startswith(("-", " "))), len(head))
        kept = [b for b in _blocks(head, i_plat + 1, end, lambda l: l.startswith("- "))
                if b[0].removeprefix("- name: ").strip() in plats]
        head = head[:i_plat + 1] + [l for b in kept for l in b] + head[end:]
    pkgs = [b for b in _blocks(lines, i_pkg + 1, len(lines), lambda l: l.startswith("- "))
            if b[0][2:].strip() in used]
    return "".join(head + ["environments:\n", "  default:\n", *block[1:], "packages:\n",
                           *(l for b in pkgs for l in b)])


def capture_env(inst: Instance) -> tuple[str, str]:
    """(manifest, lock) of the env `inst` runs on — its own project, or its
    profile's env extracted from the shared root project."""
    if owns_env(inst):
        d = env_project(inst)
        return (d / "pixi.toml").read_text(encoding="utf-8"), (d / "pixi.lock").read_text(encoding="utf-8")
    if not ROOT_LOCK.exists():
        raise GdlError("No pixi.lock yet. Run Lock or Build first.")
    return (env_manifest(inst.env_name, inst.name),
            extract_lock(ROOT_LOCK.read_text(encoding="utf-8"), inst.env_name))


def capture_recipe(inst: Instance, label: str = "") -> Recipe:
    if inst.is_service:
        raise GdlError("Services have no environment to capture (their image is in the settings).")
    r = Recipe(name=inst.name, settings={k: getattr(inst, k) for k in PORTABLE if getattr(inst, k) != ""},
               data=[{"name": d.name, "ro": d.ro} for d in inst.data], created=datetime.now().isoformat(timespec="seconds"),
               geodatalab=capture(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"]), label=label)
    if inst.backend == "pixi":
        r.manifest, r.lock = capture_env(inst)
    else:
        from .render import image
        r.image = image(inst)
    return r


# ── export / import ────────────────────────────────────────────────────────────

def export_recipe(inst: Instance, path: Path, label: str = "") -> Path:
    path = path.expanduser()
    if path.is_dir():
        path = path / f"{inst.name}.gdlenv.toml"
    capture_recipe(inst, label).save(path)
    return path


def import_recipe(settings, recipe: Recipe, name: str, workspace: str,
                  data_paths: dict[str, str] | None = None) -> Instance:
    """Create instance `name` from `recipe`. Data folders get the paths given
    (a folder without a path is skipped). pixi: the instance gets its own env
    project with the recipe's exact lock — Build installs it."""
    from .config import BACKENDS, KEYS, PROFILES, DataDir
    s = {k: v for k, v in recipe.settings.items() if k in KEYS}
    if s.get("backend") not in BACKENDS or s.get("profile") not in PROFILES:
        raise GdlError(f"Recipe has an unknown backend/profile: {s.get('backend')}/{s.get('profile')}.")
    if s["backend"] == "pixi" and not (recipe.manifest and recipe.lock):
        raise GdlError("This pixi recipe has no manifest/lock.")
    paths = data_paths or {}
    data = [DataDir(d["name"], str(Path(paths[d["name"]]).expanduser()), bool(d.get("ro")))
            for d in recipe.data if paths.get(d["name"], "").strip()]
    inst = settings.new_instance(name)
    inst = settings.update(inst, **s, workspace=str(Path(workspace).expanduser()), data=data)
    if s["backend"] == "pixi":
        write_env_project(inst, recipe.manifest, recipe.lock)
    return inst
