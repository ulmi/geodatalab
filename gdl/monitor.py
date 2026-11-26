"""Data behind the TUI's Monitor tab: CPU/memory of an instance, its processes,
and which notebook each Jupyter kernel belongs to."""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .backends import Backend, Container, Pixi

PROBE = Path(__file__).with_name("probe.py")
HISTORY = 60  # samples kept for the sparklines


@dataclass
class Sample:
    cpu: float = 0.0          # % of one core (200 = two cores busy)
    rss: int = 0              # bytes
    mem_limit: int = 0        # bytes (container limit or RAM)
    cores: int = 1
    procs: list[dict] = field(default_factory=list)
    kernels: list[dict] = field(default_factory=list)
    note: str = ""


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def parse_size(s: str) -> int:
    """'12.3MiB', '1.2GB', '512kB' (podman/docker stats) → bytes."""
    m = re.match(r"\s*([\d.]+)\s*([kKMGT]?)i?B", s)
    if not m:
        return 0
    return int(float(m.group(1)) * 1024 ** " KMGT".index(m.group(2).upper() or " "))


def sessions(port: int, token: str) -> dict[str, dict]:
    """kernel id → {path, state} from Jupyter's REST API ({} if unreachable)."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/sessions",
                                 headers={"Authorization": f"token {token}"} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json.load(r)
    except (OSError, ValueError):
        return {}
    return {s["kernel"]["id"]: {"path": s.get("path") or s.get("name", "?"),
                                "state": s["kernel"].get("execution_state", "?")}
            for s in data if s.get("kernel")}


class Monitor:
    """Keeps a short history per instance; sample() is blocking (run it in a worker)."""

    def __init__(self) -> None:
        self.cpu: dict[str, deque] = {}
        self.mem: dict[str, deque] = {}
        self._tokens: dict[str, str] = {}

    def history(self, name: str) -> tuple[list[float], list[float]]:
        return list(self.cpu.get(name, [])), list(self.mem.get(name, []))

    def sample(self, be: Backend) -> Sample:
        inst = be.inst
        if not be.is_running():
            return Sample(note="Not running.")
        if inst.is_service:
            s = self._stats(be)
        else:
            s = self._probe(be)
            s.cpu = sum(p["cpu"] for p in s.procs)
            s.rss = sum(p["rss"] for p in s.procs)
            if inst.mode != "idle":
                s.kernels = self._kernels(be, s.procs)
        self.cpu.setdefault(inst.name, deque(maxlen=HISTORY)).append(s.cpu)
        self.mem.setdefault(inst.name, deque(maxlen=HISTORY)).append(s.rss / 2**20)
        return s

    def _probe(self, be: Backend) -> Sample:
        try:
            if isinstance(be, Pixi):
                from .probe import snapshot
                data = snapshot(be._pid())
            else:
                r = subprocess.run([be.rt, "exec", "-i", be.inst.container_name, "python3", "-"],
                                   input=PROBE.read_text(), capture_output=True, text=True, timeout=10)
                data = json.loads(r.stdout)
        except (OSError, ValueError, subprocess.SubprocessError, ImportError) as e:
            return Sample(note=f"Process list unavailable: {e}")
        return Sample(procs=data["procs"], mem_limit=data["mem_limit"], cores=data["cores"])

    def _stats(self, be: Container) -> Sample:
        try:
            out = subprocess.run([be.rt, "stats", "--no-stream", "--format", "{{.CPUPerc}}|{{.MemUsage}}",
                                  be.inst.container_name], capture_output=True, text=True, timeout=10).stdout
            cpu, mem = out.strip().splitlines()[-1].split("|")
            used, _, limit = mem.partition("/")
            return Sample(cpu=float(cpu.strip().rstrip("%") or 0), rss=parse_size(used),
                          mem_limit=parse_size(limit), note="Services show totals only.")
        except (OSError, ValueError, IndexError, subprocess.SubprocessError) as e:
            return Sample(note=f"Stats unavailable: {e}")

    def _kernels(self, be: Backend, procs: list[dict]) -> list[dict]:
        name = be.inst.name
        if name not in self._tokens:
            self._tokens[name] = be.token()
        info = sessions(be.inst.port, self._tokens[name])
        if not info:
            self._tokens.pop(name, None)  # token may have changed (restart): fetch again next time
        by_kernel = {p["kernel"]: p for p in procs if p["kernel"]}
        rows = []
        for kid, k in info.items():
            p = by_kernel.get(kid, {})
            rows.append({**k, "id": kid, "pid": p.get("pid", ""), "cpu": p.get("cpu", 0.0),
                         "rss": p.get("rss", 0)})
        return sorted(rows, key=lambda r: -r["cpu"])
