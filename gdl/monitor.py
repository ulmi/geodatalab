"""Data behind the TUI's Monitor tab: CPU/memory of an instance (its pixi env's
processes or its container — nothing else on the machine), its processes, and which
notebook each Jupyter kernel belongs to — plus the braille ("dot matrix") graphs."""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import psutil
from rich.text import Text

from .backends import Backend, Container, Pixi

PROBE = Path(__file__).with_name("probe.py")
HISTORY = 300   # samples kept per series (10 min at the 2 s poll); graphs show what fits
BACKGROUND = 20.0  # % CPU of a kernel's tree that counts as working while Jupyter says idle
CPU_EASE = 0.35    # instance CPU (graph + label) eases toward each sample: blips stay small,
                   # real load still shows within a few samples (tables keep raw numbers)


@dataclass
class Sample:
    cpu: float = 0.0          # % of one core (200 = two cores busy)
    rss: int = 0              # bytes
    mem_limit: int = 0        # bytes (container limit or RAM)
    cores: int = 1
    cpu_limit: float | None = None  # container CPU limit (cores), None = all cores
    procs: list[dict] = field(default_factory=list)
    kernels: list[dict] = field(default_factory=list)
    note: str = ""
    running: bool = False


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
            s = Sample(note="Not running.")
        elif inst.is_service:
            s = self._stats(be)
        else:
            s = self._probe(be)
            if s.cpu < 0:  # no cgroup total (pixi): the tree's sum
                s.cpu = sum(p["cpu"] for p in s.procs)
            s.rss = sum(p["rss"] for p in s.procs)
            if inst.mode != "idle":
                s.kernels = self._kernels(be, s.procs)
        s.running = be.is_running()
        if not s.running:
            self.cpu.pop(inst.name, None)
            self.mem.pop(inst.name, None)
        if s.running:
            hist = self.cpu.setdefault(inst.name, deque(maxlen=HISTORY))
            if hist:
                s.cpu = hist[-1] + CPU_EASE * (s.cpu - hist[-1])
            hist.append(s.cpu)
            self.mem.setdefault(inst.name, deque(maxlen=HISTORY)).append(s.rss)
        return s

    def _probe(self, be: Backend) -> Sample:
        try:
            if isinstance(be, Pixi):
                from .probe import snapshot
                data = snapshot(be._pid())
            else:
                r = subprocess.run([be.rt, "exec", "-i", be.inst.container_name, "python3", "-", "gdl-probe"],
                                   input=PROBE.read_text(), capture_output=True, text=True, timeout=10)
                data = json.loads(r.stdout)
        except (OSError, ValueError, subprocess.SubprocessError, ImportError) as e:
            return Sample(cpu=-1, note=f"Process list unavailable: {e}")
        total = data.get("cpu_total")
        return Sample(procs=data["procs"], mem_limit=data["mem_limit"], cores=data["cores"],
                      cpu=-1 if total is None else total, cpu_limit=data.get("cpu_limit"))

    def _stats(self, be: Container) -> Sample:
        try:
            out = subprocess.run([be.rt, "stats", "--no-stream", "--format", "{{.CPUPerc}}|{{.MemUsage}}",
                                  be.inst.container_name], capture_output=True, text=True, timeout=10).stdout
            cpu, mem = out.strip().splitlines()[-1].split("|")
            used, _, limit = mem.partition("/")
            return Sample(cpu=float(cpu.strip().rstrip("%") or 0), rss=parse_size(used),
                          mem_limit=parse_size(limit), cores=psutil.cpu_count() or 1,
                          note="Services show totals only.")
        except (OSError, ValueError, IndexError, subprocess.SubprocessError) as e:
            return Sample(note=f"Stats unavailable: {e}")

    def _kernels(self, be: Backend, procs: list[dict]) -> list[dict]:
        name = be.inst.name
        if name not in self._tokens:
            self._tokens[name] = be.token()
        info = sessions(be.inst.port, self._tokens[name])
        if not info:
            self._tokens.pop(name, None)  # token may have changed (restart): fetch again next time
        # forked children (multiprocessing, joblib) inherit the kernel's command line, so
        # several processes carry its id: the kernel is the topmost of them
        by_kernel: dict[str, dict] = {}
        for kid in {p["kernel"] for p in procs if p["kernel"]}:
            group = [p for p in procs if p["kernel"] == kid]
            pids = {p["pid"] for p in group}
            by_kernel[kid] = next((p for p in group if p.get("ppid") not in pids), group[0])
        rows = []
        for kid, k in info.items():
            p = by_kernel.get(kid)
            tree = subtree(procs, p["pid"]) if p else []
            cpu = sum(q["cpu"] for q in tree)
            state = k["state"]
            if state == "idle" and cpu >= BACKGROUND:  # e.g. threads/processes a cell left running
                state = "background"
            rows.append({**k, "state": state, "id": kid, "pid": p["pid"] if p else "", "cpu": cpu,
                         "rss": sum(q["rss"] for q in tree), "procs": len(tree),
                         "threads": sum(q.get("threads", 1) for q in tree)})
        return sorted(rows, key=lambda r: -r["cpu"])


def subtree(procs: list[dict], pid: int) -> list[dict]:
    """The process `pid` and all its descendants (by ppid)."""
    kids: dict[int, list[dict]] = {}
    for p in procs:
        kids.setdefault(p.get("ppid", -1), []).append(p)
    out, todo = [], [p for p in procs if p["pid"] == pid]
    while todo:
        p = todo.pop()
        out.append(p)
        todo.extend(kids.get(p["pid"], []))
    return out


# ── drawing: braille graphs ("dot matrix") and meters, as rich Text ──────────────

_DOTS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))  # braille dot bits by row, column


def level_style(frac: float) -> str:
    """green → yellow → red, like btop's gradient."""
    return "green" if frac < 0.5 else "yellow" if frac < 0.8 else "red"


def braille(values: list[float], width: int, height: int, top: float, style: str = "",
            min_dot: bool = False) -> Text:
    """A filled area graph of the newest values, 2 samples per character and 4 dot
    rows per line. `top` = the value of a full column. Rows are coloured by height,
    or all in `style`. min_dot: every sample shows at least one dot, zero included —
    a running instance always has a visible floor (300 MB of 50 GB, an idle 0 % CPU);
    the empty stretch before the history starts stays blank."""
    width, height = max(1, width), max(1, height)
    vals = values[-2 * width:]
    vals = [-1.0] * (2 * width - len(vals)) + vals  # -1: no sample yet
    rows = 4 * height
    levels = [min(rows, round(max(0.0, v) / top * rows)) if top > 0 else 0 for v in vals]
    if min_dot:
        levels = [max(lvl, 1) if v >= 0 else lvl for lvl, v in zip(levels, vals)]
    lines = []
    for line in range(height):
        bottom = (height - 1 - line) * 4  # dot rows below this line
        chars = []
        for c in range(width):
            code = 0
            for col in (0, 1):
                lvl = levels[2 * c + col] - bottom
                for r in range(4):  # r = 0 is the top dot row of the cell
                    if lvl >= 4 - r:
                        code |= _DOTS[r][col]
            chars.append(chr(0x2800 + code) if code else " ")
        lines.append(Text("".join(chars), style=style or level_style((bottom + 4) / rows)))
    return Text("\n").join(lines)
