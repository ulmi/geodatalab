# shellcheck shell=bash
# geodatalab — shared helpers (sourced by geodatalab.sh, never executed directly).
#
# Backend-agnostic pieces live here: logging, config, the data-folder model,
# profiles/modes and the backend dispatcher. Each backend (lib/backend-*.sh)
# implements functions named <backend>_<op>, e.g. container_start, pixi_start.

# ── Output ─────────────────────────────────────────────────────────────────────

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
BOLD=$'\033[1m'
NC=$'\033[0m'

info()    { echo -e "${GREEN}[geodatalab]${NC} $*"; }
warn()    { echo -e "${YELLOW}[geodatalab]${NC} $*"; }
error()   { echo -e "${RED}[geodatalab]${NC} $*" >&2; }
heading() { echo -e "\n${BOLD}$*${NC}"; }

# Ask a yes/no question. Default answer is $2 (Y or N). GDL_ASSUME_YES=1 answers yes.
confirm() {
    local prompt="$1" def="${2:-Y}" ans
    [[ "${GDL_ASSUME_YES:-0}" == "1" ]] && return 0
    if [[ ! -t 0 ]]; then
        [[ "$def" == "Y" ]]; return
    fi
    if [[ "$def" == "Y" ]]; then
        read -rp "  ${prompt} [Y/n] " ans
        [[ ! "$ans" =~ ^[Nn]$ ]]
    else
        read -rp "  ${prompt} [y/N] " ans
        [[ "$ans" =~ ^[Yy]$ ]]
    fi
}

# ── Paths ──────────────────────────────────────────────────────────────────────

CONFIG_FILE="${GDL_CONFIG:-${SCRIPT_DIR}/.geodatalab}"   # base config (GDL_CONFIG: alternate)
INSTANCE_DIR="${SCRIPT_DIR}/.geodatalab.d"              # named instances: overrides only
GDL_STATE_ROOT="${SCRIPT_DIR}/.gdl"                     # generated state (gitignored)
GDL_STATE_DIR=""                                        # per instance — set by gdl_apply_instance
GDL_HOME="${GDL_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/geodatalab}"  # tools (pixi binary)
GDL_PYTHON="3.13"                      # must match debian:trixie python3 (pip locks + pixi)

# ── Instances ──────────────────────────────────────────────────────────────────
# Several workbenches can run side by side from one checkout. The "default"
# instance is configured by .geodatalab. A named instance (-i NAME or
# GDL_INSTANCE=NAME) layers .geodatalab.d/NAME on top of it and stores only the
# keys that differ (plus its own port). Images and pixi environments are shared
# per profile; containers, ports, tokens, logs and the workbench layout are not.

GDL_INSTANCE="${GDL_INSTANCE:-default}"
GDL_NAME="geodatalab"                  # container / compose project name for this instance

validate_instance_name() {
    [[ "$1" =~ ^[a-z0-9][a-z0-9-]{0,30}$ && "$1" != "default" ]]
}

instance_file() { echo "${INSTANCE_DIR}/$1"; }

