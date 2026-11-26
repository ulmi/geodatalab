"""Process snapshot for the Monitor tab. Standalone (psutil + stdlib only): the
manager imports it for pixi, and pipes this file into `<rt> exec -i <c> python3 -`
for container workbenches. Prints/returns JSON-able data.

CPU is measured from cpu_times deltas over `interval`, not psutil's cpu_percent:
- each process's own time plus its *reaped* children's (children_user/system), so
  work done by short-lived subprocesses (multiprocessing, joblib, shell commands)
  still counts after they exit;
- processes are listed again at the end, so ones that started during the interval
  count too (all their CPU time falls inside it);
- in a container, the cgroup's own counter (cpu.stat usage_usec) is the total:
  it sees every process, even ones that came and went between the two listings.
"""
import json
import os
import re
import sys
import time

import psutil

KERNEL_RE = re.compile(r"kernel-([0-9a-f-]{36})\.json")
TAG = "gdl-probe"  # on every probe's command line: probes skip each other (two monitors, one container)
CGROUP_CPU = "/sys/fs/cgroup/cpu.stat"


def mem_limit() -> int:
    """cgroup v2/v1 memory limit if set (containers), else physical RAM."""
    total = psutil.virtual_memory().total
    for f in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            v = open(f).read().strip()
            if v.isdigit() and int(v) < total:
                return int(v)
        except OSError:
            pass
    return total


def cpu_limit() -> float | None:
    """CPUs this cgroup may use (cgroup v2 cpu.max quota / period), or None if unlimited."""
    try:
        quota, period = open("/sys/fs/cgroup/cpu.max").read().split()[:2]
        return None if quota == "max" else int(quota) / int(period)
    except (OSError, ValueError):
        return None


def cgroup_usec() -> int | None:
    """CPU time used by this cgroup so far (cgroup v2), or None."""
    try:
        for line in open(CGROUP_CPU):
            if line.startswith("usage_usec "):
                return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def _listing(root: int | None) -> list[psutil.Process]:
    if root is None:  # every process but this probe (and the exec that started it)
        skip = {os.getpid(), os.getppid()}
        return [p for p in psutil.process_iter() if p.pid not in skip]
    try:
        top = psutil.Process(root)
        return [top, *top.children(recursive=True)]
    except psutil.Error:
        return []


def _busy(p: psutil.Process) -> float:
    t = p.cpu_times()
    return t.user + t.system + getattr(t, "children_user", 0.0) + getattr(t, "children_system", 0.0)


def snapshot(root: int | None = None, interval: float = 0.5, cgroup: bool | None = None) -> dict:
    """root: pid whose tree to watch (pixi), or None for every process (container).
    cgroup: use the cgroup counter for the total (default: when root is None)."""
    cgroup = root is None if cgroup is None else cgroup
    before: dict[int, tuple[float, float, int]] = {}  # pid -> (create_time, cpu seconds, ppid)
    for p in _listing(root):
        try:
            with p.oneshot():
                before[p.pid] = (p.create_time(), _busy(p), p.ppid())
        except psutil.Error:
            pass
    usec0, t0 = cgroup_usec() if cgroup else None, time.monotonic()
    time.sleep(interval)
    usec1, elapsed = cgroup_usec() if cgroup else None, time.monotonic() - t0
    rows, delta, probes = [], {}, 0.0
    for p in _listing(root):
        try:
            with p.oneshot():
                created, busy = p.create_time(), _busy(p)
                prev = before.get(p.pid)
                # started during the interval (or pid reused): all of its time is new
                d = busy - prev[1] if prev and prev[0] == created else busy
                cmd = p.cmdline()
                if TAG in cmd:  # another monitor's probe: not the instance's work
                    probes += d
                    continue
                delta[p.pid] = d
                m = KERNEL_RE.search(" ".join(cmd))
                rows.append({"pid": p.pid, "ppid": p.ppid(), "name": p.name(), "threads": p.num_threads(),
                             "rss": p.memory_info().rss, "cmd": " ".join(cmd) or p.name(),
                             "kernel": m.group(1) if m else ""})
        except psutil.Error:
            pass
    # a child that exited and was reaped during the interval moved its whole lifetime into
    # its parent's children_* time; what it used before the interval was already counted
    for pid, (_, busy, ppid) in before.items():
        if pid not in delta and ppid in delta:
            delta[ppid] -= busy
    for r in rows:
        r["cpu"] = max(0.0, 100.0 * delta[r["pid"]] / elapsed)
    total = None
    if usec0 is not None and usec1 is not None:
        total = max(0.0, 100.0 * ((usec1 - usec0) / 1e6 - probes) / elapsed)
    return {"procs": rows, "mem_limit": mem_limit(), "cores": psutil.cpu_count() or 1, "cpu_total": total,
            "cpu_limit": cpu_limit() if cgroup else None}


if __name__ == "__main__":
    pid = next((a for a in sys.argv[1:] if a.isdigit()), None)  # `python3 - gdl-probe [pid]`
    json.dump(snapshot(int(pid) if pid else None), sys.stdout)
