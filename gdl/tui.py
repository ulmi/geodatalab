"""Textual TUI: pick an instance on the left, manage it on the right."""
from __future__ import annotations

import subprocess
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
                             Select, Static, TabbedContent, TabPane)

from .backends import Backend, backend_for
from .config import (BACKENDS, MODES, PROFILES, DataDir, GdlError, Instance, Settings,
                     check_data_name)
from .render import NETWORK, remove_state, service_url
from .templates import load as load_templates


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

    def __init__(self, question: str, field: str | None = None):
        super().__init__()
        self.question, self.field = question, field

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.question)
            if self.field is not None:
                yield Input(placeholder=self.field, id="answer")
            with Horizontal(classes="buttons"):
                yield Button("OK", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed)
    @on(Input.Submitted)
    def done(self, event) -> None:
        if getattr(event, "button", None) and event.button.id == "cancel":
            self.dismiss(None)
        elif self.field is not None:
            self.dismiss(self.query_one("#answer", Input).value.strip() or None)
        else:
            self.dismiss(True)


class Setup(ModalScreen):
    """First run: the essentials for the default instance."""

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield from logo()
            yield Label("[b]Welcome to geodatalab[/b] — set up your workbench")
            yield Label("Backend")
            yield Select(options(BACKENDS), value="pixi", allow_blank=False, id="backend")
            yield Label("Profile")
            yield Select(options(PROFILES), value="kitchen", allow_blank=False, id="profile")
            yield Label("Workspace folder (your notebooks and projects)")
            yield Input(str(Path.home() / "geodatalab"), id="workspace")
            with Horizontal(classes="buttons"):
                yield Button("Create", variant="primary", id="ok")
            yield Static(Text.assemble(
                ("Tab", "bold"), " / ", ("Shift+Tab", "bold"), "  next / previous field\n",
                ("Enter", "bold"), " or ", ("Space", "bold"), "  open a list · ",
                ("↑ ↓", "bold"), " choose · ", ("Enter", "bold"), " pick · ", ("Esc", "bold"), " close\n",
                ("Enter", "bold"), " in the folder field, or ", ("Create", "bold"), ", saves"),
                classes="hint")

    @on(Button.Pressed, "#ok")
    @on(Input.Submitted, "#workspace")
    def create(self) -> None:
        self.dismiss({"backend": self.query_one("#backend", Select).value,
                      "profile": self.query_one("#profile", Select).value,
                      "workspace": str(Path(self.query_one("#workspace", Input).value).expanduser())})


