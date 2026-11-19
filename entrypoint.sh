#!/bin/sh
# Container startup — behaviour controlled by GDL_MODE:
#   lab   (default)  start JupyterLab
#   idle             sleep infinity — for VS Code Dev Containers / exec-only use
# ("server" is accepted as a legacy alias for lab — JupyterLab 4 *is* the server.)
#
# Layout (identical on every geodatalab backend):
#   $GDL_ROOT/workspace     workspace (read-write)
#   $GDL_ROOT/data/<name>   data folders declared with: ./geodatalab.sh data add
# GDL_OPEN (optional) is the folder, relative to GDL_ROOT, Jupyter opens in.

ROOT="${GDL_ROOT:-/gdl}"
set -- --ip=0.0.0.0 --port=8888 --no-browser --allow-root \
       "--ServerApp.root_dir=${ROOT}"
if [ -n "${GDL_OPEN:-}" ]; then
    if [ -d "${ROOT}/${GDL_OPEN}" ]; then
        set -- "$@" "--ContentsManager.preferred_dir=${GDL_OPEN}"
    else
        echo "[geodatalab] GDL_OPEN=${GDL_OPEN} not found under ${ROOT} — ignoring" >&2
    fi
fi

case "${GDL_MODE:-lab}" in
  lab|server) exec jupyter lab "$@" ;;
  *)          exec sleep infinity ;;
esac
