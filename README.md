<p align="center">
  <img src="images/logo_nobg.png" width="350" alt="geodatalab">
</p>

<h1 align="center">geodatalab</h1>

<p align="center">
  A geospatial workbench, local or remote, in a container (Podman/Docker) or a pixi environment
</p>

---

A headless GIS workstation served through JupyterLab and [JupyterGIS](https://jupytergis.readthedocs.io). No GUI required: use the browser, VS Code Dev Containers, or a shell. One CLI drives every backend, with the same profiles and the same folder layout.

## Quick start

```bash
git clone https://github.com/YOUR_USERNAME/geodatalab.git
cd geodatalab

./geodatalab.sh init                              # guided setup
# or step by step:
./geodatalab.sh workspace ~/projects              # your notebooks / project files
./geodatalab.sh data add gisdata /mnt/gis --ro    # optional: data folders
./geodatalab.sh build                             # build (default: lab profile)
./geodatalab.sh start                             # start, prints the URL
./geodatalab.sh open                              # open JupyterLab in the browser
```

Running `./geodatalab.sh` with no arguments opens an arrow-key menu.

## Backends

| Backend | What runs | Notes |
|---------|-----------|-------|
| `container` *(default)* | Podman (preferred) or Docker image on `debian:trixie-slim` | Full stack incl. GRASS, SAGA, PDAL, lasR |
| `pixi` | [pixi](https://pixi.sh) env from conda-forge, Jupyter as a host process | No container runtime or root needed. **No SAGA yet** (not on conda-forge) and no lasR |
| `nix` | — | Planned |

```bash
./geodatalab.sh backend pixi      # switch; workspace, data folders, profile and port are shared
./geodatalab.sh build -p kitchen  # downloads pixi to ~/.local/share/geodatalab on first use
./geodatalab.sh start
```

`pixi.toml` is generated from the same `requirements/*.txt` the image uses, so you can also skip the CLI: `pixi run -e lab jupyter lab`.

**Remote workbench:** clone it on the server, then `ssh box ./geodatalab/geodatalab.sh start` and `ssh -L 8888:localhost:8888 box`.

## Several workbenches side by side (instances)

One checkout can run several workbenches at once, for example one per project. Each one can have its own backend, profile, data folders and port:

```bash
./geodatalab.sh instances new pinhel                 # gets the next free port
./geodatalab.sh -i pinhel profile kitchen
./geodatalab.sh -i pinhel data add ren /data/REN/Pinhel --ro
./geodatalab.sh -i pinhel start                      # alongside the default one
./geodatalab.sh instances                            # name, backend, profile, port, state, data
```

An instance inherits everything from `.geodatalab` and stores only what differs, in `.geodatalab.d/<name>`. Images and pixi environments are shared per profile, so ten instances don't mean ten copies. Containers are named `geodatalab-<name>`.

## Workspace & data folders

Declare folders once and every backend shows them in the same place:

```
workspace/        -> your workspace (read-write)
data/<name>/      -> each data folder (optionally read-only)
```

```bash
./geodatalab.sh data add ccdrn /media/disk1/CCDRN --ro
./geodatalab.sh data open ccdrn      # Jupyter opens in data/ccdrn
./geodatalab.sh data                 # list
./geodatalab.sh data rm ccdrn        # forget it (files untouched)
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

```bash
./geodatalab.sh packages lab        # list a profile (with locked versions)
./geodatalab.sh build --profile institute
```

## Reproducible builds and updates

The `requirements/*.txt` files list what goes in. The lock files pin exact versions:

```bash
./geodatalab.sh lock lab     # re-resolve to latest stable, write requirements/locks/lab.lock
./geodatalab.sh build        # builds from the lock
./geodatalab.sh update       # re-lock/rebuild and restart
```

Commit the lock files (`requirements/locks/*.lock` for the image, `pixi.lock` for pixi). A build from a lock reproduces exactly what you tested.

## Modes

| Mode | Behaviour |
|------|-----------|
| `lab` | Start JupyterLab *(default)* |
| `idle` | No Jupyter. For VS Code Dev Containers or `shell`/`exec` use |

## Commands

```
start / stop / restart     Workbench lifecycle
open | url                 Open / print the JupyterLab URL (with token)
shell | exec [cmd...]      Shell / command inside the workbench
logs | status              Logs / state, config, data folders, URL

build [-p profile] [-t tag] [--no-cache]
lock [profile|all]         Pin latest versions
update                     Re-lock/rebuild and restart
images | use <tag>         Versioned images (container)
clean                      Remove image(s) / environment

backend [name]             container | pixi | nix
instances [new|rm]         Several workbenches; -i <name> <command> targets one
workspace [path]           Workspace directory
data [add|rm|open|ls]      Data folders
limits [--memory --cpus --reserve --clear]   Resource limits (container)
profile | mode | port      Build profile, startup mode, host port
packages [profile]         List packages
init | menu | help
```

## Environment variables

| Variable | Effect |
|----------|--------|
| `JUPYTER_TOKEN` | Auth token. Empty = no auth, unset = auto-generated |
| `GDL_BACKEND` | One-off backend override |
| `GDL_INSTANCE` | Same as `-i <name>` |
| `GDL_BIND` | pixi: listen address (default `127.0.0.1`) |
| `GDL_HOME` | Where the pixi binary is downloaded |
| `GDL_CONFIG` | Use another base config file |

## VS Code Dev Containers

`.devcontainer/` uses the same compose files as the CLI, so VS Code sees the same `/gdl/workspace` and `/gdl/data/<name>`. Build the image first, then **Reopen in Container**. The container runs in `idle` mode under its own name, so it can sit next to `./geodatalab.sh start`. The Python interpreter and kernels are at `/venv`.

## Build notes

- Multi-stage image: compiled in a builder stage, runtime libraries only in the final image
- SAGA and GRASS Python APIs come from Debian packages and are bridged into the venv through a targeted `.pth` (PEP 668-safe). The build fails if they can't be imported
- Smoke test: `./geodatalab.sh exec python /opt/geodatalab/smoke.py` (container) or `./geodatalab.sh exec python "$PWD/tests/smoke.py"` (pixi)
