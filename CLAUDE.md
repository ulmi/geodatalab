# geodatalab

Docker/Podman-based GIS Data Laboratory on `debian:trixie-slim`.

## Architecture

- **Multi-stage Dockerfile**: Builder stage compiles Python C extensions into `/venv`; final stage has runtime-only packages (no build-essential, no *-dev headers)
- **Headless**: No GUI/X11. Interaction via JupyterLab or VS Code Dev Containers
- **Profiles**: Four build profiles select which tools are installed (see below)
- **Entrypoint**: `entrypoint.sh` reads `GDL_MODE` to decide whether to start Jupyter

## GIS Stack

**Native tools (apt):** GRASS GIS, SAGA GIS (headless) — lab and institute profiles only
**Python ecosystem (pip):** varies by profile — see `requirements/`
**R + IRkernel:** institute and r+julia profiles only
**Julia + IJulia:** institute and r+julia profiles only

## Build Profiles

| Profile | Contents |
|---------|----------|
| `kitchen` | Core GIS Python stack + JupyterLab + DuckDB + whitebox |
| `lab` | kitchen + GRASS GIS + SAGA GIS + netCDF4 + h5py *(default)* |
| `institute` | lab + R + Julia + rpy2 |
| `r+julia` | JupyterLab + R + Julia (no GIS tools) |

## Modes (`GDL_MODE`)

| Mode | Behavior |
|------|----------|
| `server` | Start `jupyter server` (default) |
| `lab` | Start `jupyter lab` |
| `idle` | `sleep infinity` — for Dev Containers / exec-only use |

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage container build |
| `compose.yml` | Compose orchestration (workspace, profile, port, SELinux) |
| `entrypoint.sh` | Container entrypoint — starts Jupyter or idles based on GDL_MODE |
| `geodatalab.sh` | Control script — the only interface needed |
| `requirements/kitchen.txt` | Base Python GIS packages |
| `requirements/lab.txt` | Extends kitchen + scientific data formats |
| `requirements/institute.txt` | Extends lab + R interop (rpy2) |
| `requirements/r+julia.txt` | Minimal stack for R+Julia only |
| `.dockerignore` | Whitelist build context |
| `.devcontainer/devcontainer.json` | VS Code Dev Containers config |
| `.geodatalab` | Local config (workspace path, profile) — not committed |

## Usage

```bash
# First time
./geodatalab.sh workspace /data/projects   # set workspace
./geodatalab.sh build --profile lab        # build image
./geodatalab.sh start                      # start container, prints URL

# Daily use
./geodatalab.sh start
./geodatalab.sh stop
./geodatalab.sh shell                      # bash inside container
./geodatalab.sh logs
./geodatalab.sh status                     # state, health, size, URL
./geodatalab.sh url                        # just the Jupyter URL+token

# Interactive TUI
./geodatalab.sh menu                       # arrow-key menu

# Inspect packages
./geodatalab.sh packages [profile]         # list system + pip packages for a profile

# Maintenance
./geodatalab.sh update                     # rebuild --no-cache and restart
./geodatalab.sh clean                      # remove container + image
```

## Environment Variables

| Variable | Effect |
|----------|--------|
| `GDL_MODE` | Container mode: `server` (default), `lab`, `idle` |
| `JUPYTER_TOKEN` | Fixed auth token (empty = no auth, unset = auto-generated shown in logs) |
| `GDL_PORT` | Host port for JupyterLab (default: 8888) |

## Podman & SELinux

The script auto-detects `podman` (preferred) or `docker`. SELinux is handled via:
- Volume mount with `:Z` label (private relabeling)
- `security_opt: label=disable` in compose.yml

## VS Code Dev Containers

`.devcontainer/devcontainer.json` configures the container with `GDL_MODE=idle` so VS Code controls the lifecycle. Python interpreter and Jupyter kernels are pre-configured at `/venv`.

## Build Notes

- `fiona`, `shapely`, `pyproj` are not listed in requirements — they install automatically as `geopandas` dependencies
- Builder needs: `libgdal-dev`, `libproj-dev`, `libgeos-dev`, `libspatialindex-dev`, `libhdf5-dev`
- Final stage needs matching runtime libs: `libgdal36t64`, `libproj25`, `libgeos3.13.0`, `libhdf5-310`, `libspatialindex7`
- If a shared library error occurs after build, check that runtime lib package versions match what was linked in the builder (`apt-cache search libgdal`)
- Julia is downloaded in the builder stage and copied to `/opt/julia` in the final stage
