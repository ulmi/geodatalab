"""geodatalab manager.   pixi run gdl  → TUI.   pixi run gdl <command>  → scripting.

    start | stop | restart | status | url | open | logs | shell | update
    build [--profile P] [--no-cache]   lock [PROFILE ...]   clean [--images]
    render   (regenerate .gdl/<instance>/compose.data.yml, used by .devcontainer)
    export [FILE] [--label TEXT]          the instance's env as a recipe (default ~/<instance>.gdlenv.toml)
    import FILE [--name N] [--workspace DIR] [--data NAME=PATH ...]   a new instance from a recipe
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
from .render import service_urls, write_fragment

COMMANDS = ["start", "stop", "restart", "status", "url", "open", "logs", "shell",
            "update", "build", "lock", "clean", "render", "export", "import"]


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
    ap.add_argument("--label", default="", help="export: a note stored in the recipe")
    ap.add_argument("--name", help="import: instance name (default: the recipe's)")
    ap.add_argument("--workspace", help="import: workspace folder (default ~/geodatalab)")
    ap.add_argument("--data", action="append", default=[], metavar="NAME=PATH",
                    help="import: path for a data folder named in the recipe (repeatable)")
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
    from .backends import Container, backend_for
    settings = Settings()
    inst = settings.get(a.instance)
    if a.command == "render":  # also used by .devcontainer's initializeCommand
        say(f"Rendered {write_fragment(inst, service_urls(settings, internal=True))}")
        try:  # the fragment joins the shared network: make sure it exists
            Container(settings, inst).ensure_network()
        except GdlError:
            pass  # no container runtime here
        return 0
    if a.command == "import":
        return import_cmd(settings, a)
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
            if inst.is_service:
                rows = [("Instance", inst.name), ("Service", f"{inst.template} ({inst.image})"),
                        ("Port", inst.port), ("State", f"{state} {be.health()}".strip()),
                        ("Address", be.url())]
            else:
                rows = [("Instance", inst.name), ("Backend", f"{inst.backend} ({be.label()})"),
                        ("Profile", inst.profile), ("Mode", inst.mode), ("Port", inst.port),
                        ("Workspace", inst.workspace or "not set"),
                        ("State", f"{state} {be.health()}".strip())]
            for k, v in rows:
                print(f"{k + ':':11}{v}")
            for d in inst.data:
                print(f"{'Data:':11}{d.name} -> {d.path}{'  (ro)' if d.ro else ''}")
            for line in be.status():
                print(line)
            if state == "running" and inst.mode != "idle" and not inst.is_service:
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
        case "export":
            from pathlib import Path
            from .recipe import export_recipe
            path = export_recipe(inst, Path(a.args[0]) if a.args else Path.home(), a.label)
            say(f"Exported the env of '{inst.name}' to {path}")
        case "clean":
            try:
                yes = input(f"Remove {inst.backend} resources of '{inst.name}'"
                            f"{' and ALL geodatalab images' if a.images else ''}? [y/N] ").lower() == "y"
            except EOFError:  # no terminal (script, pipe without input): never remove unasked
                print()
                say("Not removed: no answer (run it in a terminal, or pipe in 'y').", "33")
                return 1
            if yes:
                be.clean(out, images=a.images)
    return 0


def import_cmd(settings: Settings, a: argparse.Namespace) -> int:
    from pathlib import Path
    from .recipe import Recipe, import_recipe
    if not a.args:
        raise GdlError("Usage: gdl import FILE [--name N] [--workspace DIR] [--data NAME=PATH ...]")
    r = Recipe.load(Path(a.args[0]).expanduser())
    paths = dict(d.split("=", 1) for d in a.data if "=" in d)
    name = a.name or r.name
    inst = import_recipe(settings, r, name, a.workspace or str(Path.home() / "geodatalab"), paths)
    say(f"Created '{name}' from the recipe ({r.summary()}).")
    for d in r.data:
        if d["name"] not in paths:
            say(f"Data folder '{d['name']}' skipped (no --data {d['name']}=PATH); add it later in the Data tab.", "33")
    say(f"Build it: pixi run gdl -i {name} build", "34")
    return 0


if __name__ == "__main__":
    sys.exit(main())
