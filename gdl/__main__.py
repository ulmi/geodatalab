"""geodatalab manager.   pixi run gdl  → TUI.   pixi run gdl <command>  → scripting.

    start | stop | restart | status | url | open | logs | shell | update
    build [--profile P] [--no-cache]   lock [PROFILE ...]   clean [--images]
    render   (regenerate .gdl/<instance>/compose.data.yml, used by .devcontainer)
Any command takes -i NAME for a named instance (or GDL_INSTANCE=NAME).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import webbrowser

from .config import PROFILES, GdlError, Settings, migrate_legacy
from .render import write_fragment

COMMANDS = ["start", "stop", "restart", "status", "url", "open", "logs", "shell",
            "update", "build", "lock", "clean", "render"]


def say(msg: str, color: str = "32") -> None:
    tag = f"\033[{color}m[geodatalab]\033[0m" if sys.stdout.isatty() else "[geodatalab]"
    print(f"{tag} {msg}", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gdl", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-i", "--instance", default=os.environ.get("GDL_INSTANCE", "default"))
    ap.add_argument("command", nargs="?", choices=COMMANDS)
    ap.add_argument("args", nargs="*")
    ap.add_argument("--profile", choices=list(PROFILES))
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--images", action="store_true", help="clean: also remove all geodatalab images")
    a = ap.parse_args(argv)

    if sys.platform == "win32":
        os.system("")  # enable ANSI colours in the Windows console
    if migrate_legacy():
        say("Converted .geodatalab to geodatalab.toml (old files kept as *.bak).", "33")

    if a.command is None:
        from .tui import GeodatalabApp
        GeodatalabApp(instance=a.instance).run()
        return 0
    try:
        return run(a)
    except GdlError as e:
        say(str(e), "31")
        return 1
    except KeyboardInterrupt:
        return 130


def run(a: argparse.Namespace) -> int:
    from .backends import backend_for
    settings = Settings()
    inst = settings.get(a.instance)
    if a.command == "render":
        say(f"Rendered {write_fragment(inst)}")
        return 0
    if not settings.exists:
        raise GdlError("No geodatalab.toml yet. Run `pixi run gdl` to set up, "
                       "or copy geodatalab.example.toml.")
    be = backend_for(settings, inst)
    out = print
    match a.command:
        case "start":
            be.start(out)
            if inst.mode != "idle" and be.is_running():
                say(be.url(), "34")
        case "stop":
            be.stop(out)
        case "restart":
            be.restart(out)
        case "url":
            say(be.url() if be.is_running() else "Not running.", "34")
        case "open":
            if not be.is_running():
                raise GdlError("Not running. Start it first.")
            webbrowser.open(be.url())
        case "status":
            state = "running" if be.is_running() else "stopped"
            for k, v in [("Instance", inst.name), ("Backend", f"{inst.backend} ({be.label()})"),
                         ("Profile", inst.profile), ("Mode", inst.mode), ("Port", inst.port),
                         ("Workspace", inst.workspace or "not set"),
                         ("State", f"{state} {be.health()}".strip())]:
                print(f"{k + ':':11}{v}")
            for d in inst.data:
                print(f"{'Data:':11}{d.name} -> {d.path}{'  (ro)' if d.ro else ''}")
            for line in be.status():
                print(line)
            if state == "running" and inst.mode != "idle":
                say(be.url(), "34")
        case "logs":
            be.logs(out, threading.Event())
        case "shell":
            argv, env, cwd = be.shell()
            return subprocess.call(argv, env=env, cwd=cwd)
        case "build":
            be.build(out, profile=a.profile, no_cache=a.no_cache)
        case "lock":
            be.lock(out, a.args or [inst.profile])
        case "update":
            be.update(out)
        case "clean":
            if input(f"Remove {inst.backend} resources of '{inst.name}'"
                     f"{' and ALL geodatalab images' if a.images else ''}? [y/N] ").lower() == "y":
                be.clean(out, images=a.images)
    return 0


if __name__ == "__main__":
    sys.exit(main())