list_instances() {
    local f
    echo default
    for f in "${INSTANCE_DIR}"/*; do
        [[ -f "$f" ]] && basename "$f"
    done
    return 0
}

# Derive per-instance names/paths; backends add theirs via <backend>_apply_instance.
gdl_apply_instance() {
    GDL_STATE_DIR="${GDL_STATE_ROOT}/${GDL_INSTANCE}"
    if [[ "$GDL_INSTANCE" == "default" ]]; then
        GDL_NAME="geodatalab"
    else
        GDL_NAME="geodatalab-${GDL_INSTANCE}"
    fi
    local b
    for b in "${BACKENDS[@]}"; do
        if declare -F "${b}_apply_instance" >/dev/null; then "${b}_apply_instance"; fi
    done
}

# Ports configured for every instance except the current one
_other_instance_ports() {
    local n
    while IFS= read -r n; do
        [[ "$n" == "$GDL_INSTANCE" ]] && continue
        ( GDL_INSTANCE="$n"; load_config 2>/dev/null; echo "$GDL_PORT" ) || true
    done < <(list_instances)
}

# First port >= 8888 not configured by another instance and not in use
gdl_free_port() {
    local used p=8888
    used=" $(_other_instance_ports | tr '\n' ' ') "
    while [[ "$used" == *" $p "* ]] || port_open "$p"; do p=$((p + 1)); done
    echo "$p"
}

# ── Config ─────────────────────────────────────────────────────────────────────
# .geodatalab (and .geodatalab.d/*) are sourced shell files written by save_config.

CONFIG_KEYS=(BACKEND WORKSPACE PROFILE GDL_MODE GDL_PORT IMAGE_TAG GDL_OPEN
             GDL_MEMORY GDL_MEMORY_RESERVE GDL_CPUS GDL_DATA_DIRS)

_config_defaults() {
    BACKEND="container"
    WORKSPACE=""
    PROFILE="lab"
    GDL_MODE="lab"
    GDL_PORT="8888"
    IMAGE_TAG=""
    GDL_DATA_DIRS=()       # data folders: "name=/host/path" or "name=/host/path:ro"
    GDL_OPEN=""            # folder Jupyter opens in, relative to the workbench root
    GDL_MEMORY=""          # container memory limit, e.g. 56G
    GDL_MEMORY_RESERVE=""  # container memory reservation, e.g. 4G
    GDL_CPUS=""            # container CPU limit, e.g. 78
}
_config_defaults
_CFG_BACKEND=""            # backend as stored (BACKEND may be a GDL_BACKEND override)
declare -A _BASE_CFG=()    # base-config lines, to save only an instance's differences

# One "KEY=value" line for a config key
_cfg_line() {
    local k="$1" d
    case "$k" in
        GDL_DATA_DIRS)
            printf 'GDL_DATA_DIRS=('
            for d in "${GDL_DATA_DIRS[@]+"${GDL_DATA_DIRS[@]}"}"; do printf ' %q' "$d"; done
            printf ' )' ;;
        BACKEND) printf 'BACKEND=%q' "${_CFG_BACKEND:-${BACKEND:-container}}" ;;
        *)       printf '%s=%q' "$k" "${!k}" ;;
    esac
}

load_config() {
    local k
    _config_defaults
    _CFG_BACKEND=""
    # shellcheck source=/dev/null
    [[ -f "$CONFIG_FILE" ]] && source "$CONFIG_FILE"
    for k in "${CONFIG_KEYS[@]}"; do _BASE_CFG[$k]="$(_cfg_line "$k")"; done
    if [[ "$GDL_INSTANCE" != "default" ]]; then
        if ! validate_instance_name "$GDL_INSTANCE"; then
            error "Invalid instance name: ${GDL_INSTANCE}  (lowercase letters, digits, -)"
            exit 1
        fi
        if [[ ! -f "$(instance_file "$GDL_INSTANCE")" ]]; then
            error "No instance '${GDL_INSTANCE}'. Create it: $0 instances new ${GDL_INSTANCE}"
            exit 1
        fi
        # shellcheck source=/dev/null
        source "$(instance_file "$GDL_INSTANCE")"
    fi
    # Legacy values
    [[ "${GDL_MODE:-}" == "server" ]] && GDL_MODE="lab"   # JupyterLab 4: server IS lab
    [[ "${BACKEND:-}" == "mamba" ]] && BACKEND="pixi"     # mamba backend replaced by pixi
    _CFG_BACKEND="${BACKEND:-container}"
    BACKEND="${GDL_BACKEND:-$_CFG_BACKEND}"   # GDL_BACKEND env = one-off override (never saved)
    if ! validate_backend "$BACKEND"; then
        error "Unknown backend in config: ${BACKEND}  (valid: ${BACKENDS[*]})"
        exit 1
    fi
    gdl_apply_instance
}

save_config() {
    local k line
    if [[ "$GDL_INSTANCE" == "default" ]]; then
        {
            echo "# geodatalab config (default instance) — written by ./geodatalab.sh, not committed"
            for k in "${CONFIG_KEYS[@]}"; do _cfg_line "$k"; echo; done
        } > "$CONFIG_FILE"
    else
        mkdir -p "$INSTANCE_DIR"
        {
            echo "# geodatalab instance '${GDL_INSTANCE}' — only what differs from .geodatalab"
            for k in "${CONFIG_KEYS[@]}"; do
                line="$(_cfg_line "$k")"
                if [[ "$k" == "GDL_PORT" || "$line" != "${_BASE_CFG[$k]:-}" ]]; then
                    echo "$line"
                fi
            done
        } > "$(instance_file "$GDL_INSTANCE")"
    fi
}

# ── Backends ───────────────────────────────────────────────────────────────────

BACKENDS=("container" "pixi" "nix")

declare -A BACKEND_DESC=(
    [container]="Podman / Docker image  (full stack incl. SAGA)"
    [pixi]="pixi env on the host, no container  (no SAGA yet)"
    [nix]="Nix flake  (planned)"
)

validate_backend() {
    local b="$1" v
    for v in "${BACKENDS[@]}"; do [[ "$b" == "$v" ]] && return 0; done
    return 1
}

_BE_READY=""
# Dispatch an operation to the active backend: be start → ${BACKEND}_start
be() {
    local op="$1"; shift
    local fn="${BACKEND}_${op}"
    if [[ "$_BE_READY" != "$BACKEND" ]] && declare -F "${BACKEND}_init" >/dev/null; then
        "${BACKEND}_init"
        _BE_READY="$BACKEND"
    fi
    if ! declare -F "$fn" >/dev/null; then
        error "'${op}' is not available on the ${BACKEND} backend."
        exit 1
    fi
    "$fn" "$@"
}

be_has() { declare -F "${BACKEND}_$1" >/dev/null; }

# Safe to call from anywhere (no init, never exits).
gdl_is_running() {
    be_has is_running && "${BACKEND}_is_running" 2>/dev/null
}

# ── Data folders (backend-agnostic) ────────────────────────────────────────────
# Declared once in .geodatalab (GDL_DATA_DIRS), rendered by each backend into the
# same logical layout:
#     $GDL_ROOT/workspace       -> WORKSPACE
#     $GDL_ROOT/data/<name>     -> each data folder
# plus env vars GDL_ROOT, GDL_WORKSPACE, GDL_DATA, GDL_DATA_<NAME>.

# Parse one entry into _D_NAME / _D_PATH / _D_RO (0|1)
_data_parse() {
    local e="$1" rest
    _D_NAME="${e%%=*}"
    rest="${e#*=}"
    if [[ "$rest" == *:ro ]]; then _D_RO=1; _D_PATH="${rest%:ro}"; else _D_RO=0; _D_PATH="$rest"; fi
}

# Index of data folder $1 in GDL_DATA_DIRS, or -1
_data_index() {
    local i
    for i in "${!GDL_DATA_DIRS[@]}"; do
        _data_parse "${GDL_DATA_DIRS[$i]}"
        [[ "$_D_NAME" == "$1" ]] && { echo "$i"; return 0; }
    done
    echo -1
}

# GDL_DATA_<NAME> variable name for a data folder name
gdl_data_var() {
    local n="${1^^}"
    echo "GDL_DATA_${n//-/_}"
}

# Fill the global array GDL_ENV_KV with KEY=VALUE pairs for a workbench root
gdl_env_kv() {
    local root="$1" e
    GDL_ENV_KV=(
        "GDL_ROOT=${root}"
        "GDL_WORKSPACE=${root}/workspace"
        "GDL_DATA=${root}/data"
        "GDL_OPEN=${GDL_OPEN:-}"
        "GDL_PROFILE=${PROFILE:-lab}"
        "GDL_BACKEND=${BACKEND}"
        "GDL_INSTANCE=${GDL_INSTANCE}"
    )
    for e in "${GDL_DATA_DIRS[@]+"${GDL_DATA_DIRS[@]}"}"; do
        _data_parse "$e"
        GDL_ENV_KV+=("$(gdl_data_var "$_D_NAME")=${root}/data/${_D_NAME}")
    done
}

# Host-process backends (pixi, nix): materialise the layout as a symlink farm.
# Only symlinks are ever created or removed inside the farm — never real files.
gdl_build_root_farm() {
    local root="$1" l e warned=0
    mkdir -p "$root/data"
    if [[ -e "$root/workspace" && ! -L "$root/workspace" ]]; then
        error "$root/workspace exists and is not a symlink — refusing to touch it."
        exit 1
    fi
    ln -sfn "$WORKSPACE" "$root/workspace"
    for l in "$root"/data/*; do
        [[ -L "$l" ]] && unlink "$l"
    done
    for e in "${GDL_DATA_DIRS[@]+"${GDL_DATA_DIRS[@]}"}"; do
        _data_parse "$e"
        if [[ ! -d "$_D_PATH" ]]; then
            warn "Data folder '${_D_NAME}' missing: ${_D_PATH}  (linked anyway)"
        fi
        ln -sfn "$_D_PATH" "$root/data/${_D_NAME}"
        if [[ $_D_RO -eq 1 && $warned -eq 0 ]]; then
            warn "Read-only (:ro) data folders are not enforced on the ${BACKEND} backend."
            warned=1
        fi
    done
}

# ── Workspace ──────────────────────────────────────────────────────────────────

prompt_workspace() {
    heading "Workspace setup"
    echo "  The workspace appears in the workbench as  workspace/  (read-write)."
    echo "  Put your notebooks and project files there."
    echo ""
    read -rp "  Path (default: ${SCRIPT_DIR}): " ws
    ws="${ws:-${SCRIPT_DIR}}"
    ws="${ws/#\~/$HOME}"
    ws="$(realpath -m "$ws")"

    if [[ ! -d "$ws" ]]; then
        if confirm "Directory does not exist. Create it?" Y; then
            mkdir -p "$ws"
            info "Created: $ws"
        else
            warn "Workspace not created. Using: $ws"
        fi
    fi
    WORKSPACE="$ws"
    save_config
    info "Workspace set to: $WORKSPACE"
}

ensure_workspace() {
    load_config
    if [[ -z "${WORKSPACE:-}" ]]; then
        warn "No workspace configured."
        prompt_workspace
    fi
    if [[ ! -d "$WORKSPACE" ]]; then
        warn "Workspace missing: $WORKSPACE"
        if confirm "Create it?" Y; then
            mkdir -p "$WORKSPACE"
            info "Created: $WORKSPACE"
        else
            error "Workspace required. Run: $0 workspace /path"
            exit 1
        fi
    fi
}

# ── Profiles ───────────────────────────────────────────────────────────────────

PROFILES=("kitchen" "lab" "institute" "r+julia")

declare -A PROFILE_DESC=(
    [kitchen]="Python GIS + ML/spatial stats + JupyterLab + JupyterGIS + whitebox"
    [lab]="kitchen + GRASS GIS · SAGA GIS"
    [institute]="lab + R + Julia"
    [r+julia]="JupyterLab + R + Julia only"
)

declare -A PROFILE_SIZE=(
    [kitchen]="~1.9 GB"
    [lab]="~2.5 GB"
    [institute]="~4.3 GB"
    [r+julia]="~2.5 GB"
)

declare -A PROFILE_SYS=(
    [kitchen]="GDAL  PROJ  PDAL"
    [lab]="GDAL  PROJ  PDAL  GRASS GIS  SAGA GIS"
    [institute]="GDAL  PROJ  PDAL  GRASS GIS  SAGA GIS  R  Julia"
    [r+julia]="R  Julia"
)

validate_profile() {
    local p="$1" v
    for v in "${PROFILES[@]}"; do [[ "$p" == "$v" ]] && return 0; done
    return 1
}

# ── Modes ──────────────────────────────────────────────────────────────────────

MODES=("lab" "idle")

declare -A MODE_DESC=(
    [lab]="Start JupyterLab (browser UI + token URL)"
    [idle]="No Jupyter — attach via VS Code Dev Containers or use shell"
)

validate_mode() {
    local m="$1" v
    for v in "${MODES[@]}"; do [[ "$m" == "$v" ]] && return 0; done
    return 1
}

# ── Requirements ───────────────────────────────────────────────────────────────

# List packages of a requirements file (following -r). With a profile as $2,
# appends the locked version from requirements/locks/<profile>.lock.
_expand_requirements() {
    local file="$1" profile="${2:-}" line ver
    [[ -f "$file" ]] || return 0
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ -z "$line" || "$line" == \#* ]] && continue
        if [[ "$line" == -r\ * ]]; then
            _expand_requirements "${SCRIPT_DIR}/requirements/${line#-r }" "$profile"
        else
            ver=""
            [[ -n "$profile" ]] && ver="$(_locked_version "$profile" "$line")"
            if [[ -n "$ver" ]]; then printf "    • %-24s %s\n" "$line" "$ver"; else echo "    • $line"; fi
        fi
    done < "$file"
}

# Locked version of a package for a profile (container lock), or empty
_locked_version() {
    local lock="${SCRIPT_DIR}/requirements/locks/$1.lock" pkg="${2,,}"
    [[ -f "$lock" ]] || return 0
    grep -iE "^${pkg//-/[-_]}==" "$lock" | head -1 | cut -d= -f3
}

# ── Port probe ─────────────────────────────────────────────────────────────────

port_open() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}
