"""Process snapshot for the Monitor tab. Standalone (psutil + stdlib only): the
manager imports it for pixi, and pipes this file into `<rt> exec -i <c> python3 -`
for container workbenches. Prints/returns JSON-able data."""
import json
import os
import re
import sys
import time

import psutil

KERNEL_RE = re.compile(r"kernel-([0-9a-f-]{36})\.json")


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


def snapshot(root: int | None = None, interval: float = 0.5) -> dict:
    """root: pid whose tree to watch (pixi), or None for every process (container)."""
    if root is None:  # all but this probe (and the exec that started it)
        me = os.getpid()
        procs = [p for p in psutil.process_iter() if p.pid != me and p.pid != os.getppid()]
    else:
        try:
            top = psutil.Process(root)
            procs = [top, *top.children(recursive=True)]
        except psutil.Error:
            procs = []
    for p in procs:
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    time.sleep(interval)
    rows = []
    for p in procs:
        try:
            with p.oneshot():
                cmd = p.cmdline()
                m = KERNEL_RE.search(" ".join(cmd))
                rows.append({"pid": p.pid, "name": p.name(), "cpu": p.cpu_percent(None),
                             "rss": p.memory_info().rss, "cmd": " ".join(cmd) or p.name(),
                             "kernel": m.group(1) if m else ""})
        except psutil.Error:
            pass
    return {"procs": rows, "mem_limit": mem_limit(), "cores": psutil.cpu_count() or 1}


if __name__ == "__main__":
    json.dump(snapshot(int(sys.argv[1]) if len(sys.argv) > 1 else None), sys.stdout)
