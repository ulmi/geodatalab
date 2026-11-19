"""Backends: what start/stop/build/... mean for the container and pixi backends.

Every long operation takes `out`, a callable that receives output lines, so the
same code prints to the terminal (CLI) or streams into the TUI log panel.
User-facing failures raise GdlError. Backends never prompt; callers confirm.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import os
import platform
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import date
from pathlib import Path
from typing import Callable

from .config import GDL_PYTHON, PROFILES, ROOT, STATE_ROOT, GdlError, Instance, Settings, port_open
from .render import build_root, gdl_env, image, write_fragment

Out = Callable[[str], None]
WIN = sys.platform == "win32"


# ── Process helpers ────────────────────────────────────────────────────────────

def run(argv: list[str], out: Out, env: dict | None = None, cwd: Path = ROOT) -> None:
    """Run a command, streaming its output lines to `out`. Raise on failure."""
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                errors="replace", env=env, cwd=cwd, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise GdlError(f"Command not found: {argv[0]}") from None
    for line in proc.stdout:
        out(line.rstrip("\n"))
    if proc.wait():
        raise GdlError(f"`{' '.join(argv[:3])} ...` failed (exit {proc.returncode})")


def capture(argv: list[str], env: dict | None = None) -> str:
    """stdout of a command, or '' if it fails or is missing."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, errors="replace", env=env, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def spawn_detached(argv: list[str], env: dict, cwd: Path, log: Path) -> int:
    with open(log, "wb") as f:
        kw = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
              if WIN else {"start_new_session": True})
        return subprocess.Popen(argv, env=env, cwd=cwd, stdout=f, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, **kw).pid


def alive(pid: int) -> bool:
    if WIN:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    try:
        if os.waitpid(pid, os.WNOHANG)[0] == pid:  # our own child that exited: reap it
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def kill_tree(pid: int) -> None:
    if WIN:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        return
    for sig, wait in ((signal.SIGTERM, 10.0), (signal.SIGKILL, 2.0)):
        try:
            os.killpg(pid, sig)  # started with start_new_session: pgid == pid
        except ProcessLookupError:
            return
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if not alive(pid):
                return
            time.sleep(0.25)


def follow_file(path: Path, out: Out, stop: threading.Event, lines: int = 50) -> None:
    if not path.exists():
        out("No log yet.")
        return
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f.readlines()[-lines:]:
            out(line.rstrip("\n"))
        while not stop.is_set():
            line = f.readline()
            if line:
                out(line.rstrip("\n"))
            else:
                time.sleep(0.5)


def ensure_workspace(inst: Instance, out: Out) -> None:
    if not inst.workspace:
        raise GdlError("No workspace set. Set it in the TUI (Settings) or in geodatalab.toml.")
    ws = Path(inst.workspace)
    if not ws.is_dir():
        ws.mkdir(parents=True)
        out(f"Created workspace: {ws}")


# ── Base ───────────────────────────────────────────────────────────────────────

class Backend:
    def __init__(self, settings: Settings, inst: Instance):
        self.settings, self.inst = settings, inst

    def label(self) -> str: ...
    def is_running(self) -> bool: ...
    def health(self) -> str: ...
    def start(self, out: Out) -> None: ...
    def stop(self, out: Out) -> None: ...
    def build(self, out: Out, profile: str | None = None, no_cache: bool = False) -> None: ...
    def lock(self, out: Out, profiles: list[str]) -> None: ...
    def logs(self, out: Out, stop: threading.Event) -> None: ...
    def shell(self) -> tuple[list[str], dict | None, Path]: ...
    def token(self) -> str: ...
    def status(self) -> list[str]: ...
    def clean(self, out: Out, images: bool = False) -> None: ...

    def update(self, out: Out) -> None:
        was = self.is_running()
        if was:
            self.stop(out)
        self.lock(out, [self.inst.profile])
        self.build(out, no_cache=True)
        if was:
            self.start(out)

    def url(self) -> str:
        token = os.environ["JUPYTER_TOKEN"] if "JUPYTER_TOKEN" in os.environ else self.token()
        base = f"http://localhost:{self.inst.port}/lab"
        return f"{base}?token={token}" if token else base

    def restart(self, out: Out) -> None:
        if self.is_running():
            self.stop(out)
        self.start(out)


