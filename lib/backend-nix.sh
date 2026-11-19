# shellcheck shell=bash
# geodatalab — Nix backend (planned).
#
# Intended design, so it slots into the same interface as container/pixi:
#   * flake.nix with one devShell per profile, built from the same
#     requirements/*.txt (python3.withPackages where nixpkgs has the package,
#     a uv-managed venv on top for the rest, e.g. jupytergis/whitebox-workflows)
#   * nixpkgs ships recent GRASS *and* SAGA, so the nix backend can cover SAGA
#     without a custom conda recipe
#   * data folders reuse gdl_build_root_farm + gdl_env_kv from lib/common.sh
#   * start/stop/logs/url mirror lib/backend-pixi.sh (plain host processes)

nix_init() {
    error "The nix backend is planned but not implemented yet."
    echo  "  Switch back:  $0 backend container   (or: $0 backend pixi)" >&2
    exit 1
}

nix_is_running() { return 1; }
nix_label()      { echo "nix (planned)"; }
