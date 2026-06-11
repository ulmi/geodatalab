<p align="center">
  <img src="images/logo_nobg.png" width="350" alt="geodatalab">
</p>

<h1 align="center">geodatalab</h1>

<p align="center">
  Docker/Podman-based GIS Data Laboratory on <code>debian:trixie-slim</code>
</p>

---

A headless, containerised GIS workstation served through JupyterLab and [JupyterGIS](https://jupytergis.readthedocs.io). No GUI required — interact via the browser, VS Code Dev Containers, or a shell.

## Quick start

```bash
git clone https://github.com/YOUR_USERNAME/geodatalab.git
cd geodatalab

./geodatalab.sh workspace /path/to/your/data   # set workspace
./geodatalab.sh build                           # build image  (default: lab profile)
./geodatalab.sh start                           # start container, prints URL
./geodatalab.sh open                            # open JupyterLab in browser
```

Or use the interactive TUI:

```bash
./geodatalab.sh          # opens arrow-key menu
```

## Profiles

| Profile | Contents | Size |
|---------|----------|------|
| `kitchen` | Python GIS + JupyterLab + JupyterGIS + whitebox | ~1.6 GB |
| `lab` | kitchen + GRASS GIS + SAGA GIS + netCDF4 + h5py *(default)* | ~2.2 GB |
| `institute` | lab + R + Julia | ~4 GB |
| `r+julia` | JupyterLab + R + Julia only | ~2.5 GB |

```bash
./geodatalab.sh build --profile institute
./geodatalab.sh build --profile lab --tag 2025.06   # versioned tag
```

## Modes

| Mode | Behaviour |
|------|-----------|
| `server` | Start Jupyter server *(default)* |
| `lab` | Start JupyterLab with full browser UI |
| `idle` | Keep container alive, no Jupyter — for VS Code Dev Containers |

```bash
./geodatalab.sh mode lab && ./geodatalab.sh restart
```

## Commands

```
start / stop / restart     Container lifecycle
open                       Open JupyterLab in browser
shell                      Bash inside the container
exec [cmd...]              Run any command inside the container
logs                       Follow container logs
status                     State, health, image, config
url                        Print JupyterLab URL + token

build [-p profile] [-t tag] [--no-cache]
images                     List all built versions
use <tag>                  Switch active image tag
update                     Rebuild without cache

workspace [path]           Show/set workspace directory
profile [name]             Show/set build profile
mode [name]                Show/set startup mode  (idle|lab|server)
port [number]              Show/set host port  (default: 8888)
packages [profile]         List packages for a profile

init                       First-time guided setup wizard
```

## Versioned images

Each build is tagged `geodatalab:YYYY.MM-<profile>` and aliased as `geodatalab:latest`.

```bash
./geodatalab.sh build --tag 3.1 --profile lab
./geodatalab.sh images
./geodatalab.sh use 2025.06-lab
```

## Environment variables

| Variable | Effect |
|----------|--------|
| `JUPYTER_TOKEN` | Auth token — empty = no auth, unset = auto-generated |
| `GDL_PORT` | Host port override (default: `8888`, persisted in `.geodatalab`) |
| `GDL_MODE` | Startup mode override (`idle` \| `lab` \| `server`) |

```bash
JUPYTER_TOKEN=secret ./geodatalab.sh start
GDL_PORT=9999 ./geodatalab.sh start
```

## VS Code Dev Containers

`.devcontainer/devcontainer.json` is included. Build the image first, then **Reopen in Container**. The container starts in `idle` mode so VS Code manages the lifecycle. The Python interpreter and Jupyter kernels are pre-configured at `/venv`.

## Runtime

The script auto-detects **Podman** (preferred) or **Docker** and the matching compose plugin. SELinux is handled automatically via `:Z` volume labels and `label=disable`.

## Build notes

- Multi-stage build: C extensions compile in a builder stage; the final image carries only runtime libraries
- `fiona`, `shapely`, `pyproj` are not listed explicitly — they install as `geopandas` dependencies
- If a shared library error occurs after build, check that runtime lib versions match the builder (`apt-cache search libgdal`)