# ── Container (Podman preferred, Docker fallback) ──────────────────────────────

_RUNTIME: tuple[str, list[str]] | None = None


def detect_runtime() -> tuple[str, list[str]]:
    global _RUNTIME
    if _RUNTIME:
        return _RUNTIME
    for rt in ("podman", "docker"):
        if not shutil.which(rt):
            continue
        if capture([rt, "compose", "version"]):
            _RUNTIME = (rt, [rt, "compose"])
        elif shutil.which(f"{rt}-compose"):
            _RUNTIME = (rt, [f"{rt}-compose"])
        else:
            raise GdlError(f"{rt} found but no compose. Install {rt}-compose or the compose plugin.")
        return _RUNTIME
    raise GdlError("No container runtime found. Install Podman or Docker, or use the pixi backend.")


class Container(Backend):
    LABEL = "io.geodatalab.checkout"

    @property
    def rt(self) -> str:
        return detect_runtime()[0]

    def compose(self, *args: str, inst: Instance | None = None) -> tuple[list[str], dict]:
        inst = inst or self.inst
        frag = write_fragment(inst)
        env = {**os.environ, "PROFILE": inst.profile, "GDL_TAG": inst.image_tag or "latest",
               "GDL_PORT": str(inst.port), "GDL_MODE": inst.mode}
        argv = [*detect_runtime()[1], "-p", inst.container_name,
                "-f", str(ROOT / "compose.yml"), "-f", str(frag), *args]
        return argv, env

    def _run_compose(self, out: Out, *args: str, inst: Instance | None = None) -> None:
        argv, env = self.compose(*args, inst=inst)
        run(argv, out, env=env)

    def _inspect(self, fmt: str, *opts: str) -> str:
        return capture([self.rt, "inspect", *opts, "-f", fmt, self.inst.container_name])

    def _owner(self) -> str | None:
        """Checkout that created the container; None if no container exists."""
        if not capture([self.rt, "inspect", "-f", "{{.Id}}", self.inst.container_name]):
            return None
        return self._inspect(f'{{{{index .Config.Labels "{self.LABEL}"}}}}').replace("<no value>", "")

    def _guard_foreign(self) -> None:
        owner = self._owner()
        if owner is not None and owner != str(ROOT):
            raise GdlError(f"A container named '{self.inst.container_name}' already exists and belongs to "
                           f"{owner or 'another (older) geodatalab checkout'}. Use a separate instance here.")

    def label(self) -> str:
        return image(self.inst)

    def is_running(self) -> bool:
        try:
            return self._inspect("{{.State.Running}}") == "true" and self._owner() == str(ROOT)
        except GdlError:
            return False

    def health(self) -> str:
        return self._inspect("{{.State.Health.Status}}") if self.is_running() else ""

    def build(self, out, profile=None, no_cache=False):
        profile = profile or self.inst.profile
        tag = f"{date.today():%Y.%m}-{profile}"
        if not (ROOT / "requirements" / "locks" / f"{profile}.lock").exists():
            out(f"No lock file for '{profile}' — the build resolves the latest versions.")
        out(f"Building geodatalab:{tag} ...")
        target = dataclasses.replace(self.inst, profile=profile, image_tag=tag)
        self._run_compose(out, "build", *(["--no-cache"] if no_cache else []), inst=target)
        if subprocess.run([self.rt, "tag", f"geodatalab:{tag}", "geodatalab:latest"],
                          capture_output=True).returncode == 0:
            out("Tagged as geodatalab:latest")
        self.settings.update(self.inst, profile=profile, image_tag=tag)
        out(f"Build complete: geodatalab:{tag}")

    def lock(self, out, profiles):
        m = platform.machine().lower()  # x86_64 / aarch64 / arm64 (macOS) / amd64 (Windows)
        plat = f"{ {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(m, m)}-manylinux_2_28"
        (ROOT / "requirements" / "locks").mkdir(parents=True, exist_ok=True)
        for p in profiles:
            out(f"Locking {p} [python {GDL_PYTHON}, {plat}] ...")
            args = ["pip", "compile", "--quiet", f"requirements/{p}.txt", "requirements/build.txt",
                    "--python-version", GDL_PYTHON, "--python-platform", plat,
                    "--custom-compile-command", f"pixi run lock {p}", "-o", f"requirements/locks/{p}.lock"]
            if shutil.which("uv"):
                run(["uv", *args], out)
            else:  # official uv image: nothing to install on the host
                user = ["--user", f"{os.getuid()}:{os.getgid()}"] if self.rt == "docker" and not WIN else []
                (STATE_ROOT / "uv-cache").mkdir(parents=True, exist_ok=True)
                run([self.rt, "run", "--rm", *user, "-v", f"{ROOT}:/src", "--security-opt", "label=disable",
                     "-w", "/src", "-e", "UV_CACHE_DIR=/src/.gdl/uv-cache",
                     f"ghcr.io/astral-sh/uv:python{GDL_PYTHON}-trixie-slim", "uv", *args], out)
            out(f"Wrote requirements/locks/{p}.lock — rebuild to apply.")

    def start(self, out):
        ensure_workspace(self.inst, out)
        if self.is_running():
            out("Already running.")
            return
        self._guard_foreign()
        missing = [d for d in self.inst.data if not Path(d.path).is_dir()]
        if missing:
            raise GdlError("Data folder(s) missing: " + ", ".join(f"{d.name} ({d.path})" for d in missing))
        img = image(self.inst)
        if not capture([self.rt, "image", "inspect", "-f", "{{.Id}}", img]):
            if self.inst.image_tag and capture([self.rt, "image", "inspect", "-f", "{{.Id}}", "geodatalab:latest"]):
                out(f"Image {img} not found — using geodatalab:latest")
                self.inst = dataclasses.replace(self.inst, image_tag="")
            else:
                raise GdlError(f"Image not found: {img}. Build it first.")
        out(f"Starting [{image(self.inst)}, mode {self.inst.mode}, port {self.inst.port}] ...")
        self._run_compose(out, "up", "-d")
        self._wait(out)

    def _wait(self, out):
        for _ in range(30):
            h = self.health() if self.inst.mode != "idle" else ("healthy" if self.is_running() else "")
            if h == "healthy":
                out("Ready.")
                return
            if h == "unhealthy":
                raise GdlError("Container is unhealthy — check the logs.")
            time.sleep(2)
        out("Still starting — check the logs.")

    def stop(self, out):
        self._guard_foreign()
        self._run_compose(out, "stop")
        out("Stopped.")

    def logs(self, out, stop):
        proc = subprocess.Popen([self.rt, "logs", "-f", "--tail", "200", self.inst.container_name],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        threading.Thread(target=lambda: (stop.wait(), proc.terminate()), daemon=True).start()
        for line in proc.stdout:
            out(line.rstrip("\n"))
        proc.wait()

    def shell(self):
        if not self.is_running():
            raise GdlError("Not running. Start it first.")
        return [self.rt, "exec", "-it", self.inst.container_name, "bash"], None, ROOT

    def token(self):
        if not self.is_running():
            return ""
        logs = subprocess.run([self.rt, "logs", self.inst.container_name], capture_output=True,
                              text=True, errors="replace")
        found = re.findall(r"token=([a-f0-9]+)", logs.stdout + logs.stderr)
        return found[-1] if found else ""

    def images(self) -> list[str]:
        return capture([self.rt, "images", "--filter", "reference=geodatalab",
                        "--format", "{{.Tag}}  {{.Size}}  ({{.CreatedSince}})"]).splitlines()

    def status(self):
        rt, comp = detect_runtime()
        lines = [f"Runtime:  {rt} ({' '.join(comp)})", f"Image:    {image(self.inst)}"]
        if self.is_running():
            lines.append(f"Started:  {self._inspect('{{.State.StartedAt}}')}")
        return lines + ["Images:", *(f"  {i}" for i in self.images() or ["none built yet"])]

    def clean(self, out, images=False):
        self._guard_foreign()
        argv, env = self.compose("down", "--volumes")
        subprocess.run(argv, env=env, capture_output=True)
        out("Container removed.")
        if images:
            ids = sorted(set(capture([self.rt, "images", "--filter", "reference=geodatalab",
                                      "--format", "{{.ID}}"]).split()))
            if ids:
                run([self.rt, "rmi", "--force", *ids], out)
            self.settings.update(self.inst, image_tag="")
            out("Images removed.")


# ── pixi (conda-forge env, Jupyter as a host process) ──────────────────────────

class Pixi(Backend):
    MANIFEST = ROOT / "pixi.toml"
    LOCK = ROOT / "pixi.lock"

    @staticmethod
    def exe() -> str:
        exe = os.environ.get("PIXI_EXE") or shutil.which("pixi")
        if not exe:
            raise GdlError("pixi not found — install it from https://pixi.sh")
        return exe

    def px(self, sub: str, *args: str) -> list[str]:
        return [self.exe(), sub, "--manifest-path", str(self.MANIFEST), *args]

    @staticmethod
    def clean_env(extra: dict | None = None) -> dict:
        """Our environment minus the manager env's activation, so pixi
        activates the target environment cleanly."""
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PIXI_", "CONDA_"))}
        return {**env, **(extra or {})}

    def prefix(self, inst: Instance | None = None) -> Path:
        return ROOT / ".pixi" / "envs" / (inst or self.inst).env_name

    def installed(self) -> bool:
        p = self.prefix()
        return (p / "python.exe").exists() if WIN else (p / "bin" / "python").exists()

    def _f(self, name: str) -> Path:
        return self.inst.state_dir / name

    def _pid(self) -> int | None:
        try:
            return int(self._f("jupyter.pid").read_text())
        except (OSError, ValueError):
            return None

    def label(self):
        return f"pixi:{self.inst.env_name}"

    def is_running(self):
        pid = self._pid()
        return bool(pid and alive(pid))

    def health(self):
        if not self.is_running():
            return ""
        return "healthy" if port_open(self.inst.port) else "starting"

    def _guard_env(self, profile: str) -> None:
        """Refuse to modify an env that another instance's Jupyter runs from."""
        env = dataclasses.replace(self.inst, profile=profile).env_name
        for n in self.settings.names():
            other = self.settings.get(n)
            if other.backend == "pixi" and other.env_name == env and Pixi(self.settings, other).is_running():
                raise GdlError(f"Instance '{n}' is running from the '{env}' environment. Stop it first.")

    def _gen(self):
        spec = importlib.util.spec_from_file_location("gen_pixi", ROOT / "envs" / "pixi" / "gen_pixi.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def lock(self, out, profiles):
        self._gen().main([])
        if len(profiles) >= len(PROFILES) or not self.LOCK.exists():
            out("Solving all environments → pixi.lock ...")
            run(self.px("lock"), out, env=self.clean_env())
        else:
            envs = [a for p in profiles for a in ("-e", dataclasses.replace(self.inst, profile=p).env_name)]
            out(f"Updating {', '.join(profiles)} in pixi.lock ...")
            run(self.px("update", *envs), out, env=self.clean_env())
        out("Wrote pixi.lock")

    def build(self, out, profile=None, no_cache=False):
        profile = profile or self.inst.profile
        self._guard_env(profile)
        if profile in ("lab", "institute"):
            out("Note: SAGA GIS is not on conda-forge — use the container backend for SAGA.")
        if self._gen().main(["--check"]) or not self.LOCK.exists():
            out("pixi.toml is out of date with requirements/ — regenerating and re-locking.")
            self.lock(out, [profile])
        target = dataclasses.replace(self.inst, profile=profile)
        out(f"Installing environment '{target.env_name}' from pixi.lock ...")
        run(self.px("install", "--locked", "-e", target.env_name), out, env=self.clean_env())
        self._post_install(out, target)
        self.settings.update(self.inst, profile=profile)
        out(f"Environment ready: {self.prefix(target)}")

    def _in_env(self, inst: Instance, *cmd: str) -> list[str]:
        return self.px("run", "--frozen", "-e", inst.env_name, *cmd)

    def _post_install(self, out, inst):
        bridge = ("import pathlib, shutil, subprocess, sys, sysconfig\n"
                  "g = shutil.which('grass')\n"
                  "p = g and subprocess.run([g, '--config', 'python_path'], capture_output=True, text=True).stdout.strip()\n"
                  "if p:\n"
                  "    (pathlib.Path(sysconfig.get_paths()['purelib']) / 'gis-bridge.pth').write_text(p + '\\n')\n"
                  "    sys.path.append(p); import grass.script; print('GRASS Python API bridged:', p)\n")
        env = self.clean_env()
        run(self._in_env(inst, "python", "-c", bridge), out, env=env)
        if inst.profile in ("institute", "r+julia"):
            out("Installing IJulia ...")
            try:
                run(self._in_env(inst, "julia", "-e", "using Pkg; Pkg.add(\"IJulia\"); using IJulia"), out, env=env)
            except GdlError:
                out("IJulia install failed — Julia kernel unavailable.")
        try:
            run(self._in_env(inst, "python", "-m", "pip", "check"), out, env=env)
        except GdlError:
            out("pip check reported problems (see above).")

    def start(self, out):
        ensure_workspace(self.inst, out)
        if self.is_running():
            out("Already running.")
            return
        if not self.installed():
            raise GdlError(f"No pixi environment for profile '{self.inst.profile}'. Build it first.")
        if self.inst.mode == "idle":
            out("Mode is 'idle' — nothing to start on the pixi backend. Use the shell.")
            return
        if port_open(self.inst.port):
            raise GdlError(f"Port {self.inst.port} is already in use. Pick another port in Settings.")
        root, warnings = build_root(self.inst)
        for w in warnings:
            out(w)
        if "JUPYTER_TOKEN" in os.environ:
            token = os.environ["JUPYTER_TOKEN"]
        else:
            tf = self._f("token")
            if not tf.exists() or not tf.read_text().strip():
                tf.write_text(secrets.token_hex(24))
                if not WIN:
                    tf.chmod(0o600)
            token = tf.read_text().strip()
        args = ["jupyter", "lab", "--no-browser", f"--ip={os.environ.get('GDL_BIND', '127.0.0.1')}",
                f"--port={self.inst.port}", f"--ServerApp.root_dir={root}", f"--IdentityProvider.token={token}"]
        if self.inst.open and (root / self.inst.open).is_dir():
            args.append(f"--ContentsManager.preferred_dir={self.inst.open}")
        out(f"Starting [instance {self.inst.name}, env {self.inst.env_name}, port {self.inst.port}] ...")
        env = self.clean_env(gdl_env(self.inst, str(root)))
        pid = spawn_detached(self._in_env(self.inst, *args), env, root / "workspace", self._f("jupyter.log"))
        self._f("jupyter.pid").write_text(str(pid))
        for _ in range(120):
            if not alive(pid):
                tail = self._f("jupyter.log").read_text(errors="replace").splitlines()[-20:]
                raise GdlError("Jupyter exited:\n" + "\n".join(tail))
            if port_open(self.inst.port):
                out("Ready.")
                return
            time.sleep(0.5)
        out("Still starting — check the logs.")

    def stop(self, out):
        pid = self._pid()
        if pid and alive(pid):
            out(f"Stopping Jupyter (pid {pid}) ...")
            kill_tree(pid)
        self._f("jupyter.pid").unlink(missing_ok=True)
        out("Stopped.")

    def logs(self, out, stop):
        follow_file(self._f("jupyter.log"), out, stop)

    def shell(self):
        if not self.installed():
            raise GdlError("Environment not installed. Build it first.")
        ensure_workspace(self.inst, lambda _: None)
        root, _ = build_root(self.inst)
        return (self.px("shell", "--frozen", "-e", self.inst.env_name),
                self.clean_env(gdl_env(self.inst, str(root))), root / "workspace")

    def token(self):
        tf = self._f("token")
        return tf.read_text().strip() if self.is_running() and tf.exists() else ""

    def status(self):
        lines = [f"Env:      {self.inst.env_name}  "
                 + (str(self.prefix()) if self.installed() else "(not installed — build it)"),
                 f"Root:     {self.inst.state_dir / 'root'}",
                 f"Log:      {self._f('jupyter.log')}",
                 f"Lock:     {'pixi.lock' if self.LOCK.exists() else 'none (next build solves latest)'}"]
        pid = self._pid()
        if pid and self.is_running():
            lines.insert(0, f"Pid:      {pid}")
        return lines

    def clean(self, out, images=False):
        if self.is_running():
            self.stop(out)
        self._guard_env(self.inst.profile)
        run(self.px("clean", "-e", self.inst.env_name), out, env=self.clean_env())
        out(f"Removed pixi environment '{self.inst.env_name}'.")


def backend_for(settings: Settings, inst: Instance) -> Backend:
    return {"container": Container, "pixi": Pixi}[inst.backend](settings, inst)
