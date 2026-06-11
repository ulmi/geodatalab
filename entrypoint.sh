#!/bin/sh
# Container startup — behaviour controlled by GDL_MODE env var:
#   idle   (default)  keep alive for VS Code Dev Containers, no Jupyter server
#   lab               start JupyterLab (browser UI + token URL)
#   server            start Jupyter server only (lighter, no Lab UI)

JUPYTER_ARGS="--ip=0.0.0.0 --port=8888 --no-browser --allow-root --ServerApp.root_dir=/workspace"

case "${GDL_MODE:-idle}" in
  lab)
    exec jupyter lab $JUPYTER_ARGS
    ;;
  server)
    exec jupyter server $JUPYTER_ARGS
    ;;
  *)
    exec sleep infinity
    ;;
esac