class NewInstance(ModalScreen):
    """Name + type: a workbench, or a service from a template (with its image variant)."""
    WORKBENCH = "workbench"

    def __init__(self):
        super().__init__()
        self.templates = load_templates()

    def compose(self) -> ComposeResult:
        types = [("Workbench  —  JupyterLab + GIS stack (pixi or container)", self.WORKBENCH)]
        types += [(f"{t.name}  —  {t.description}", k) for k, t in self.templates.items()]
        with Vertical(id="dialog"):
            yield Label("[b]New instance[/b]")
            yield Label("Name")
            yield Input(placeholder="lowercase letters, digits, -", id="name")
            yield Label("Type")
            yield Select(types, value=self.WORKBENCH, allow_blank=False, id="type")
            yield Label("Image", id="variant-label")
            yield Select([("-", "-")], allow_blank=False, id="variant")
            with Horizontal(classes="buttons"):
                yield Button("Create", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")
            yield Static(Text(f"Services join the '{NETWORK}' network: other containers reach them by "
                              "instance name, pixi workbenches through localhost. Every workbench gets "
                              "their addresses as GDL_SERVICE_<NAME>."), classes="hint")

    def on_mount(self) -> None:
        self.show_variants(self.WORKBENCH)

    @on(Select.Changed, "#type")
    def type_changed(self, event: Select.Changed) -> None:
        self.show_variants(event.value)

    def show_variants(self, key) -> None:
        t = self.templates.get(key)
        variants = list(t.images.items()) if t else []
        sel = self.query_one("#variant", Select)
        if variants:
            sel.set_options([(f"{v}  —  {img}", v) for v, img in variants])
            sel.value = variants[0][0]
        for w in (sel, self.query_one("#variant-label")):
            w.display = len(variants) > 1

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#ok")
    @on(Input.Submitted, "#name")
    def create(self) -> None:
        name = self.query_one("#name", Input).value.strip()
        key = self.query_one("#type", Select).value
        if not name:
            self.notify("Enter a name.", severity="error")
            return
        template = "" if key == self.WORKBENCH else key
        variant = self.query_one("#variant", Select).value if template else ""
        self.dismiss((name, template, variant if variant != "-" else ""))


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
    .buttons { height: auto; padding: 0 1; }
    .buttons Button { margin-right: 1; }
    #form { grid-size: 2; grid-columns: 18 1fr; grid-rows: auto; padding: 1 2; height: auto; grid-gutter: 0 1; }
    #form Label { padding-top: 1; }
    #data-add { height: auto; padding: 0 1; }
    #data-add Input { width: 1fr; }
    #data-add #d-name { width: 20; }
    #data-add Checkbox, #data-add Button { width: auto; }
    #data { height: 1fr; }
    #dialog { width: 72; height: auto; max-height: 100%; overflow-y: auto; padding: 1 2; border: thick $primary; background: $surface; }
    Ask, Setup, NewInstance { align: center middle; }
    """
    BINDINGS = [
        Binding("s", "start", "Start"), Binding("x", "stop", "Stop"), Binding("r", "restart", "Restart"),
        Binding("o", "open", "Open"), Binding("c", "copy", "Copy URL"), Binding("h", "shell", "Shell"),
        Binding("b", "build", "Build"), Binding("l", "lock", "Lock"), Binding("u", "update", "Update"),
        Binding("f", "follow", "Logs"), Binding("n", "new", "New inst."), Binding("d", "delete", "Del inst."),
        Binding("k", "clean", "Clean", show=False), Binding("q", "quit", "Quit"),
    ]

    def __init__(self, instance: str = "default"):
        super().__init__()
        self.settings = Settings()
        names = self.settings.names()
        self.current = instance if instance in names or not names else names[0]
        self.follow_stop: threading.Event | None = None

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
                            yield Button(name.capitalize() if name != "copy" else "Copy URL", id=f"do-{name}")
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
                        yield Button("Save", variant="primary", id="save")
                with TabPane("Data", id="tab-data"):
                    yield DataTable(id="data", cursor_type="row")
                    with Horizontal(id="data-add"):
                        yield Input(placeholder="name", id="d-name")
                        yield Input(placeholder="/path/to/folder", id="d-path")
                        yield Checkbox("read-only", id="d-ro")
                        yield Button("Add", id="d-add")
                    with Horizontal(classes="buttons"):
                        yield Button("Remove", id="d-rm")
                        yield Button("Toggle read-only", id="d-toggle")
                        yield Button("Jupyter opens here", id="d-open")
                with TabPane("Log", id="tab-log"):
                    yield RichLog(id="log", wrap=True, max_lines=5000)
        yield Footer()

    def on_mount(self) -> None:
        self.columns = self.query_one("#instances", DataTable).add_columns("Instance", "Kind", "Port", "State")
        self.query_one("#data", DataTable).add_columns("Name", "Read-only", "Path")
        self.query_one("#instances", DataTable).focus()
        if not self.settings.exists or not self.settings.names():  # first run, or all deleted
            self.push_screen(Setup(), self.first_run)
        self.show_instance()
        self.refresh_states()
        self.set_interval(5, self.refresh_states)

    def first_run(self, values: dict) -> None:
        self.current = "default"
        self.settings.update(Instance(port=self.settings.free_port(exclude="default")), **values)
        self.notify("Created the 'default' instance. Next: Build (b), then Start (s).")
        self.show_instance()
        self.refresh_states()

    # ── state ──────────────────────────────────────────────────────────────────

    @property
    def inst(self) -> Instance:
        return self.settings.get(self.current)

    def backend(self) -> Backend:
        return backend_for(self.settings, self.inst)

    @work(thread=True, exclusive=True, group="refresh")
    def refresh_states(self) -> None:
        if self.current not in self.settings.names():
            self.call_from_thread(self.paint_states, [], "", None)
            return
        rows = []
        for n in self.settings.names():
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
        if self.current not in names:
            self.query_one("#overview", Static).update("No instances. Press n to create one.")
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

    def show_instance(self) -> None:
        if self.current not in self.settings.names():
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

    # ── operations (run in a worker, output to the Log tab) ────────────────────

    def say(self, msg: str, style: str = "") -> None:
        self.query_one("#log", RichLog).write(Text(msg, style=style))

    @work(thread=True, exclusive=True, group="op")
    def op(self, title: str, method: str, **kwargs) -> None:
        self.call_from_thread(setattr, self.query_one("#tabs", TabbedContent), "active", "tab-log")
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

    def action_clean(self) -> None:
        i = self.inst
        if i.is_service:
            what = f"container and its data volume ({i.container_name}-data — all data in it)"
        else:
            what = "container" if i.backend == "container" else f"pixi env '{i.env_name}'"
        self.push_screen(Ask(f"Remove the {what} of instance '{self.current}'?"),
                         lambda ok: ok and self.op("Clean", "clean"))

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
        self.call_from_thread(self.copy_to_clipboard, url)
        self.call_from_thread(self.notify, f"Copied: {url}")

    def action_shell(self) -> None:
        try:
            argv, env, cwd = self.backend().shell()
            with self.suspend():
                subprocess.call(argv, env=env, cwd=cwd)
        except GdlError as e:
            self.notify(str(e), severity="error")
        except Exception as e:  # e.g. suspend not supported in this terminal
            self.notify(f"Shell unavailable here: {e}", severity="error")

    def action_follow(self) -> None:
        if self.follow_stop:
            self.follow_stop.set()
            self.follow_stop = None
            self.say("■ stopped following logs", "dim")
            return
        self.follow_stop = threading.Event()
        self.query_one("#tabs", TabbedContent).active = "tab-log"
        self.say(f"▶ following logs of '{self.current}' (press f to stop)", "bold cyan")
        self.follow(self.backend(), self.follow_stop)

    @work(thread=True, group="logs")
    def follow(self, be: Backend, stop: threading.Event) -> None:
        try:
            be.logs(lambda line: self.call_from_thread(self.say, line), stop)
        except GdlError as e:
            self.call_from_thread(self.say, str(e), "bold red")

    # ── instances ──────────────────────────────────────────────────────────────

    def action_new(self) -> None:
        def create(answer):
            if not answer:
                return
            name, template, variant = answer
            try:
                inst = self.settings.new_instance(name, template, variant)
                self.current = inst.name
                what = f"{inst.template} service" if inst.is_service else "workbench"
                self.notify(f"Created {what} '{name}' on port {inst.port}. Start it with s.")
                self.show_instance()
                self.refresh_states()
            except GdlError as e:
                self.notify(str(e), severity="error")
        self.push_screen(NewInstance(), create)

    def action_delete(self) -> None:
        name = self.current
        if name not in self.settings.names():
            return
        extra = " The other instances keep their current settings." if name == "default" else ""
        if self.inst.is_service:
            extra += f" Its data volume {self.inst.container_name}-data is kept (Clean, k, removes it)."
        self.push_screen(Ask(f"Delete instance '{name}'? Its config and generated state go; "
                             f"workspace and data folders are untouched.{extra}"),
                         lambda ok: ok and self.delete(name))

    @work(thread=True, exclusive=True, group="op")
    def delete(self, name: str) -> None:
        inst = self.settings.get(name)
        be = backend_for(self.settings, inst)
        if be.is_running():
            self.call_from_thread(self.notify, f"'{name}' is running. Stop it first.", severity="error")
            return
        if inst.backend == "container":
            try:
                argv, env = be.compose("down")
                subprocess.run(argv, env=env, capture_output=True)
            except GdlError:
                pass
        remove_state(inst)
        self.settings.remove_instance(name)
        names = self.settings.names()
        self.current = names[0] if names else "default"
        self.call_from_thread(self.notify, f"Deleted instance '{name}'.")
        self.call_from_thread(self.show_instance)
        self.call_from_thread(self.refresh_states)
        if not names:  # nothing left: set up a new default instance
            self.call_from_thread(self.push_screen, Setup(), self.first_run)

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
