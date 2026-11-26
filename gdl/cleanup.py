"""Disk space: what deleting an instance removes, and what the cleaner can free
without touching anything an instance needs. Workspace and data folders are
never touched. Sizes are best effort (None = unknown)."""
from __future__ import annotations

import json
import os
from datetime import datetime
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .backends import Container, Out, Pixi, backend_for, capture, detect_runtime, run
from . import config
from .config import GdlError, Instance, Settings
from .monitor import parse_size
from .render import image, remove_state


@dataclass
class Item:
    label: str
    detail: str
    size: int | None
    action: Callable[[Out], None]
    default: bool = True          # checked by default in the cleaner
    warn: bool = False            # removes data that can't be rebuilt
    approx: bool = False          # size is an upper bound (shared/reflinked files)


def du(path: Path, unique: bool = False) -> int:
    """Bytes on disk under path (symlinks not followed). unique=True counts only
    files with a single hard link, i.e. what deleting them actually frees."""
    total = 0
    for dirpath, _, files in os.walk(path):
        for f in files:
            try:
                st = os.lstat(os.path.join(dirpath, f))
            except OSError:
                continue
            if unique and st.st_nlink > 1:
                continue
            total += getattr(st, "st_blocks", 0) * 512 or st.st_size
    return total


def _runtime() -> str | None:
    try:
        return detect_runtime()[0]
    except GdlError:
        return None


def _image_size(rt: str, ref: str) -> int | None:
    try:
        return int(capture([rt, "image", "inspect", "--format", "{{.Size}}", ref]).strip())
    except (ValueError, GdlError):
        return None


def _workbenches(settings: Settings, backend: str, skip: str = "") -> list[Instance]:
    return [i for n in settings.names() if n != skip
            for i in [settings.get(n)] if not i.is_service and i.backend == backend]


# ── deleting an instance ───────────────────────────────────────────────────────

def instance_files(settings: Settings, inst: Instance) -> tuple[list[Item], list[str]]:
    """(what deleting `inst` removes besides its settings, what is kept because
    another instance shares it)."""
    items, kept = [], []
    items.append(Item("Generated state", f"{inst.state_dir} (logs, links, compose files)",
                      du(inst.state_dir) if inst.state_dir.exists() else 0, lambda out: None))
    be = backend_for(settings, inst)
    if inst.backend == "container" and not _runtime():
        pass  # no Podman/Docker here: there is no container, image or volume to remove
    elif inst.is_service:
        vol = f"{inst.container_name}-data"
        items.append(Item("Container and data volume", f"{vol} — all data stored in this service",
                          None, lambda out: be.clean(out), warn=True))
    elif inst.backend == "container":
        rt, ref = _runtime(), image(inst)
        users = [i.name for i in _workbenches(settings, "container", inst.name) if image(i) == ref]
        if users:
            kept.append(f"image {ref} (used by {', '.join(users)})")
            items.append(Item("Container", inst.container_name, None, lambda out: be.clean(out)))
        else:
            items.append(Item("Container and image", ref, rt and _image_size(rt, ref),
                              lambda out: (be.clean(out), rt and run([rt, "rmi", "--force", ref], out))))
    elif be.owns_env():
        if be.installed():
            items.append(Item("Own pixi env", str(be.prefix()), du(be.prefix(), unique=True),
                              lambda out: None, approx=True))  # lives in the state dir, goes with it
    else:
        users = [i.name for i in _workbenches(settings, "pixi", inst.name)
                 if i.env_name == inst.env_name and not Pixi(settings, i).owns_env()]
        if users:
            kept.append(f"pixi env {inst.env_name} (used by {', '.join(users)})")
        elif be.installed():
            items.append(Item(f"pixi env {inst.env_name}", str(be.prefix()), du(be.prefix(), unique=True),
                              lambda out: be.clean(out), approx=True))
    return items, kept


def delete_instance(settings: Settings, name: str, out: Out, keep_files: bool = False) -> None:
    inst = settings.get(name)
    be = backend_for(settings, inst)
    if be.is_running():
        raise GdlError(f"'{name}' is running. Stop it first.")
    if keep_files:
        if inst.backend == "container":  # the container itself always goes; images/volumes stay
            try:
                argv, env = be.compose("down")
                subprocess.run(argv, env=env, capture_output=True)
            except GdlError:
                pass
    else:
        for item in instance_files(settings, inst)[0]:
            try:
                item.action(out)
            except GdlError as e:  # e.g. a container of another checkout: report, still forget the instance
                out(f"Could not remove {item.label}: {e}")
    if not keep_files:
        remove_state(inst)
    elif inst.state_dir.exists():  # out of the way of a new instance with this name; Free space lists it
        inst.state_dir.rename(inst.state_dir.with_name(f"{name}.deleted-{datetime.now():%Y%m%d-%H%M%S}"))
    settings.remove_instance(name)


