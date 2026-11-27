# Changelog

All notable changes to geodatalab. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); dates are when the change was made.

## v0.3 "After Hours"

### Added
- **GDL Settings** tab (far right, next to GDL Tools and GDL Activity): settings for the manager itself, for every instance.
  - **pixi environments**: in the checkout (`.pixi/envs`), pixi's cache folder, or a folder of your choice. Stored as pixi's own `detached-environments` in `.pixi/config.toml`, so a checkout on a `noexec` drive works: run `pixi config set --local detached-environments true` before the first `pixi run`. Refused while a pixi workbench runs or for a target on a `noexec` drive; instances with their own env (imported recipes) move too. The old environments show up in **Free disk space**.
  - **Container runtime**: auto, Podman or Docker (`GDL_RUNTIME` still overrides it for one run).
  - **Theme**.
  - Saved in a new `[gdl]` table in `geodatalab.toml`, which is never treated as an instance.
- **Monitor**, rebuilt:
  - CPU and memory as dot-matrix (braille) graphs side by side, for the instance only: its pixi env's processes (Jupyter, kernels and whatever they start) or everything in its container.
  - CPU in cores, scaled to the container's CPU limit or else all cores; smoothed so short blips stay small. Memory scaled to the container's memory limit or else the machine's RAM. A running instance always shows a one-dot floor.
  - **Notebooks** panel: state, CPU, memory, processes and threads of each kernel *including the processes it started* (multiprocessing, joblib). New state **background**: Jupyter reports idle while the notebook's threads or processes are still working.
  - Foldable **Processes** panel with thread counts, and foldable **Log** panel (the workbench log, live while open; **f** opens it).
- **Settings** has foldable **Container limits** (open when a limit is set) and **Data folders** panels.
- Start and Restart refuse while Settings has unsaved changes, and name the fields to save.
- After switching an instance's backend, Save says to build the new backend's env or image first.
- `CHANGELOG.md`.

### Changed
- Tabs: **Overview · Monitor · Settings** per instance, **GDL Tools · GDL Activity · GDL Settings** for the manager. The **Logs** tab moved into Monitor, the **Data** tab into Settings.
- pixi environment paths are asked from pixi (`pixi info --json`) instead of assumed under `.pixi/envs`.
- Container start only uses an image built for the instance's profile; the `geodatalab:latest` fallback applies only when it matches.
- Monitor CPU is measured from CPU-time deltas, including children that exited during the interval and processes started during it; containers use the container's own cgroup counter.

### Fixed
- Monitor showed a notebook as idle while background threads kept the CPU busy, and counted only the kernel process, not the workers it started.
- Monitor missed short-lived processes, and two monitors watching one container counted each other's sampling as load.
- A stopped instance kept showing its old CPU and memory history.
- PostGIS reported ready while the image's first-boot initialisation was still running; the health check now waits for the real server (`pg_isready -h 127.0.0.1`).
- `clean` crashed with a traceback when run without a terminal; it now does nothing and says why.
- The cleaner left pixi's empty wrapper folder behind after removing detached environments.

## Before this changelog

Up to `2c5c64c` (2026-11-25), in short:
- The bash manager (`geodatalab.sh` + `lib/*.sh`) replaced by `gdl/`, a Python package with a Textual TUI running in pixi's default environment; settings moved from `.geodatalab` to `geodatalab.toml` (converted automatically).
- Two interchangeable backends, container (Podman/Docker) and pixi; several instances per checkout; backend-independent workspace and data folders.
- Service instances from templates (PostGIS), on a shared network with `GDL_SERVICE_*` URLs.
- Free disk space, instance deletion with or without its files, recipes (export/import an instance's environment as one TOML file).
- `pixi.lock` for linux-64, osx-arm64 and win-64; GitHub Actions removed (tests run locally with `pixi run test`).
