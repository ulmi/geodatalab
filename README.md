<p align="center">
  <img src="images/logo_nobg.png" width="350" alt="geodatalab">
</p>

<h1 align="center">geodatalab</h1>

<p align="center">
  A geospatial workbench on Linux, macOS or Windows: in a container (Podman/Docker) or a pixi environment
</p>

---

A headless GIS workstation served through JupyterLab and [JupyterGIS](https://jupytergis.readthedocs.io). Use the browser, VS Code Dev Containers, or a shell. One manager drives every backend, with the same profiles and the same folder layout.

## About

This grew out of several projects, cause I was tired of setting up every machine again and juggling what each project needed. I also wanted to come back to a hibernating project after several months and find it still working, not broken by newer packages, and also cause I'm sort of an "Evel Knievel" distro hopper, so my setup has to survive the next jump. The project was already somehow working, but scattered and held together with a lot of tape. Now, with the "advent" of AI, it come to fruition, and it's somewhat ready for the public.

## Quick start

The only thing to install is [pixi](https://pixi.sh). Docker or Podman is needed only for the container backend.

```bash
# Linux / macOS
curl -fsSL https://pixi.sh/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm -useb https://pixi.sh/install.ps1 | iex"

git clone https://github.com/ulmi/geodatalab.git
cd geodatalab
pixi run gdl          # opens the manager
```

The manager opens on an empty list. Press **n** (or **New instance…**) to start the wizard. Step 1 asks for a name and a type: a **workbench** (JupyterLab + GIS stack) or a **service** from a template, such as PostGIS. Step 2 asks what that type needs: backend, profile and workspace folder for a workbench, or the image for a service. The settings go to `geodatalab.toml`. Then press **b** to build a workbench and **s** to start.

![The manager on first run](images/tui1.png)

## The manager

```
┌ Instances ───────────────┐┌ Overview │ Monitor │ Logs │ Settings │ Data │ … ┐
│ default  pixi       8888 ││ default   pixi · kitchen · mode lab · port 8888 │
│ pinhel   container  8890 ││ State:      healthy                             │
│                          ││ URL:        http://localhost:8888/lab?token=…   │
└──────────────────────────┘└─────────────────────────────────────────────────┘
 s Start  x Stop  r Restart  o Open  c Copy URL  h Shell  b Build  l Lock  u Update  f Logs  n New  d Delete  q Quit
```

- **Overview:** state, URL and folders of the selected instance.
- **Monitor:** live CPU and memory, which notebooks are running (idle/busy, CPU, memory) and the processes behind them.
- **Settings:** backend, profile, mode, port, workspace, start folder and container limits.
- **Data:** add or remove data folders, toggle read-only, choose where Jupyter opens.
- **Logs:** the selected instance's workbench log, live while the tab is open (**f** jumps there).
- **GDL Tools:** Free disk space (shortcut **k**): pixi cache, unused envs and images, leftovers of deleted instances — you pick.
- **GDL Activity:** what the manager itself does: builds, locks, deletes, clean-ups.

**Delete** (**d**) removes the instance together with its files: its pixi env or container image (unless another instance shares it), a service's data volume, and `.gdl/<name>`. Tick *Keep these files on disk* to only forget the instance. **Free disk space** (GDL Tools tab, or **k**) lists what can go without affecting any instance (pixi download cache, unused envs and images, leftovers of deleted instances) with sizes; you pick. Workspace and data folders are never touched.

Jupyter keeps running after you quit the manager.

### Moving an environment to another machine

**Export recipe…** (Overview, or **e**) saves the selected workbench's environment as one plain-text file, `~/<name>.gdlenv.toml`: its settings and the exact version of every package (no data, no machine paths). On the other machine: **n** → *From a recipe file*, pick the file, fill in the workspace and a path for each data folder it names; the manager builds the same environment from it. The imported instance gets its own environment, so other instances there are not affected.

```bash
pixi run export ~/pinhel.gdlenv.toml                     # scripting: export the default instance
pixi run import ~/pinhel.gdlenv.toml --name pinhel --workspace ~/work --data ccdrn=/media/disk/CCDRN
```

For a container workbench the recipe carries the image tag; the other machine rebuilds it from the same locks.

For scripts, the same operations are pixi tasks:

```bash
pixi run start | stop | restart | status | url | open | logs | shell
pixi run build [--profile lab] [--no-cache]
pixi run lock [lab ...]
pixi run gdl -i pinhel start          # any command, for a named instance
```

## Settings: `geodatalab.toml`

The manager edits it, and you can too. See [`geodatalab.example.toml`](geodatalab.example.toml). It isn't committed.

```toml
backend = "pixi"
profile = "lab"
port = 8888
workspace = "/home/me/projects"

[[data]]
name = "ccdrn"
path = "/media/disk1/CCDRN"
ro = true

[instance.pinhel]     # another workbench: only what differs
port = 8890
profile = "kitchen"
```

A `.geodatalab` file from the old `geodatalab.sh` is converted automatically on first run, and the old file is kept as `.geodatalab.bak`.

## Backends

| Backend | What runs | Notes |
|---------|-----------|-------|
| `container` | Podman (preferred) or Docker image on `debian:trixie-slim` | Full stack incl. GRASS, SAGA, PDAL, lasR. Linux, macOS (Docker Desktop / Podman machine), Windows |
| `pixi` | conda-forge environment, Jupyter as a host process | No container runtime or root. Linux x86-64, Apple Silicon Macs, Windows x64. **No SAGA yet** (not on conda-forge) and no lasR. `institute` and `r+julia` are Linux-only (no conda-forge Julia elsewhere) |

`pixi.toml` is generated from the same `requirements/*.txt` the image uses, so you can also skip the manager: `pixi run -e lab jupyter lab`.

**Remote workbench:** clone it on the server, then `ssh box 'cd geodatalab && pixi run start'` and `ssh -L 8888:localhost:8888 box`.

## Services: PostGIS and friends

Next to workbenches, the manager runs ready-made **service containers** from templates in [`templates/`](templates/). Press **n**, pick a type (for example **PostGIS**) and an image variant (Debian or Alpine). Then press **s** to start it.

![Step 2 of the wizard for a PostGIS service](images/tui2.png)

- Every container joins the `geodatalab` network, where instances reach each other **by name**: `postgresql://gis:…@gisdb:5432/gis`.
- Services publish their port on `127.0.0.1`, so pixi workbenches, QGIS and other desktop apps use `localhost:<port>`.
- Every workbench gets each service's address as `GDL_SERVICE_<NAME>`, already right for where it runs:

```python
import os, geopandas as gpd
from sqlalchemy import create_engine
eng = create_engine(os.environ["GDL_SERVICE_GISDB"])
gdf.to_postgis("parcels", eng)            # psycopg2 + GeoAlchemy2 are in every GIS profile
```

- **Settings** sets the image, port, environment and `shm_size` (PostGIS starts with 1 GB instead of Docker's 64 MB). The password is generated per instance.
- Data lives in a named volume (`geodatalab-<name>-data`). Deleting the instance removes it too, unless you tick *Keep these files on disk*; a kept volume shows up later under **Free disk space** (GDL Tools).
- **Shell** (`h`) opens `psql`. **Update** (`u`) pulls a newer image.
- Works with Docker and Podman. Your own templates go in `templates.d/`, which isn't committed.

Workbenches also get `shm_size` in Settings (useful for Dask).

## Workspace & data folders

Every backend shows the folders in the same place:

```
workspace/        -> your workspace (read-write)
data/<name>/      -> each data folder (read-only is enforced on the container backend)
```

Notebooks stay portable across backends:

```python
import os
from pathlib import Path
dem = Path(os.environ["GDL_DATA"]) / "ccdrn" / "dem.tif"   # or os.environ["GDL_DATA_CCDRN"]
```

## Profiles

| Profile | Contents | Size |
|---------|----------|------|
| `kitchen` | Python GIS + scikit-learn, scikit-image, xarray-spatial, PySAL (libpysal, esda, mgwr, momepy) + JupyterLab + JupyterGIS + DuckDB + whitebox | ~1.9 GB |
| `lab` | kitchen + GRASS GIS + SAGA GIS + netCDF4 + h5py *(default)* | ~2.5 GB |
| `institute` | lab + R + Julia + rpy2 | ~4.3 GB |
| `r+julia` | JupyterLab + R + Julia only | ~2.5 GB |

## Reproducible builds and updates

The `requirements/*.txt` files list what goes in. The lock files pin exact versions: `requirements/locks/*.lock` for the image, `pixi.lock` for pixi. Builds install from the locks; **Lock** (`l`) re-resolves to the latest versions and **Update** (`u`) re-locks, rebuilds and restarts. Commit the lock files.

## Modes

| Mode | Behaviour |
|------|-----------|
| `lab` | Start JupyterLab *(default)* |
| `idle` | No Jupyter. For VS Code Dev Containers or the shell |

## Environment variables

| Variable | Effect |
|----------|--------|
| `JUPYTER_TOKEN` | Fixed auth token (unset = auto-generated) |
| `GDL_INSTANCE` | Same as `-i <name>` |
| `GDL_BACKEND` | One-off backend override |
| `GDL_RUNTIME` | `podman` or `docker` (default: podman if installed, else docker) |
| `GDL_BIND` | pixi: listen address (default `127.0.0.1`) |
| `GDL_CONFIG` | Use another settings file |

## VS Code Dev Containers

`.devcontainer/` uses the same compose files as the manager, so VS Code sees the same `/gdl/workspace` and `/gdl/data/<name>`. Build the image first, then **Reopen in Container**. The container runs in `idle` mode. The Python interpreter and kernels are at `/venv`.

## Build notes

- Multi-stage image: compiled in a builder stage, runtime libraries only in the final image
- SAGA and GRASS Python APIs come from Debian packages and are bridged into the venv through a targeted `.pth` (PEP 668-safe). The build fails if they can't be imported
- Smoke test: in **Shell** (`h`), run `python /opt/geodatalab/smoke.py` (container) or `python tests/smoke.py` from the repo (pixi)
- Tests for the manager: `pixi run test`