# ── the cleaner ────────────────────────────────────────────────────────────────

def reclaimable(settings: Settings) -> list[Item]:
    items: list[Item] = []
    names = settings.names() if settings.exists else []
    insts = [settings.get(n) for n in names]

    # pixi download cache (hard links: envs keep their files, so only unshared bytes count)
    try:
        info = json.loads(subprocess.run([Pixi.exe(), "info", "--json"], capture_output=True, text=True,
                                         env=Pixi.clean_env(), timeout=30).stdout)
        cache = Path(info["cache_dir"])
        size = sum(du(cache / d, unique=True) for d in ("pkgs", "repodata", "uv-cache") if (cache / d).exists())
        if size:
            items.append(Item("pixi download cache", f"{cache} · shared by all pixi projects; installed "
                              "envs keep working, builds re-download what they need", size,
                              lambda out: run([Pixi.exe(), "clean", "cache", "--conda", "--pypi",
                                               "--repodata", "--yes"], out, env=Pixi.clean_env()),
                              approx=True))
    except (OSError, ValueError, KeyError, GdlError, subprocess.SubprocessError):
        pass

    # pixi envs no instance uses (the manager's own 'default' env always stays)
    used = {i.env_name for i in insts if not i.is_service and i.backend == "pixi"
            and not Pixi(settings, i).owns_env()}
    envs_dir = Pixi.MANIFEST.parent / ".pixi" / "envs"
    for env in sorted(p.name for p in envs_dir.iterdir()) if envs_dir.is_dir() else []:
        if env != "default" and env not in used:
            items.append(Item(f"Unused pixi env {env}", f"{envs_dir / env} · no instance uses it; "
                              "Build recreates it", du(envs_dir / env, unique=True),
                              lambda out, env=env: run([Pixi.exe(), "clean", "--manifest-path",
                                                        str(Pixi.MANIFEST), "-e", env], out,
                                                       env=Pixi.clean_env()), default=False, approx=True))

    # generated state of instances that no longer exist (e.g. deleted before this cleaner)
    state_root = config.STATE_ROOT  # looked up at call time (tests patch it)
    uv = state_root / "uv-cache"
    if uv.is_dir() and (size := du(uv)):
        items.append(Item("uv cache of container locks", f"{uv} · Lock re-downloads what it needs", size,
                          lambda out: shutil.rmtree(uv, ignore_errors=True)))
    for d in sorted(state_root.iterdir()) if state_root.is_dir() else []:
        name = d.name
        if d.is_dir() and name not in names and name != "uv-cache":
            label = name.partition(".deleted-")[0]
            items.append(Item(f"Leftover files of deleted instance '{label}'", str(d), du(d),
                              lambda out, name=name: remove_state(Instance(name=name))))

    # big Jupyter logs of stopped pixi instances
    for i in insts:
        log = i.state_dir / "jupyter.log"
        if log.exists() and log.stat().st_size > 1 << 20 and not backend_for(settings, i).is_running():
            items.append(Item(f"Jupyter log of '{i.name}'", str(log), log.stat().st_size,
                              lambda out, log=log: log.write_text("")))

    rt = _runtime()
    if rt:
        used_imgs = {image(i) for i in insts if i.backend == "container" or i.is_service}
        for line in capture([rt, "images", "--filter", "reference=geodatalab",
                             "--format", "{{.Repository}}:{{.Tag}}|{{.Size}}"]).splitlines():
            ref, _, size = line.partition("|")
            ref = ref.removeprefix("localhost/")
            if ref and ref not in used_imgs and not ref.endswith(":<none>"):
                items.append(Item(f"Unused image {ref}", "no instance uses this tag; Build recreates it",
                                  parse_size(size) or None,
                                  lambda out, ref=ref: run([rt, "rmi", ref], out), default=False))
        dangling = sum(parse_size(s) for s in capture(
            [rt, "images", "--filter", "dangling=true", "--format", "{{.Size}}"]).split("\n") if s)
        if dangling:
            def prune(out):
                run([rt, "image", "prune", "-f"], out)
                if rt == "docker":
                    run([rt, "builder", "prune", "-f"], out)
            items.append(Item("Dangling images and build cache", "untagged layers left by earlier builds",
                              dangling, prune))
        services = {f"{i.container_name}-data" for i in insts if i.is_service}
        for vol in capture([rt, "volume", "ls", "--format", "{{.Name}}"]).split():
            if vol.startswith("geodatalab") and vol.endswith("-data") and vol not in services:
                items.append(Item(f"Leftover data volume {vol}", "from a deleted service — its data is lost",
                                  None, lambda out, vol=vol: run([rt, "volume", "rm", vol], out),
                                  default=False, warn=True))
    return items
