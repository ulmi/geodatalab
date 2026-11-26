"""Textual TUI: pick an instance on the left, manage it on the right."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Grid, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (Button, Checkbox, DataTable, Footer, Header, Input, Label, RichLog,
                             Select, Sparkline, Static, TabbedContent, TabPane)

from .backends import Backend, backend_for
from .config import (BACKENDS, INSTANCE_RE, MODES, PROFILES, DataDir, GdlError, Instance, Settings,
                     check_data_name)
from .monitor import Monitor, Sample, human
from .cleanup import Item, delete_instance, instance_files, reclaimable
from .recipe import Recipe, export_recipe, import_recipe
from .render import NETWORK, service_url
from .templates import load as load_templates


def native_copy(text: str) -> bool:
    """Copy via the OS clipboard tool. Textual's copy_to_clipboard uses OSC 52,
    which VTE terminals (GNOME/Mint/Xfce Terminal) ignore."""
    if sys.platform == "darwin":
        cands = [["pbcopy"]]
    elif sys.platform == "win32":
        cands = [["clip"]]
    else:
        cands = ([["wl-copy"]] if os.environ.get("WAYLAND_DISPLAY") else []) + \
                ([["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
                 if os.environ.get("DISPLAY") else [])
    for argv in cands:
        if shutil.which(argv[0]):
            try:
                subprocess.run(argv, input=text, text=True, check=True, timeout=5,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except (OSError, subprocess.SubprocessError):
                continue
    return False


def logo() -> ComposeResult:
    """The geodatalab globe (ANSI art from the original geodatalab.sh), centered, + title."""
    art = Text.from_ansi((Path(__file__).parent / "logo.ans").read_text(encoding="utf-8").rstrip("\n"))
    with Center(classes="logo"):
        yield Static(art, classes="logo-art")
    yield Static(Text.assemble(("geodatalab", "bold"), "  —  GIS Data Laboratory"), classes="logo-title")


def options(d: dict) -> list[tuple[str, str]]:
    return [(f"{k}  —  {v}", k) for k, v in d.items()]


class Ask(ModalScreen):
    """Yes/no question, or a text prompt when `field` is given. Dismisses with
    the answer (str / True) or None."""

    def __init__(self, question: str, field: str | None = None, value: str = ""):
        super().__init__()
        self.question, self.field, self.value = question, field, value

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.question)
            if self.field is not None:
                yield Input(self.value, placeholder=self.field, id="answer")
            with Horizontal(classes="buttons"):
                yield Button("OK", variant="primary", id="ok", compact=True)
                yield Button("Cancel", id="cancel", compact=True)

    @on(Button.Pressed)
    @on(Input.Submitted)
    def done(self, event) -> None:
        if getattr(event, "button", None) and event.button.id == "cancel":
            self.dismiss(None)
        elif self.field is not None:
            self.dismiss(self.query_one("#answer", Input).value.strip() or None)
        else:
            self.dismiss(True)



def size_text(it: Item) -> str:
    if it.size is None:
        return "size unknown"
    return ("up to " if it.approx else "") + human(it.size) if it.size else ""


class DeleteDialog(ModalScreen):
    """Delete an instance. Its files (env/image/volume, state) go too unless
    'Keep files on disk' is ticked. Dismisses with keep_files (bool) or None."""

    def __init__(self, name: str, items: list[Item], kept: list[str], note: str = ""):
        super().__init__()
        self.inst_name, self.items, self.kept, self.note = name, items, kept, note

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(Text.assemble("Delete instance ", (self.inst_name, "bold"), "?"))
            lines = [Text("This also removes from disk:")]
            for it in self.items:
                lines.append(Text.assemble("  • ", (it.label, "bold red" if it.warn else "bold"),
                                           f"  {size_text(it)}\n    ", (it.detail, "dim")))
            lines += [Text(f"  Kept, shared: {k}", style="dim") for k in self.kept]
            lines.append(Text("\nYour workspace and data folders are never touched."))
            if self.note:
                lines.append(Text(self.note, style="dim"))
            yield Static(Text("\n").join(lines), classes="hint")
            yield Checkbox("Keep these files on disk (only forget the instance)", id="keep")
            with Horizontal(classes="buttons"):
                yield Button("Delete", variant="error", id="ok", compact=True)
                yield Button("Cancel", id="cancel", compact=True)

    @on(Button.Pressed)
    def done(self, event: Button.Pressed) -> None:
        self.dismiss(None if event.button.id == "cancel" else self.query_one("#keep", Checkbox).value)

    def key_escape(self) -> None:
        self.dismiss(None)


class Cleaner(ModalScreen):
    """Pick what to free. Nothing a configured instance needs is listed.
    Dismisses with the chosen items, or None."""

    def __init__(self, items: list[Item]):
        super().__init__()
        self.items = items

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(Text("Free disk space", style="bold"))
            if not self.items:
                yield Static("Nothing to clean — all tidy.", classes="hint")
            for n, it in enumerate(self.items):
                size = size_text(it)
                yield Checkbox(f"{it.label}  ·  {size}" if size else it.label, value=it.default, id=f"c{n}")
                yield Static(Text(it.detail, style="red" if it.warn else "dim"), classes="detail")
            yield Static("Envs, images and volumes your instances use are never listed; "
                         "workspace and data folders are never touched.", classes="hint")
            with Horizontal(classes="buttons"):
                yield Button("Free", variant="primary", id="ok", compact=True, disabled=not self.items)
                yield Button("Cancel", id="cancel", compact=True)

    def on_mount(self) -> None:
        self.total()

    @on(Checkbox.Changed)
    def total(self) -> None:
        if self.items:
            chosen = self.chosen()
            n = sum(it.size or 0 for it in chosen)
            upto = "up to " if any(it.approx for it in chosen) else ""
            self.query_one("#ok", Button).label = f"Free {upto}{human(n)}" if n else "Free"

    def chosen(self) -> list[Item]:
        return [it for n, it in enumerate(self.items) if self.query_one(f"#c{n}", Checkbox).value]

    @on(Button.Pressed)
    def done(self, event: Button.Pressed) -> None:
        self.dismiss(self.chosen() if event.button.id == "ok" else None)

    def key_escape(self) -> None:
        self.dismiss(None)


NAV_HINT = Text.assemble(
    ("Tab", "bold"), " / ", ("Shift+Tab", "bold"), "  next / previous field\n",
    ("Enter", "bold"), " or ", ("Space", "bold"), "  open a list · ",
    ("↑ ↓", "bold"), " choose · ", ("Enter", "bold"), " pick · ", ("Esc", "bold"), " close")


class Wizard(ModalScreen):
    """Create an instance in two steps: 1) name + type, 2) what that type needs
    (workbench: backend, profile, workspace · service: image variant).
    Dismisses with a dict, or None when cancelled."""
    WORKBENCH = "workbench"
    RECIPE = "recipe"

    def __init__(self, taken: list[str], suggested: str = ""):
        super().__init__()
        self.taken, self.suggested, self.step = taken, suggested, 1
        self.templates = load_templates()
        self.recipe: Recipe | None = None

    def compose(self) -> ComposeResult:
        types = [("Workbench  —  JupyterLab + GIS stack (pixi or container)", self.WORKBENCH)]
        types += [("From a recipe file  —  an env exported with Export recipe", self.RECIPE)]
        types += [(f"{t.name}  —  {t.description}", k) for k, t in self.templates.items()]
        with Vertical(id="dialog"):
            yield Label(id="title")
            with Vertical(id="step1", classes="step"):
                yield Label("Name")
                yield Input(self.suggested, placeholder="lowercase letters, digits, -", id="name")
                yield Label("Type")
                yield Select(types, value=self.WORKBENCH, allow_blank=False, id="type")
            with Vertical(id="step2-wb", classes="step"):
                yield Label("Backend")
                yield Select(options(BACKENDS), value="pixi", allow_blank=False, id="backend")
                yield Label("Profile")
                yield Select(options(PROFILES), value="kitchen", allow_blank=False, id="profile")
                yield Label("Workspace folder (your notebooks and projects)")
                yield Input(str(Path.home() / "geodatalab"), id="workspace")
            with Vertical(id="step2-recipe", classes="step"):
                yield Label("Recipe file (.gdlenv.toml)")
                yield Input(placeholder=str(Path.home() / "name.gdlenv.toml"), id="recipe-path")
                yield Static(id="recipe-info", classes="hint")
                yield Label("Workspace folder (your notebooks and projects)")
                yield Input(str(Path.home() / "geodatalab"), id="r-workspace")
                yield Vertical(id="recipe-data", classes="step")
            with Vertical(id="step2-svc", classes="step"):
                yield Label("Image")
                yield Select([("-", "-")], allow_blank=False, id="variant")
                yield Static(Text(f"Services join the '{NETWORK}' network: other containers reach "
                                  "them by instance name, pixi workbenches through localhost. Every "
                                  "workbench gets their addresses as GDL_SERVICE_<NAME>."), classes="hint")
            with Horizontal(classes="buttons"):
                yield Button("Back", id="back", compact=True)
                yield Button("Next", variant="primary", id="next", compact=True)
                yield Button("Create", variant="primary", id="ok", compact=True)
                yield Button("Cancel", id="cancel", compact=True)
            yield Static(NAV_HINT, classes="hint")

    def on_mount(self) -> None:
        self.show_step()

    @property
    def kind(self) -> str:
        return self.query_one("#type", Select).value

    @property
    def template(self) -> str:
        return "" if self.kind in (self.WORKBENCH, self.RECIPE) else self.kind

    def show_step(self) -> None:
        svc, rec = bool(self.template), self.kind == self.RECIPE
        what = "service" if svc else "workbench from a recipe" if rec else "workbench"
        self.query_one("#title", Label).update(
            f"[b]Create an instance[/b] — step {self.step} of 2"
            + ("" if self.step == 1 else f": {what} '{self.name_value}'"))
        self.query_one("#step1").display = self.step == 1
        self.query_one("#step2-wb").display = self.step == 2 and not svc and not rec
        self.query_one("#step2-recipe").display = self.step == 2 and rec
        self.query_one("#step2-svc").display = self.step == 2 and svc
        for b, show in (("#back", self.step == 2), ("#next", self.step == 1), ("#ok", self.step == 2)):
            self.query_one(b).display = show
        focus = {1: "#name", 2: "#variant" if svc else "#recipe-path" if rec else "#workspace"}[self.step]
        self.query_one(focus).focus()

    @property
    def name_value(self) -> str:
        return self.query_one("#name", Input).value.strip()

    @on(Button.Pressed, "#next")
    @on(Input.Submitted, "#name")
    def go_next(self) -> None:
        name = self.name_value
        if not INSTANCE_RE.match(name):
            self.notify("Name: lowercase letters, digits and '-'.", severity="error")
            return
        if name in self.taken:
            self.notify(f"Instance '{name}' already exists.", severity="error")
            return
        if self.template:
            t = self.templates[self.template]
            sel = self.query_one("#variant", Select)
            sel.set_options([(f"{v}  —  {img}", v) for v, img in t.images.items()])
            sel.value = next(iter(t.images))
        self.step = 2
        self.show_step()

    @on(Button.Pressed, "#back")
    def back(self) -> None:
        self.step = 1
        self.show_step()

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)

    @on(Input.Changed, "#recipe-path")
    def load_recipe(self, event: Input.Changed) -> None:
        """Read the recipe as soon as the path points at a file; ask a path per data folder."""
        path = Path(event.value.strip()).expanduser()
        info = self.query_one("#recipe-info", Static)
        box = self.query_one("#recipe-data", Vertical)
        if not path.is_file():
            self.recipe = None
            info.update("")
            box.remove_children()
            return
        try:
            self.recipe = Recipe.load(path)
        except (GdlError, OSError, UnicodeDecodeError) as e:
            self.recipe = None
            info.update(Text(str(e), style="red"))
            box.remove_children()
            return
        r = self.recipe
        info.update(Text.assemble((f"Recipe '{r.name}'", "bold"), f": {r.summary()}"))
        box.remove_children()
        for n, d in enumerate(r.data):
            box.mount(Label(f"Data folder '{d['name']}'{' (ro)' if d.get('ro') else ''}: its path here "
                            "(empty = skip)"))
            box.mount(Input(placeholder="/path/to/folder", id=f"rd-{n}"))

    @on(Button.Pressed, "#ok")
    @on(Input.Submitted, "#workspace")
    @on(Input.Submitted, "#r-workspace")
    def create(self) -> None:
        answer = {"name": self.name_value, "template": self.template, "variant": ""}
        if self.kind == self.RECIPE:
            if not self.recipe:
                self.notify("Pick a recipe file first.", severity="error")
                return
            answer |= {"recipe": self.recipe,
                       "workspace": str(Path(self.query_one("#r-workspace", Input).value).expanduser()),
                       "data": {d["name"]: self.query_one(f"#rd-{n}", Input).value.strip()
                                for n, d in enumerate(self.recipe.data)}}
        elif self.template:
            answer["variant"] = self.query_one("#variant", Select).value
        else:
            answer |= {"backend": self.query_one("#backend", Select).value,
                       "profile": self.query_one("#profile", Select).value,
                       "workspace": str(Path(self.query_one("#workspace", Input).value).expanduser())}
        self.dismiss(answer)


class GeodatalabApp(App):
    TITLE = "geodatalab"
    CSS = """
    #tabs { width: 1fr; }
    #side { width: 44; border-right: solid $primary-darken-2; }
    #side Label { padding: 0 1; text-style: bold; }
    .logo { height: auto; padding-top: 1; }
    .logo-art { width: auto; }
    .logo-title { width: 1fr; text-align: center; padding-bottom: 1; }
    .hint { color: $text-muted; padding-top: 1; height: auto; }
    #overview { padding: 1 2; height: auto; }
    .buttons { height: auto; padding: 1 1 0 1; }
    .buttons Button { margin-right: 2; min-width: 0; width: auto; padding: 0 2; }
    #form { grid-size: 2; grid-columns: 18 1fr; grid-rows: auto; padding: 1 2; height: auto; grid-gutter: 0 1; }
    #form Label { padding-top: 1; }
    #data-add { height: auto; padding: 0 1; }
    #data-add Input { width: 1fr; }
    #data-add #d-name { width: 20; }
    #data-add Checkbox, #data-add Button { width: auto; }
    #data-add Button { margin: 1 0 0 1; }
    #data { height: 1fr; }
    #monitor { padding: 1 2 0 2; }
    .meter { height: 1; margin-bottom: 1; }
    .meter Label { width: 34; }
    .meter Sparkline { width: 1fr; height: 1; }
    #monitor .title { text-style: bold; padding-top: 1; }
    #m-kernels { height: auto; max-height: 10; }
    #m-procs { height: 1fr; }
    #m-note { color: $text-muted; }
    #logs-head { color: $text-muted; padding: 0 1; }
    #tabs #tabs-list-bar, #tabs #tabs-list { width: 1fr; }
    #tabs .tab-spacer { width: 1fr; height: 1; }
    #tools { padding: 1 2; height: auto; }
    #tools .title { text-style: bold; }
    #tools .hint { padding-top: 0; }
    #dialog { width: 72; height: auto; max-height: 100%; overflow-y: auto; padding: 1 2; border: thick $primary; background: $surface; }
    Ask, Wizard { align: center middle; }
    .step { height: auto; }
    #dialog .buttons { padding: 1 0 0 0; }
    #dialog .buttons Button { margin-right: 2; }
    DeleteDialog, Cleaner { align: center middle; }
    #dialog .detail { padding: 0 0 0 4; height: auto; }
    """
    BINDINGS = [
        Binding("s", "start", "Start"), Binding("x", "stop", "Stop"), Binding("r", "restart", "Restart"),
        Binding("o", "open", "Open"), Binding("c", "copy", "Copy URL"), Binding("h", "shell", "Shell"),
        Binding("b", "build", "Build"), Binding("l", "lock", "Lock"), Binding("u", "update", "Update"),
        Binding("f", "follow", "Logs"), Binding("n", "new", "New inst."), Binding("d", "delete", "Del inst."),
        Binding("k", "cleanup", "Free space", show=False), Binding("e", "export", "Export", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, instance: str = "default"):
        super().__init__()
        self.settings = Settings()
        names = self.names()
        self.current = instance if instance in names or not names else names[0]
        self.follow_stop: threading.Event | None = None
        self._following = ""
        self.monitor = Monitor()
        self.theme = "gruvbox"

    INSTANCE_ACTIONS = {"start", "stop", "restart", "open", "copy", "shell", "build", "lock", "update",
                        "follow", "delete", "export"}

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Instance commands are greyed out in the footer (None) until an instance exists."""
        if action in self.INSTANCE_ACTIONS and self.current not in self.names():
            return None
        return True

    def names(self) -> list[str]:
        """Instances to show: none before geodatalab.toml exists (the CLI treats
        that as an implicit default instance; the TUI offers the wizard)."""
        return self.settings.names() if self.settings.exists else []

    # ── layout ─────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="side"):
                yield from logo()
                yield Label("Instances")
                yield DataTable(id="instances", cursor_type="row", zebra_stripes=True)
            with TabbedContent(id="tabs"):
                with TabPane("Overview", id="tab-overview"):
                    yield Static(id="overview")
                    with Horizontal(classes="buttons"):
                        for name in ("start", "stop", "restart", "open", "copy"):
                            yield Button(name.capitalize() if name != "copy" else "Copy URL", id=f"do-{name}",
                                         compact=True)
                        yield Button("New instance…", variant="primary", id="do-new", compact=True)
                    with Horizontal(classes="buttons"):
                        yield Button("Export recipe…", id="do-export", compact=True)
                with TabPane("Monitor", id="tab-monitor"):
                    with Vertical(id="monitor"):
                        with Horizontal(classes="meter"):
                            yield Label("CPU", id="m-cpu-label")
                            yield Sparkline([], id="m-cpu", summary_function=max)
                        with Horizontal(classes="meter"):
                            yield Label("Memory", id="m-mem-label")
                            yield Sparkline([], id="m-mem", summary_function=max)
                        yield Static(id="m-note")
                        yield Label("Notebooks", classes="title")
                        yield DataTable(id="m-kernels", cursor_type="row", zebra_stripes=True)
                        yield Label("Processes", classes="title")
                        yield DataTable(id="m-procs", cursor_type="row", zebra_stripes=True)
                with TabPane("Logs", id="tab-logs"):
                    yield Static(id="logs-head")
                    yield RichLog(id="logs", wrap=True, max_lines=5000)
                with TabPane("Settings", id="tab-settings"):
                    with Grid(id="form"):
                        # class "wb": workbenches only, "svc": services only
                        yield Label("Backend", classes="wb")
                        yield Select(options(BACKENDS), allow_blank=False, id="f-backend", classes="wb")
                        yield Label("Profile", classes="wb")
                        yield Select(options(PROFILES), allow_blank=False, id="f-profile", classes="wb")
                        yield Label("Mode", classes="wb")
                        yield Select(options(MODES), allow_blank=False, id="f-mode", classes="wb")
                        yield Label("Image", classes="svc")
                        yield Input(id="f-image", classes="svc", placeholder="e.g. docker.io/postgis/postgis:17-3.5-alpine")
                        yield Label("Port");      yield Input(id="f-port", type="integer")
                        yield Label("Environment", classes="svc")
                        yield Input(id="f-env", classes="svc", placeholder="KEY=value; KEY2=value")
                        yield Label("Workspace", classes="wb"); yield Input(id="f-workspace", classes="wb")
                        yield Label("Opens in", classes="wb")
                        yield Input(id="f-open", classes="wb", placeholder="workspace, data/<name> or empty")
                        yield Label("Image tag", classes="wb")
                        yield Input(id="f-image_tag", classes="wb", placeholder="container: latest")
                        yield Label("Shared mem."); yield Input(id="f-shm_size", placeholder="container /dev/shm, e.g. 2g")
                        yield Label("Memory");    yield Input(id="f-memory", placeholder="container limit, e.g. 16G")
                        yield Label("Memory res."); yield Input(id="f-memory_reserve", placeholder="e.g. 4G")
                        yield Label("CPUs");      yield Input(id="f-cpus", placeholder="e.g. 6")
                    with Horizontal(classes="buttons"):
                        yield Button("Save", variant="primary", id="save", compact=True)
                with TabPane("Data", id="tab-data"):
                    yield DataTable(id="data", cursor_type="row")
                    with Horizontal(id="data-add"):
                        yield Input(placeholder="name", id="d-name")
                        yield Input(placeholder="/path/to/folder", id="d-path")
                        yield Checkbox("read-only", id="d-ro")
                        yield Button("Add", id="d-add", compact=True)
                    with Horizontal(classes="buttons"):
                        yield Button("Remove", id="d-rm", compact=True)
                        yield Button("Toggle read-only", id="d-toggle", compact=True)
                        yield Button("Jupyter opens here", id="d-open", compact=True)
                with TabPane("GDL Tools", id="tab-tools"):
                    with Vertical(id="tools"):
                        yield Label("Free disk space", classes="title")
                        yield Static("Lists what can go without affecting any instance — pixi download cache, "
                                     "unused envs and images, leftovers of deleted instances — with sizes. "
                                     "You pick; workspace and data folders are never touched. (Shortcut: k)",
                                     classes="hint")
                        with Horizontal(classes="buttons"):
                            yield Button("Free disk space…", id="do-cleanup", compact=True)
                with TabPane("GDL Activity", id="tab-activity"):
                    yield RichLog(id="activity", wrap=True, max_lines=5000)
        yield Footer()

    def on_mount(self) -> None:
        self.columns = self.query_one("#instances", DataTable).add_columns("Instance", "Kind", "Port", "State")
        self.query_one("#data", DataTable).add_columns("Name", "Read-only", "Path")
        self.query_one("#instances", DataTable).focus()
        self.show_instance()
        self.refresh_states()
        self.set_interval(5, self.refresh_states)
        self.query_one("#m-kernels", DataTable).add_columns("Notebook", "State", "CPU %", "Memory", "PID")
        self.query_one("#m-procs", DataTable).add_columns("PID", "CPU %", "Memory", "Command")
        self.set_interval(2, self.tick_monitor)
        # push the GDL tabs to the right end of the tab bar (Tabs only counts Tab widgets)
        tools = self.query_one("#tabs #--content-tab-tab-tools")
        tools.parent.mount(Static(classes="tab-spacer"), before=tools)

    # ── state ──────────────────────────────────────────────────────────────────

    @property
    def inst(self) -> Instance:
        return self.settings.get(self.current)

    def backend(self) -> Backend:
        return backend_for(self.settings, self.inst)

    @work(thread=True, exclusive=True, group="refresh")
    def refresh_states(self) -> None:
        if self.current not in self.names():
            self.call_from_thread(self.paint_states, [], "", None)
            return
        rows = []
        for n in self.names():
            inst = self.settings.get(n)
            be = backend_for(self.settings, inst)
            running = be.is_running()
            kind = inst.template if inst.is_service else inst.backend
            rows.append((n, kind, str(inst.port), (be.health() or "running") if running else "stopped"))
        url, be, i = "", self.backend(), self.inst
        try:
            if i.is_service:  # connection info is useful even while stopped
                url = f"{be.url()}\n{service_url(i, internal=True)}"
            elif be.is_running() and i.mode != "idle":
                url = be.url()
            extra = be.status()
        except GdlError as e:
            extra = [str(e)]
        self.call_from_thread(self.paint_states, rows, url, extra)

    def paint_states(self, rows, url, extra) -> None:
        self.refresh_bindings()  # instances may have appeared/disappeared
        table = self.query_one("#instances", DataTable)
        colours = {"healthy": "green", "running": "green", "starting": "yellow", "stopped": "red"}
        cells = [(r[0], r[1], r[2], Text(r[3], style=colours.get(r[3], "yellow"))) for r in rows]
        names = [r[0] for r in rows]
        if names != [k.value for k in table.rows]:  # instances added/removed: rebuild
            table.clear()
            for c in cells:
                table.add_row(*c, key=c[0])
            if self.current in names:
                table.move_cursor(row=names.index(self.current))
        else:  # same instances: update in place, the cursor stays put
            for c in cells:
                for col, value in zip(self.columns[1:], c[1:]):
                    table.update_cell(c[0], col, value)
        empty = self.current not in names
        for b in ("start", "stop", "restart", "open", "copy", "export"):  # nothing to act on yet
            self.query_one(f"#do-{b}").display = not empty
        if empty:
            self.query_one("#overview", Static).update(Text.assemble(
                ("Welcome to geodatalab", "bold"), "\n\nNo instances yet. Press ", ("n", "bold"),
                " (or New instance below) to create one:\n",
                "  • a workbench: JupyterLab + GIS stack, on pixi or in a container\n",
                "  • a service from a template, such as a PostGIS database"))
            return
        i = self.inst
        state = dict((r[0], r[3]) for r in rows).get(self.current, "?")
        # Text objects, not markup: paths and URLs may contain [ ] characters
        if i.is_service:
            local, internal = (url.split("\n") + [""])[:2]
            lines = [Text.assemble((i.name, "bold"), f"   {i.template} · {i.image} · port {i.port}"),
                     Text.assemble("State:      ", (state, colours.get(state, "yellow"))),
                     Text.assemble("This machine: ", (local, "bold"), "   (pixi workbenches, desktop apps)"),
                     Text.assemble("Containers:   ", (internal, "bold"), "   (container workbenches)"),
                     Text(f"In notebooks: os.environ['GDL_SERVICE_{i.name.upper().replace('-', '_')}']")]
        else:
            lines = [Text.assemble((i.name, "bold"), f"   {i.backend} · {i.profile} · mode {i.mode} · port {i.port}"),
                     Text.assemble("State:      ", (state, colours.get(state, "yellow"))),
                     Text.assemble("URL:        ", (url, f"link {url}") if url else "—"),
                     Text.assemble("Workspace:  ", i.workspace or ("not set", "red"))]
        lines += [Text(f"Data:       {d.name} → {d.path}{'  (ro)' if d.ro else ''}") for d in i.data]
        if extra:
            lines += [Text(""), *map(Text, extra)]
        self.query_one("#overview", Static).update(Text("\n").join(lines))

    # ── monitor ────────────────────────────────────────────────────────────────

    def tick_monitor(self) -> None:
        if self.query_one("#tabs", TabbedContent).active == "tab-monitor" and self.current in self.names():
            self.sample_monitor()

    @on(TabbedContent.TabActivated, "#tabs")
    def tab_changed(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id == "tab-monitor":
            self.tick_monitor()
        self.follow_logs()  # starts on the Logs tab, stops when leaving it

    @work(thread=True, exclusive=True, group="monitor")
    def sample_monitor(self) -> None:
        name, be = self.current, self.backend()
        try:
            s = self.monitor.sample(be)
        except Exception as e:  # never let a probe hiccup kill the TUI
            s = Sample(note=f"Monitor error: {e}")
        self.call_from_thread(self.paint_monitor, name, s)

    def paint_monitor(self, name: str, s: Sample) -> None:
        if name != self.current:
            return
        cpu, mem = self.monitor.history(name)
        self.query_one("#m-cpu", Sparkline).data = cpu or [0]
        self.query_one("#m-mem", Sparkline).data = mem or [0]
        self.query_one("#m-cpu-label", Label).update(f"CPU     {s.cpu:6.1f} %  ({s.cores} cores)")
        limit = f" / {human(s.mem_limit)}" if s.mem_limit else ""
        self.query_one("#m-mem-label", Label).update(f"Memory  {human(s.rss)}{limit}")
        self.query_one("#m-note", Static).update(s.note)
        home = str(Path.home())
        busy = {"busy": "yellow", "idle": "green", "starting": "yellow"}
        self._fill(self.query_one("#m-kernels", DataTable), [
            (k["id"], [k["path"], Text(k["state"], style=busy.get(k["state"], "red")),
                       f"{k['cpu']:.1f}", human(k["rss"]) if k["rss"] else "", str(k["pid"])])
            for k in s.kernels])
        notebooks = {k["id"]: k["path"] for k in s.kernels}

        def command(p: dict) -> str:
            if p["kernel"] in notebooks:
                return f"kernel · {notebooks[p['kernel']]}"
            # /long/env/bin/python …/bin/jupyter lab → python jupyter lab
            words = [Path(w).name if "/bin/" in w or "\\bin\\" in w else w for w in p["cmd"].split()]
            return " ".join(words).replace(home, "~")[:200]

        procs = sorted(s.procs, key=lambda p: (-p["cpu"], -p["rss"]))[:100]
        self._fill(self.query_one("#m-procs", DataTable), [
            (str(p["pid"]), [str(p["pid"]), f"{p['cpu']:.1f}", human(p["rss"]), command(p)]) for p in procs])

    @staticmethod
    def _fill(table: DataTable, rows: list[tuple[str, list]]) -> None:
        """Replace the rows, keeping the cursor on the same key if it's still there."""
        keep = None
        if table.row_count and table.cursor_row < table.row_count:
            keep = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
        table.clear()
        for key, cells in rows:
            table.add_row(*cells, key=key)
        keys = [k for k, _ in rows]
        if keep in keys:
            table.move_cursor(row=keys.index(keep), animate=False)

    def show_instance(self) -> None:
        if self.follow_stop is None or self.follow_stop.is_set() or self._following != self.current:
            self.follow_logs()
        if self.current not in self.names():
            return
        i = self.inst
        for w in self.query(".wb"):
            w.display = not i.is_service
        for w in self.query(".svc"):
            w.display = i.is_service
        for key in ("backend", "profile", "mode"):
            self.query_one(f"#f-{key}", Select).value = getattr(i, key)
        for key in ("port", "workspace", "open", "image_tag", "image", "shm_size", "memory", "memory_reserve", "cpus"):
            self.query_one(f"#f-{key}", Input).value = str(getattr(i, key))
        self.query_one("#f-env", Input).value = "; ".join(f"{k}={v}" for k, v in i.env.items())
        table = self.query_one("#data", DataTable)
        table.clear()
        for d in i.data:
            table.add_row(d.name, "yes" if d.ro else "", d.path, key=d.name)

    @on(DataTable.RowHighlighted, "#instances")
    def pick(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row != event.data_table.cursor_row:  # stale (table was rebuilt)
            return
        if event.row_key.value != self.current:
            self.current = event.row_key.value
            self.show_instance()
            self.refresh_states()
            self.tick_monitor()

    # ── operations (run in a worker, output to the Log tab) ────────────────────

    def say(self, msg: str, style: str = "") -> None:
        self.query_one("#activity", RichLog).write(Text(msg, style=style))

    @work(thread=True, exclusive=True, group="op")
    def op(self, title: str, method: str, **kwargs) -> None:
        self.call_from_thread(setattr, self.query_one("#tabs", TabbedContent), "active", "tab-activity")
        self.call_from_thread(self.say, f"▶ {title}  [{self.current}]", "bold cyan")
        try:
            getattr(self.backend(), method)(lambda line: self.call_from_thread(self.say, line), **kwargs)
            self.call_from_thread(self.say, f"✔ {title} done", "bold green")
        except GdlError as e:
            self.call_from_thread(self.say, str(e), "bold red")
            self.call_from_thread(self.notify, str(e).splitlines()[0], severity="error")
        self.call_from_thread(self.show_instance)
        self.call_from_thread(self.refresh_states)

    def action_start(self) -> None: self.op("Start", "start")
    def action_stop(self) -> None: self.op("Stop", "stop")
    def action_restart(self) -> None: self.op("Restart", "restart")
    def action_build(self) -> None: self.op(f"Build {self.inst.profile}", "build")
    def action_lock(self) -> None: self.op(f"Lock {self.inst.profile}", "lock", profiles=[self.inst.profile])

    def action_update(self) -> None:
        self.push_screen(Ask(f"Re-lock to the latest versions and rebuild '{self.inst.profile}'?"),
                         lambda ok: ok and self.op("Update", "update"))

    @work(thread=True, exclusive=True, group="op")
    def action_cleanup(self) -> None:
        self.call_from_thread(self.notify, "Measuring disk usage…", timeout=3)
        items = reclaimable(self.settings)
        self.call_from_thread(self.push_screen, Cleaner(items), self.cleanup)

    def cleanup(self, chosen: list[Item] | None) -> None:
        if chosen:
            self.free(chosen)

    @work(thread=True, exclusive=True, group="op")
    def free(self, chosen: list[Item]) -> None:
        self.call_from_thread(setattr, self.query_one("#tabs", TabbedContent), "active", "tab-activity")
        out = lambda line: self.call_from_thread(self.say, line)  # noqa: E731
        for it in chosen:
            self.call_from_thread(self.say, f"▶ Removing {it.label}", "bold cyan")
            try:
                it.action(out)
            except (GdlError, OSError) as e:
                self.call_from_thread(self.say, str(e), "bold red")
        self.call_from_thread(self.say, "✔ Clean-up done", "bold green")
        self.call_from_thread(self.notify, "Clean-up done.")
        self.call_from_thread(self.refresh_states)

    @on(Button.Pressed, "#do-start")
    def _b1(self): self.action_start()
    @on(Button.Pressed, "#do-stop")
    def _b2(self): self.action_stop()
    @on(Button.Pressed, "#do-restart")
    def _b3(self): self.action_restart()
    @on(Button.Pressed, "#do-open")
    def _b4(self): self.action_open()
    @on(Button.Pressed, "#do-copy")
    def _b5(self): self.action_copy()
    @on(Button.Pressed, "#do-new")
    def _b6(self): self.action_new()
    @on(Button.Pressed, "#do-export")
    def _b7(self): self.action_export()
    @on(Button.Pressed, "#do-cleanup")
    def _b8(self): self.action_cleanup()

    def action_export(self) -> None:
        if self.inst.is_service:
            self.notify("Services have no env to export; their image is in the settings.", severity="warning")
            return
        name = self.current
        self.push_screen(Ask(f"Export the env of '{name}' as a recipe file (settings + exact package "
                             "versions, no data). Save to:", field="file",
                             value=str(Path.home() / f"{name}.gdlenv.toml")),
                         lambda path: path and self.export(name, path))

    @work(thread=True, exclusive=True, group="op")
    def export(self, name: str, path: str) -> None:
        try:
            out = export_recipe(self.settings.get(name), Path(path))
            self.call_from_thread(self.say, f"✔ Exported the env of '{name}' to {out}", "bold green")
            self.call_from_thread(self.notify, f"Exported to {out}", timeout=8)
        except (GdlError, OSError) as e:
            self.call_from_thread(self.notify, str(e), severity="error")

    @work(thread=True, group="url")
    def action_open(self) -> None:
        be = self.backend()
        if not be.is_running():
            self.call_from_thread(self.notify, "Not running.", severity="warning")
        elif not be.url().startswith("http"):
            self.call_from_thread(self.notify, "Not a web page. Copy its address (c) into your "
                                  "client or notebook.", severity="warning")
        else:
            webbrowser.open(be.url())

    @work(thread=True, group="url")
    def action_copy(self) -> None:
        be = self.backend()
        if not (self.inst.is_service or be.is_running()):  # a service's address is known up front
            self.call_from_thread(self.notify, "Not running.", severity="warning")
            return
        url = be.url()
        if native_copy(url):
            self.call_from_thread(self.notify, f"Copied: {url}")
        else:  # no display (e.g. over ssh): OSC 52 reaches the local terminal if it supports it
            self.call_from_thread(self.copy_to_clipboard, url)
            self.call_from_thread(self.notify, url, title="Jupyter URL", timeout=15)

    def action_shell(self) -> None:
        try:
            be = self.backend()
            argv, env, cwd = be.shell()
            with self.suspend():
                print(f"\n── geodatalab shell: {self.current} ({be.label()}) ── "
                      f"type 'exit' (or Ctrl-D) to return to gdl ──\n", flush=True)
                subprocess.call(argv, env=env, cwd=cwd)
            self.notify(f"Back from the shell of '{self.current}'.")
        except GdlError as e:
            self.notify(str(e), severity="error")
        except Exception as e:  # e.g. suspend not supported in this terminal
            self.notify(f"Shell unavailable here: {e}", severity="error")

    async def action_quit(self) -> None:
        self.stop_following()  # the follow thread would otherwise keep the app from exiting
        self.exit()

    def on_unmount(self) -> None:
        self.stop_following()

    def stop_following(self) -> None:
        if self.follow_stop:
            self.follow_stop.set()
            self.follow_stop = None

    def action_follow(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-logs"

    def follow_logs(self) -> None:
        """(Re)start following the selected instance's log in the Logs tab."""
        self.stop_following()
        view = self.query_one("#logs", RichLog)
        view.clear()
        if self.query_one("#tabs", TabbedContent).active != "tab-logs":
            return
        if self.current not in self.names():
            self.query_one("#logs-head", Static).update("No instance yet.")
            return
        self.query_one("#logs-head", Static).update(
            Text.assemble("Log of ", (self.current, "bold"), " · live while this tab is open"))
        self.follow_stop = threading.Event()
        self._following = self.current
        self.follow(self.backend(), self.follow_stop)

    @work(thread=True, group="logs")
    def follow(self, be: Backend, stop: threading.Event) -> None:
        def out(line: str) -> None:
            if not stop.is_set():  # a newer follow may have taken over
                self.call_from_thread(self.query_one("#logs", RichLog).write, Text(line))
        try:
            be.logs(out, stop)
        except GdlError as e:
            out(str(e))

    # ── instances ──────────────────────────────────────────────────────────────

    def action_new(self) -> None:
        def create(answer):
            if not answer:
                return
            name = answer["name"]
            try:
                if answer.get("recipe"):
                    inst = import_recipe(self.settings, answer["recipe"], name, answer["workspace"],
                                         answer["data"])
                    self.current = inst.name
                    self.notify(f"Created '{name}' from the recipe on port {inst.port}. Building its env …")
                    self.show_instance()
                    self.refresh_states()
                    self.action_build()
                    return
                inst = self.settings.new_instance(name, answer["template"], answer["variant"])
                if not inst.is_service:
                    inst = self.settings.update(inst, backend=answer["backend"], profile=answer["profile"],
                                                workspace=answer["workspace"])
                self.current = inst.name
                what = f"{inst.template} service" if inst.is_service else "workbench"
                hint = "Start it with s." if inst.is_service else "Build it with b, then start with s."
                self.notify(f"Created {what} '{name}' on port {inst.port}. {hint}")
                self.show_instance()
                self.refresh_states()
            except GdlError as e:
                self.notify(str(e), severity="error")
        names = self.names()
        self.push_screen(Wizard(taken=names, suggested="" if names else "default"), create)

    @work(thread=True, exclusive=True, group="op")
    def action_delete(self) -> None:
        name = self.current
        if name not in self.names():
            return
        if backend_for(self.settings, self.inst).is_running():
            self.call_from_thread(self.notify, f"'{name}' is running. Stop it first.", severity="error")
            return
        items, kept = instance_files(self.settings, self.inst)
        note = "The other instances keep their current settings." if name == "default" else ""
        self.call_from_thread(self.push_screen, DeleteDialog(name, items, kept, note),
                              lambda keep: keep is not None and self.delete(name, keep))

    @work(thread=True, exclusive=True, group="op")
    def delete(self, name: str, keep_files: bool) -> None:
        out = lambda line: self.call_from_thread(self.say, line)  # noqa: E731
        self.call_from_thread(self.say, f"▶ Delete instance  [{name}]", "bold cyan")
        try:
            delete_instance(self.settings, name, out, keep_files=keep_files)
        except GdlError as e:
            self.call_from_thread(self.say, str(e), "bold red")
            self.call_from_thread(self.notify, str(e).splitlines()[0], severity="error")
            return
        names = self.names()
        self.current = names[0] if names else "default"
        self.call_from_thread(self.say, f"✔ Deleted '{name}'" + (" (files kept)" if keep_files else ""),
                              "bold green")
        self.call_from_thread(self.notify, f"Deleted instance '{name}'.")
        self.call_from_thread(self.show_instance)
        self.call_from_thread(self.refresh_states)

    # ── settings & data ────────────────────────────────────────────────────────

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        i = self.inst
        common = ("shm_size", "memory", "memory_reserve", "cpus")
        if i.is_service:
            values = {k: self.query_one(f"#f-{k}", Input).value.strip() for k in ("image", *common)}
            env = {}
            for pair in self.query_one("#f-env", Input).value.split(";"):
                k, sep, v = pair.strip().partition("=")
                if k and sep:
                    env[k.strip()] = v.strip()
            values["env"], values["backend"], values["workspace"] = env, i.backend, i.workspace
        else:
            values = {k: self.query_one(f"#f-{k}", Select).value for k in ("backend", "profile", "mode")}
            values |= {k: self.query_one(f"#f-{k}", Input).value.strip()
                       for k in ("workspace", "open", "image_tag", *common)}
        try:
            values["port"] = int(self.query_one("#f-port", Input).value)
        except ValueError:
            self.notify("Port must be a number.", severity="error")
            return
        values["workspace"] = str(Path(values["workspace"]).expanduser()) if values["workspace"] else ""
        running = self.backend().is_running()
        if running and values["backend"] != i.backend:
            self.notify("Stop the instance before switching backend.", severity="error")
            return
        self.settings.update(i, **values)
        self.notify("Saved." + ("  Restart (r) to apply." if running else ""))
        self.refresh_states()

    def selected_data(self) -> DataDir | None:
        table = self.query_one("#data", DataTable)
        if not table.row_count:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return next((d for d in self.inst.data if d.name == key), None)

    def save_data(self, data: list[DataDir], **extra) -> None:
        self.settings.update(self.inst, data=data, **extra)
        self.show_instance()
        if self.backend().is_running():
            self.notify("Restart (r) to apply.")

    @on(Button.Pressed, "#d-add")
    def data_add(self) -> None:
        name = self.query_one("#d-name", Input).value.strip()
        path = self.query_one("#d-path", Input).value.strip()
        try:
            check_data_name(name, self.inst.data)
        except GdlError as e:
            self.notify(str(e), severity="error")
            return
        if not path:
            self.notify("Enter a folder path.", severity="error")
            return
        path = str(Path(path).expanduser().resolve())
        if not Path(path).is_dir():
            self.notify(f"Folder does not exist (yet): {path}", severity="warning")
        ro = self.query_one("#d-ro", Checkbox).value
        self.save_data([*self.inst.data, DataDir(name, path, ro)])
        for w in ("#d-name", "#d-path"):
            self.query_one(w, Input).value = ""

    @on(Button.Pressed, "#d-rm")
    def data_rm(self) -> None:
        d = self.selected_data()
        if d:
            opens = "" if self.inst.open == f"data/{d.name}" else self.inst.open
            self.save_data([x for x in self.inst.data if x.name != d.name], open=opens)

    @on(Button.Pressed, "#d-toggle")
    def data_toggle(self) -> None:
        d = self.selected_data()
        if d:
            self.save_data([DataDir(x.name, x.path, not x.ro if x.name == d.name else x.ro)
                            for x in self.inst.data])

    @on(Button.Pressed, "#d-open")
    def data_open(self) -> None:
        d = self.selected_data()
        if d:
            self.save_data(self.inst.data, open=f"data/{d.name}")
            self.notify(f"Jupyter opens in data/{d.name}")
