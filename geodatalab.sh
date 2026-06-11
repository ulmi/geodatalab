#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/.geodatalab"
COMPOSE_FILE="${SCRIPT_DIR}/compose.yml"
CONTAINER_NAME="geodatalab"
SERVICE_NAME="gis"

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

show_logo() {
    # Heredoc contains ANSI codes without their leading ESC byte (stripped by tooling).
    # sed restores ESC before every '[' so color sequences render correctly.
    local _e=$'\033'
    sed "s/\[/${_e}[/g" <<'LOGO'
   [0m[38;2;70;71;70m▄[0m[38;2;35;34;34m▄[38;2;61;60;61m[48;2;68;67;67m▀[0m[38;2;67;67;67m▄[0m[38;2;74;74;74m▄[0m
  [0m[38;2;42;42;43m▄[38;2;82;82;82m[48;2;81;81;81m▀[38;2;62;62;62m[48;2;96;96;96m▀[38;2;89;89;89m[48;2;101;101;101m▀[38;2;96;96;96m[48;2;72;72;71m▀[38;2;90;90;89m[48;2;59;59;59m▀[0m[38;2;54;54;53m▀[0m             [0m[38;2;184;147;58m▄[0m [38;2;151;137;99m[48;2;184;150;61m▀[0m
  [38;2;79;79;79m[48;2;78;77;77m▀[38;2;88;89;89m[48;2;84;84;84m▀[38;2;118;119;118m[48;2;75;75;75m▀[38;2;75;75;74m[48;2;78;75;73m▀[38;2;76;76;76m[48;2;80;52;28m▀[38;2;96;96;96m[48;2;78;56;36m▀[0m[38;2;72;83;85m▄[0m           [0m[38;2;59;69;71m▄[0m[38;2;65;56;48m▄[0m[38;2;99;62;32m▄[0m[38;2;99;83;59m▄[0m[38;2;191;151;52m▄[38;2;178;146;65m[48;2;158;138;90m▀[0m
     [38;2;60;38;20m[48;2;60;73;76m▀[38;2;82;71;55m[48;2;49;63;64m▀[38;2;68;83;82m[48;2;76;53;31m▀[38;2;61;57;46m[48;2;83;101;100m▀[38;2;54;62;64m[48;2;84;107;110m▀[0m[38;2;60;64;65m▄[0m[38;2;46;48;48m▄[0m[38;2;63;78;81m▄[0m[38;2;73;89;92m▄[0m[38;2;70;89;93m▄[0m[38;2;58;72;75m▄[0m[38;2;70;81;83m▄[0m[38;2;41;50;52m▄[0m[38;2;54;55;56m▄[38;2;46;45;46m[48;2;71;84;86m▀[38;2;46;58;59m[48;2;93;125;130m▀[38;2;73;74;66m[48;2;85;72;54m▀[38;2;78;78;68m[48;2;48;54;50m▀[38;2;82;47;18m[48;2;51;67;72m▀[0m[38;2;58;52;47m▀[0m[38;2;165;141;81m▀[0m
      [0m[38;2;40;45;46m▀[38;2;60;89;97m[48;2;47;55;57m▀[38;2;89;130;139m[48;2;61;90;99m▀[38;2;99;134;140m[48;2;93;131;140m▀[38;2;90;114;119m[48;2;99;133;141m▀[38;2;92;124;130m[48;2;95;129;137m▀[38;2;99;134;141m[48;2;68;95;102m▀[38;2;98;134;141m[48;2;75;97;104m▀[38;2;108;132;135m[48;2;66;85;90m▀[38;2;102;133;139m[48;2;75;95;101m▀[38;2;92;126;132m[48;2;70;95;102m▀[38;2;69;92;96m[48;2;80;111;118m▀[38;2;84;107;111m[48;2;99;133;140m▀[38;2;101;133;138m[48;2;98;133;140m▀[38;2;99;133;140m[48;2;79;121;131m▀[38;2;68;105;113m[48;2;48;65;69m▀[38;2;51;61;63m[48;2;67;68;69m▀[0m
       [38;2;33;33;33m[48;2;47;55;57m▀[38;2;61;81;86m[48;2;83;112;118m▀[38;2;95;132;140m[48;2;80;109;105m▀[38;2;72;100;97m[48;2;88;128;47m▀[38;2;35;79;79m[48;2;72;116;59m▀[38;2;38;98;104m[48;2;63;96;49m▀[38;2;57;103;70m[48;2;34;99;113m▀[38;2;65;103;47m[48;2;34;115;152m▀[38;2;32;105;135m[48;2;31;96;118m▀[38;2;34;114;149m[48;2;63;102;65m▀[38;2;39;99;108m[48;2;78;116;48m▀[38;2;48;83;88m[48;2;93;136;50m▀[38;2;92;125;130m[48;2;67;97;52m▀[38;2;85;125;135m[48;2;91;126;134m▀[38;2;46;54;56m[48;2;62;88;93m▀[0m
      [0m[38;2;93;93;93m▄[38;2;48;63;66m[48;2;47;62;66m▀[38;2;84;109;114m[48;2;98;133;140m▀[38;2;78;107;72m[48;2;44;84;84m▀[38;2;94;139;51m[48;2;63;105;52m▀[38;2;90;133;49m[48;2;38;99;104m▀[38;2;34;100;112m[48;2;34;118;155m▀[38;2;34;118;156m[48;2;35;118;155m▀[38;2;34;119;156m[48;2;34;118;155m▀[38;2;47;102;104m[48;2;76;120;63m▀[38;2;43;79;60m[48;2;93;137;51m▀[38;2;57;94;47m[48;2;74;116;51m▀[38;2;93;137;51m[48;2;75;112;43m▀[38;2;93;136;51m[48;2;65;111;67m▀[38;2;65;92;95m[48;2;51;79;72m▀[38;2;73;110;117m[48;2;82;124;135m▀[38;2;15;15;14m[48;2;1;0;0m▀[0m
      [0m[38;2;95;95;95m▀[38;2;53;70;74m[48;2;45;55;57m▀[38;2;87;117;123m[48;2;74;101;106m▀[38;2;38;90;112m[48;2;54;92;105m▀[38;2;33;115;151m[48;2;30;106;141m▀[38;2;55;102;78m[48;2;40;111;127m▀[38;2;74;119;59m[48;2;90;130;50m▀[38;2;41;107;112m[48;2;71;119;63m▀[38;2;34;119;155m[48;2;34;117;154m▀[38;2;52;115;101m[48;2;34;118;155m▀[38;2;67;121;81m[48;2;32;105;135m▀[38;2;93;137;51m[48;2;92;135;50m▀[38;2;63;106;57m[48;2;40;91;82m▀[38;2;30;106;141m[48;2;25;85;113m▀[38;2;40;80;93m[48;2;63;102;112m▀[38;2;78;118;128m[48;2;51;72;77m▀[38;2;3;3;3m[48;2;72;73;73m▀[0m
       [0m[38;2;13;13;13m▀[38;2;61;84;91m[48;2;47;57;60m▀[38;2;82;112;117m[48;2;80;118;130m▀[38;2;23;81;108m[48;2;66;100;110m▀[38;2;29;102;135m[48;2;29;80;103m▀[38;2;82;118;46m[48;2;37;82;72m▀[38;2;39;108;121m[48;2;29;100;132m▀[38;2;34;119;156m[48;2;30;105;139m▀[38;2;34;118;156m[48;2;29;104;137m▀[38;2;34;117;154m[48;2;28;100;132m▀[38;2;53;95;55m[48;2;26;91;120m▀[38;2;27;95;127m[48;2;37;81;98m▀[38;2;36;75;89m[48;2;64;102;112m▀[38;2;61;98;108m[48;2;55;76;82m▀[38;2;50;66;69m[48;2;52;55;56m▀[0m
         [0m[38;2;52;63;67m▀[38;2;68;102;112m[48;2;53;53;54m▀[38;2;80;124;135m[48;2;41;54;56m▀[38;2;56;92;102m[48;2;70;88;93m▀[38;2;59;88;97m[48;2;58;86;93m▀[38;2;62;84;90m[48;2;61;93;101m▀[38;2;66;87;94m[48;2;47;71;77m▀[38;2;65;89;95m[48;2;47;64;68m▀[38;2;56;92;101m[48;2;56;70;74m▀[38;2;62;95;103m[48;2;40;42;43m▀[0m[38;2;48;64;67m▀[0m[38;2;46;47;48m▀[0m
LOGO
    printf "  \033[1mgeodatalab\033[0m  \xe2\x80\x94  GIS Data Laboratory\n"
    echo
}

# ── Config ─────────────────────────────────────────────────────────────────────

WORKSPACE=""
PROFILE="lab"
GDL_MODE="server"
GDL_PORT="8888"
IMAGE_TAG=""

load_config() {
    [[ -f "$CONFIG_FILE" ]] && source "$CONFIG_FILE" || true
}

save_config() {
    cat > "$CONFIG_FILE" <<EOF
WORKSPACE="${WORKSPACE}"
PROFILE="${PROFILE}"
GDL_MODE="${GDL_MODE}"
GDL_PORT="${GDL_PORT:-8888}"
IMAGE_TAG="${IMAGE_TAG:-}"
EOF
}

# ── Image naming ───────────────────────────────────────────────────────────────
# IMAGE_TAG stores the full tag suffix, e.g. "2025.06-lab" or "latest" or "".
# Empty / "latest" both resolve to geodatalab:latest (backward-compatible).

get_image_name() {
    echo "geodatalab:${IMAGE_TAG:-latest}"
}

# ── Runtime detection ──────────────────────────────────────────────────────────

RUNTIME=""
COMPOSE=""

detect_runtime() {
    [[ -n "$RUNTIME" ]] && return
    if command -v podman &>/dev/null; then
        RUNTIME="podman"
        if podman compose version &>/dev/null 2>&1; then
            COMPOSE="podman compose"
        elif command -v podman-compose &>/dev/null; then
            COMPOSE="podman-compose"
        else
            error "podman found but no compose. Install: dnf install podman-compose"
            exit 1
        fi
    elif command -v docker &>/dev/null; then
        RUNTIME="docker"
        if docker compose version &>/dev/null 2>&1; then
            COMPOSE="docker compose"
        elif command -v docker-compose &>/dev/null; then
            COMPOSE="docker-compose"
        else
            error "docker found but no compose plugin."
            exit 1
        fi
    else
        error "No container runtime found. Install podman or docker."
        exit 1
    fi
}

compose_run() {
    WORKSPACE="${WORKSPACE:-.}" \
        PROFILE="${PROFILE:-lab}" \
        GDL_MODE="${GDL_MODE:-server}" \
        GDL_TAG="${IMAGE_TAG:-latest}" \
        GDL_PORT="${GDL_PORT:-8888}" \
        $COMPOSE -f "$COMPOSE_FILE" "$@"
}

is_running() {
    [[ "$($RUNTIME inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || echo false)" == "true" ]]
}

# Poll for container health instead of sleeping a fixed amount.
# In idle mode (no Jupyter) just waits for the running state.
_wait_healthy() {
    local timeout=60 elapsed=0 status

    if [[ "${GDL_MODE:-server}" == "idle" ]]; then
        printf "  Waiting for container"
        while ! is_running && [[ $elapsed -lt $timeout ]]; do
            printf "."; sleep 1; elapsed=$((elapsed+1))
        done
        echo ""
        return 0
    fi

    printf "  Waiting for Jupyter"
    while [[ $elapsed -lt $timeout ]]; do
        status=$($RUNTIME inspect -f '{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "")
        case "$status" in
            healthy)
                echo " ready."
                return 0
                ;;
            unhealthy)
                echo " unhealthy."
                warn "Check logs: $0 logs"
                return 1
                ;;
        esac
        printf "."; sleep 2; elapsed=$((elapsed+2))
    done
    echo ""
    warn "Still starting — check: $0 logs"
    return 0
}

# ── Workspace ──────────────────────────────────────────────────────────────────

prompt_workspace() {
    heading "Workspace setup"
    echo "  The workspace is mounted into the container at /workspace."
    echo "  Put your data, notebooks and project files there."
    echo ""
    read -rp "  Path (default: ${SCRIPT_DIR}): " ws
    ws="${ws:-${SCRIPT_DIR}}"
    ws="${ws/#\~/$HOME}"
    ws="$(realpath -m "$ws")"

    if [[ ! -d "$ws" ]]; then
        read -rp "  Directory does not exist. Create it? [Y/n] " create
        if [[ ! "$create" =~ ^[Nn]$ ]]; then
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
        read -rp "  Create it? [Y/n] " create
        if [[ ! "$create" =~ ^[Nn]$ ]]; then
            mkdir -p "$WORKSPACE"
            info "Created: $WORKSPACE"
        else
            error "Workspace required. Run: $0 workspace /path"
            exit 1
        fi
    fi
}

cmd_workspace() {
    load_config
    if [[ -n "${1:-}" ]]; then
        local ws="${1/#\~/$HOME}"
        ws="$(realpath -m "$ws")"
        if [[ ! -d "$ws" ]]; then
            read -rp "  Directory does not exist. Create it? [Y/n] " create
            if [[ ! "$create" =~ ^[Nn]$ ]]; then
                mkdir -p "$ws"
                info "Created: $ws"
            fi
        fi
        WORKSPACE="$ws"
        save_config
        info "Workspace set to: $WORKSPACE"
    else
        heading "Workspace"
        if [[ -n "${WORKSPACE:-}" ]]; then
            echo "  Path:   $WORKSPACE"
            [[ -d "$WORKSPACE" ]] \
                && echo -e "  Status: ${GREEN}exists${NC}" \
                || echo -e "  Status: ${RED}missing${NC}"
        else
            echo "  Not configured. Run: $0 workspace /path"
        fi
    fi
}

# ── Profiles ───────────────────────────────────────────────────────────────────

PROFILES=("kitchen" "lab" "institute" "r+julia")

declare -A PROFILE_DESC=(
    [kitchen]="Python GIS + JupyterLab + JupyterGIS + whitebox"
    [lab]="kitchen + GRASS GIS · SAGA GIS"
    [institute]="lab + R + Julia"
    [r+julia]="JupyterLab + R + Julia only"
)

declare -A PROFILE_SIZE=(
    [kitchen]="~1.6 GB"
    [lab]="~2.2 GB"
    [institute]="~4 GB"
    [r+julia]="~2.5 GB"
)

declare -A PROFILE_SYS=(
    [kitchen]="GDAL  PROJ"
    [lab]="GDAL  PROJ  GRASS GIS  SAGA GIS"
    [institute]="GDAL  PROJ  GRASS GIS  SAGA GIS  R  Julia"
    [r+julia]="R  Julia"
)

validate_profile() {
    local p="$1"
    for v in "${PROFILES[@]}"; do [[ "$p" == "$v" ]] && return 0; done
    return 1
}

cmd_profile() {
    load_config
    if [[ -n "${1:-}" ]]; then
        if ! validate_profile "$1"; then
            error "Invalid profile: $1  (valid: ${PROFILES[*]})"
            exit 1
        fi
        PROFILE="$1"
        save_config
        info "Profile set to: $PROFILE"
        warn "Rebuild required to take effect: $0 build"
    else
        heading "Build profiles"
        for p in "${PROFILES[@]}"; do
            if [[ "$p" == "${PROFILE:-lab}" ]]; then
                echo -e "  ${GREEN}* ${BOLD}${p}${NC}${GREEN}  —  ${PROFILE_DESC[$p]}  (${PROFILE_SIZE[$p]})${NC}"
            else
                echo "    ${p}  —  ${PROFILE_DESC[$p]}  (${PROFILE_SIZE[$p]})"
            fi
        done
        echo ""
        echo "  Change with: $0 profile <name>"
        echo "  Requires rebuild to take effect."
    fi
}

# ── Modes ──────────────────────────────────────────────────────────────────────

MODES=("idle" "lab" "server")

declare -A MODE_DESC=(
    [idle]="Container alive, no Jupyter server — attach via VSCode Dev Containers"
    [lab]="Start JupyterLab (browser UI + token URL)"
    [server]="Start Jupyter server only (no Lab UI, lighter than lab)"
)

validate_mode() {
    local m="$1"
    for v in "${MODES[@]}"; do [[ "$m" == "$v" ]] && return 0; done
    return 1
}

cmd_mode() {
    load_config
    if [[ -n "${1:-}" ]]; then
        if ! validate_mode "$1"; then
            error "Invalid mode: $1  (valid: ${MODES[*]})"
            exit 1
        fi
        GDL_MODE="$1"
        save_config
        info "Mode set to: $GDL_MODE"
        if is_running 2>/dev/null; then
            warn "Restart the container to apply: $0 restart"
        fi
    else
        heading "Startup mode"
        for m in "${MODES[@]}"; do
            if [[ "$m" == "${GDL_MODE:-server}" ]]; then
                echo -e "  ${GREEN}* ${BOLD}${m}${NC}${GREEN}  —  ${MODE_DESC[$m]}${NC}"
            else
                echo "    ${m}  —  ${MODE_DESC[$m]}"
            fi
        done
        echo ""
        echo "  Change with: $0 mode <name>"
        echo "  Requires restart to take effect."
    fi
}

# ── Port ───────────────────────────────────────────────────────────────────────

cmd_port() {
    load_config
    if [[ -n "${1:-}" ]]; then
        if ! [[ "$1" =~ ^[0-9]+$ ]] || [[ "$1" -lt 1024 || "$1" -gt 65535 ]]; then
            error "Invalid port: $1  (must be 1024–65535)"
            exit 1
        fi
        GDL_PORT="$1"
        save_config
        info "Port set to: $GDL_PORT"
        if is_running 2>/dev/null; then
            warn "Restart to apply: $0 restart"
        fi
    else
        heading "Host port"
        echo "  Port: ${GDL_PORT:-8888}"
        echo ""
        echo "  Change with: $0 port <number>"
        echo "  Requires restart to take effect."
    fi
}

# ── Image / version management ─────────────────────────────────────────────────

cmd_images() {
    detect_runtime
    load_config
    heading "geodatalab images"
    local active="${IMAGE_TAG:-latest}"
    local found=0

    while IFS=' ' read -r tag size created_rest; do
        [[ -z "$tag" ]] && continue
        found=1
        if [[ "$tag" == "$active" ]]; then
            echo -e "  ${GREEN}${BOLD}* ${tag}${NC}${GREEN}  ${size}  (${created_rest})${NC}"
        else
            echo    "    ${tag}  ${size}  (${created_rest})"
        fi
    done < <($RUNTIME images --filter "reference=geodatalab" \
        --format "{{.Tag}} {{.Size}} {{.CreatedSince}}" 2>/dev/null \
        | sort -t'-' -k1,1Vr || true)

    [[ $found -eq 0 ]] && echo "  None found."
    echo ""
    echo -e "  Active: ${BLUE}geodatalab:${active}${NC}"
    echo    "  Switch: $0 use <tag>"
}

cmd_use() {
    load_config
    local tag="${1:-}"
    if [[ -z "$tag" ]]; then
        detect_runtime
        cmd_images
        echo ""
        read -rp "  Tag to activate: " tag
        [[ -z "$tag" ]] && return 0
    fi
    IMAGE_TAG="$tag"
    # Sync PROFILE if the tag encodes a known profile suffix
    local p
    for p in "${PROFILES[@]}"; do
        if [[ "$tag" == *"-${p}" ]]; then
            PROFILE="$p"
            break
        fi
    done
    save_config
    info "Active image: geodatalab:${IMAGE_TAG}"
    [[ "${PROFILE}" ]] && info "Profile synced to: ${PROFILE}"
}

# ── Build ──────────────────────────────────────────────────────────────────────

cmd_build() {
    detect_runtime
    load_config
    local build_profile="${PROFILE:-lab}"
    local build_tag=""
    local extra_args=()

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --profile|-p)
                shift
                if ! validate_profile "${1:-}"; then
                    error "Invalid profile: ${1:-}  (valid: ${PROFILES[*]})"
                    exit 1
                fi
                build_profile="$1"; shift
                ;;
            --tag|-t)
                shift
                build_tag="${1:-}"; shift
                ;;
            --no-cache)
                extra_args+=("--no-cache"); shift
                ;;
            *) extra_args+=("$1"); shift ;;
        esac
    done

    # Default version: YYYY.MM
    [[ -z "$build_tag" ]] && build_tag="$(date +%Y.%m)"

    local versioned_tag="${build_tag}-${build_profile}"
    local versioned_image="geodatalab:${versioned_tag}"

    info "Building  [profile: ${build_profile}, tag: ${versioned_tag}]..."
    WORKSPACE="${WORKSPACE:-.}" \
        PROFILE="$build_profile" \
        GDL_MODE="${GDL_MODE:-server}" \
        GDL_TAG="$versioned_tag" \
        GDL_PORT="${GDL_PORT:-8888}" \
        $COMPOSE -f "$COMPOSE_FILE" build "${extra_args[@]+"${extra_args[@]}"}"

    # Also tag as latest
    if $RUNTIME tag "$versioned_image" "geodatalab:latest" 2>/dev/null; then
        info "Tagged as geodatalab:latest"
    fi

    # Update config to use newly built image
    IMAGE_TAG="$versioned_tag"
    PROFILE="$build_profile"
    save_config

    info "Build complete: ${versioned_image}"
    $RUNTIME images --filter "reference=geodatalab" \
        --format "  {{.Tag}}  {{.Size}}" 2>/dev/null | head -8 || true
}

# ── Container commands ─────────────────────────────────────────────────────────

cmd_start() {
    detect_runtime
    load_config
    ensure_workspace

    if is_running; then
        warn "Already running."
        [[ "${GDL_MODE:-server}" != "idle" ]] && cmd_url
        return
    fi

    local image
    image=$(get_image_name)

    if ! $RUNTIME inspect --type image "$image" &>/dev/null; then
        # Graceful fallback: if a versioned tag is set but missing, try latest
        if [[ "${IMAGE_TAG:-latest}" != "latest" ]] && \
           $RUNTIME inspect --type image "geodatalab:latest" &>/dev/null; then
            warn "Image ${image} not found — falling back to geodatalab:latest"
            IMAGE_TAG="latest"
            image="geodatalab:latest"
        else
            error "Image not found: ${image}"
            echo  "  Build it:  $0 build --profile ${PROFILE:-lab}"
            exit 1
        fi
    fi

    info "Starting  [image: ${image}, mode: ${GDL_MODE:-server}, port: ${GDL_PORT:-8888}]..."
    compose_run up -d
    echo ""
    _wait_healthy

    if [[ "${GDL_MODE:-server}" == "idle" ]]; then
        echo ""
        echo "  Container running in idle mode — no Jupyter server."
        echo "  Attach with VSCode Dev Containers, or open a shell: $0 shell"
        echo ""
        echo "  To start JupyterLab: $0 mode lab && $0 restart"
    else
        echo ""
        cmd_url
    fi
}

cmd_stop() {
    detect_runtime
    load_config
    info "Stopping container..."
    compose_run stop
    info "Stopped."
}

cmd_restart() {
    cmd_stop
    cmd_start
}

# Run an arbitrary command in the container.
# With no arguments opens an interactive bash shell (same behaviour as old `shell`).
cmd_exec() {
    detect_runtime
    load_config
    if ! is_running; then
        error "Container not running. Start it first: $0 start"
        exit 1
    fi
    if [[ $# -eq 0 ]]; then
        $RUNTIME exec -it "$CONTAINER_NAME" bash
    else
        $RUNTIME exec -it "$CONTAINER_NAME" "$@"
    fi
}

# Kept as alias so existing muscle memory works.
cmd_shell() { cmd_exec; }

cmd_logs() {
    detect_runtime
    load_config
    compose_run logs -f "$SERVICE_NAME"
}

_get_url_raw() {
    local port="${GDL_PORT:-8888}"
    local token=""
    if [[ -n "${JUPYTER_TOKEN:-}" ]]; then
        token="$JUPYTER_TOKEN"
    elif is_running; then
        token=$($RUNTIME logs "$CONTAINER_NAME" 2>&1 \
            | grep -oP '(?<=token=)[a-f0-9]+' | tail -1 || true)
    fi
    if [[ -n "$token" ]]; then
        echo "http://localhost:${port}/lab?token=${token}"
    else
        echo "http://localhost:${port}/lab"
    fi
}

cmd_url() {
    detect_runtime
    load_config
    if [[ "${GDL_MODE:-server}" == "idle" ]]; then
        echo "  Container is in idle mode — no Jupyter server running."
        echo "  Switch modes: $0 mode lab && $0 restart"
        return
    fi
    local url
    url=$(_get_url_raw)
    echo -e "  ${BLUE}${url}${NC}"
    if [[ -z "${JUPYTER_TOKEN:-}" ]] && ! is_running; then
        echo "  (token visible in: $0 logs)"
    fi
}

cmd_open() {
    detect_runtime
    load_config
    if [[ "${GDL_MODE:-server}" == "idle" ]]; then
        error "Container is in idle mode — no Jupyter server running."
        exit 1
    fi
    if ! is_running; then
        error "Container not running. Start it first: $0 start"
        exit 1
    fi
    local url
    url=$(_get_url_raw)
    if command -v xdg-open &>/dev/null; then
        xdg-open "$url" &>/dev/null &
        info "Opening: $url"
    elif command -v open &>/dev/null; then
        open "$url"
        info "Opening: $url"
    else
        info "$url"
        warn "No browser launcher found (xdg-open / open). Copy the URL above."
    fi
}

cmd_status() {
    detect_runtime
    load_config

    heading "Container"
    if is_running; then
        local health started
        health=$($RUNTIME inspect -f '{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "n/a")
        started=$($RUNTIME inspect -f '{{.State.StartedAt}}' "$CONTAINER_NAME" 2>/dev/null || echo "n/a")
        echo -e "  State:    ${GREEN}running${NC}"
        echo    "  Health:   ${health}"
        echo    "  Started:  ${started}"
    else
        echo -e "  State:    ${RED}stopped${NC}"
    fi

    heading "Images"
    $RUNTIME images --filter "reference=geodatalab" \
        --format "  {{.Tag}}  {{.Size}}  (created {{.CreatedSince}})" \
        2>/dev/null || echo "  None built yet."

    heading "Configuration"
    echo "  Workspace:  ${WORKSPACE:-not set}"
    echo "  Profile:    ${PROFILE:-lab}"
    echo "  Mode:       ${GDL_MODE:-server}"
    echo "  Port:       ${GDL_PORT:-8888}"
    echo "  Active tag: ${IMAGE_TAG:-latest}"
    echo "  Runtime:    ${RUNTIME} (${COMPOSE})"

    if is_running && [[ "${GDL_MODE:-server}" != "idle" ]]; then
        heading "URL"
        cmd_url
    fi
}

# ── Packages ───────────────────────────────────────────────────────────────────

_expand_requirements() {
    local file="$1"
    [[ -f "$file" ]] || return
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ -z "$line" || "$line" == \#* ]] && continue
        if [[ "$line" == -r\ * ]]; then
            _expand_requirements "${SCRIPT_DIR}/requirements/${line#-r }"
        else
            echo "    • $line"
        fi
    done < "$file"
}

cmd_packages() {
    load_config
    local target="${1:-all}"

    _show_profile() {
        local p="$1"
        local req="${SCRIPT_DIR}/requirements/${p}.txt"
        heading "  ${p}  —  ${PROFILE_DESC[$p]}"
        echo -e "  ${BOLD}System:${NC}  ${PROFILE_SYS[$p]}"
        echo -e "  ${BOLD}Python:${NC}"
        if [[ -f "$req" ]]; then
            _expand_requirements "$req"
        else
            echo "    (requirements file not found)"
        fi
    }

    if [[ "$target" == "all" ]]; then
        show_logo
        for p in "${PROFILES[@]}"; do
            _show_profile "$p"
            echo ""
        done
    else
        if ! validate_profile "$target"; then
            error "Invalid profile: $target  (valid: ${PROFILES[*]})"
            exit 1
        fi
        show_logo
        _show_profile "$target"
        echo ""
    fi
}

# ── Clean / Update ─────────────────────────────────────────────────────────────

cmd_clean() {
    detect_runtime
    load_config
    echo -e "${YELLOW}This will remove the container and all geodatalab images.${NC}"
    read -rp "Are you sure? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        compose_run down --rmi local --volumes 2>/dev/null || true
        info "Cleaned."
    else
        info "Cancelled."
    fi
}

cmd_update() {
    detect_runtime
    load_config
    local build_tag
    build_tag="$(date +%Y.%m)"
    local versioned_tag="${build_tag}-${PROFILE:-lab}"
    info "Rebuilding image (no cache)  [tag: ${versioned_tag}]..."
    WORKSPACE="${WORKSPACE:-.}" \
        PROFILE="${PROFILE:-lab}" \
        GDL_MODE="${GDL_MODE:-server}" \
        GDL_TAG="$versioned_tag" \
        GDL_PORT="${GDL_PORT:-8888}" \
        $COMPOSE -f "$COMPOSE_FILE" build --no-cache
    $RUNTIME tag "geodatalab:${versioned_tag}" "geodatalab:latest" 2>/dev/null || true
    IMAGE_TAG="$versioned_tag"
    save_config
    if is_running; then
        info "Restarting with new image..."
        compose_run up -d
    fi
    info "Update complete."
    $RUNTIME images --filter "reference=geodatalab" \
        --format "  {{.Tag}}  {{.Size}}" 2>/dev/null | head -8 || true
}

# ── Init wizard ────────────────────────────────────────────────────────────────

cmd_init() {
    detect_runtime
    load_config

    clear; show_logo
    echo -e "  ${BOLD}Welcome to geodatalab — first-time setup${NC}"
    echo    "  This wizard will configure your environment."
    echo ""

    # Workspace
    prompt_workspace
    echo ""

    # Profile
    if _pick_profile "Select a build profile"; then
        PROFILE="$_PICKED_PROFILE"
        save_config
    fi

    # Mode
    local mode_opts=(
        "server  —  ${MODE_DESC[server]}"
        "lab     —  ${MODE_DESC[lab]}"
        "idle    —  ${MODE_DESC[idle]}"
    )
    echo ""
    if _pick_from_list "Select startup mode" "${mode_opts[@]}"; then
        case $PICKED_IDX in
            0) GDL_MODE=server ;; 1) GDL_MODE=lab ;; 2) GDL_MODE=idle ;;
        esac
        save_config
    fi

    # Port
    echo ""
    read -rp "  Host port [${GDL_PORT:-8888}]: " p
    if [[ -n "${p:-}" ]]; then
        cmd_port "$p"
    fi

    echo ""
    info "Configuration saved."
    echo ""
    read -rp "  Build the image now? [Y/n] " yn
    if [[ ! "${yn:-}" =~ ^[Nn]$ ]]; then
        echo ""
        cmd_build
        echo ""
        read -rp "  Start the container now? [Y/n] " yn2
        if [[ ! "${yn2:-}" =~ ^[Nn]$ ]]; then
            echo ""
            cmd_start
        fi
    fi
}

# ── Help ───────────────────────────────────────────────────────────────────────

cmd_help() {
    show_logo
    cat <<EOF
${BOLD}Usage:${NC}
  ./geodatalab.sh <command> [options]

${BOLD}Container:${NC}
  start                          Start the container
  stop                           Stop the container
  restart                        Restart the container
  open                           Open JupyterLab in the browser
  shell                          Open an interactive bash shell
  exec [cmd...]                  Run a command inside the container
  logs                           Follow container logs
  status                         Show container, image and config info
  url                            Print the JupyterLab URL with token

${BOLD}Build / images:${NC}
  build [-p <profile>] [-t <tag>] [--no-cache]
                                 Build the image
  images                         List all built geodatalab images
  use [tag]                      Switch the active image tag
  update                         Rebuild without cache and restart
  clean                          Remove container and image(s)

${BOLD}Configuration:${NC}
  init                           First-time guided setup wizard
  workspace [path]               Show or set the workspace directory
  profile [name]                 Show or set the build profile
  mode [name]                    Show or set the startup mode
  port [number]                  Show or set the host port  (default: 8888)
  packages [profile|all]         List packages included in a profile

${BOLD}Interactive TUI:${NC}
  menu                           Arrow-key menu (default when called with no args)

${BOLD}Startup modes:${NC}
  idle    ${MODE_DESC[idle]}
  lab     ${MODE_DESC[lab]}
  server  ${MODE_DESC[server]}

${BOLD}Profiles:${NC}
  kitchen    ${PROFILE_DESC[kitchen]}
  lab        ${PROFILE_DESC[lab]}  [default]
  institute  ${PROFILE_DESC[institute]}
  r+julia    ${PROFILE_DESC[r+julia]}

${BOLD}Versioned images:${NC}
  Each build is tagged  geodatalab:YYYY.MM-<profile>  and aliased as  geodatalab:latest
  Custom tag:  ./geodatalab.sh build --tag 3.1 --profile lab
  List:        ./geodatalab.sh images
  Switch:      ./geodatalab.sh use 2025.05-lab

${BOLD}Environment variables:${NC}
  JUPYTER_TOKEN   Auth token (empty = no auth, unset = auto-generated)
  GDL_PORT        Host port override  (default: 8888, persisted in .geodatalab)
  GDL_MODE        Mode override  (idle|lab|server)

${BOLD}Examples:${NC}
  ./geodatalab.sh init
  ./geodatalab.sh workspace /data/projects
  ./geodatalab.sh build --profile institute
  ./geodatalab.sh build --tag 3.1 --profile lab
  ./geodatalab.sh start && ./geodatalab.sh open
  ./geodatalab.sh images
  ./geodatalab.sh use 2025.05-lab
  ./geodatalab.sh exec python3 -c "import geopandas; print('ok')"
  ./geodatalab.sh mode lab && ./geodatalab.sh restart
  JUPYTER_TOKEN=secret ./geodatalab.sh start
EOF
}

# ── Interactive menu ───────────────────────────────────────────────────────────

_pick_from_list() {
    local title="$1"; shift
    local -a items=("$@")
    local n=${#items[@]}
    local sel=0 key esc

    while true; do
        clear
        show_logo
        echo -e "  ${BOLD}${title}${NC}\n"
        local i
        for ((i=0; i<n; i++)); do
            if [[ $i -eq $sel ]]; then
                echo -e "  ${GREEN}${BOLD}▶ ${items[$i]}${NC}"
            else
                echo    "    ${items[$i]}"
            fi
        done
        echo ""
        echo "  ↑↓ navigate  ·  Enter select  ·  Esc / q  back"

        IFS= read -r -s -n1 key
        if [[ $key == $'\033' ]]; then
            IFS= read -r -s -n2 -t0.1 esc || esc=""
            key="${key}${esc}"
        fi
        case "$key" in
            $'\033[A'|k) [[ $sel -gt 0 ]]        && sel=$((sel-1)) ;;
            $'\033[B'|j) [[ $sel -lt $((n-1)) ]] && sel=$((sel+1)) ;;
            ''|$'\n')
                PICKED_IDX=$sel
                PICKED_VAL="${items[$sel]}"
                return 0
                ;;
            $'\033'|q|Q) return 1 ;;
        esac
    done
}

_pick_profile() {
    local title="$1"
    local -a pnames=("kitchen" "lab" "institute" "r+julia")
    local -a labels=(
        "kitchen    —  ${PROFILE_DESC[kitchen]}  (${PROFILE_SIZE[kitchen]})"
        "lab        —  ${PROFILE_DESC[lab]}  (${PROFILE_SIZE[lab]})"
        "institute  —  ${PROFILE_DESC[institute]}  (${PROFILE_SIZE[institute]})"
        "r+julia    —  ${PROFILE_DESC[r+julia]}  (${PROFILE_SIZE[r+julia]})"
    )
    local n=${#labels[@]} sel=0 key esc

    while true; do
        clear; show_logo
        echo -e "  ${BOLD}${title}${NC}\n"
        local i
        for ((i=0; i<n; i++)); do
            if [[ $i -eq $sel ]]; then
                echo -e "  ${GREEN}${BOLD}▶ ${labels[$i]}${NC}"
            else
                echo    "    ${labels[$i]}"
            fi
        done
        echo ""
        echo "  ↑↓ navigate  ·  Enter select  ·  p view packages  ·  Esc / q  back"

        IFS= read -r -s -n1 key
        if [[ $key == $'\033' ]]; then
            IFS= read -r -s -n2 -t0.1 esc || esc=""
            key="${key}${esc}"
        fi
        case "$key" in
            $'\033[A'|k) [[ $sel -gt 0 ]]        && sel=$((sel-1)) ;;
            $'\033[B'|j) [[ $sel -lt $((n-1)) ]] && sel=$((sel+1)) ;;
            p|P)
                clear
                cmd_packages "${pnames[$sel]}"
                echo ""
                echo -e "  ${BOLD}Press any key to return...${NC}"
                IFS= read -r -s -n1
                ;;
            ''|$'\n')
                _PICKED_PROFILE="${pnames[$sel]}"
                return 0
                ;;
            $'\033'|q|Q) return 1 ;;
        esac
    done
}

_menu_build() {
    _pick_profile "Build image — select profile  (current: ${PROFILE:-lab})" || return 0
    clear; show_logo
    read -rp "  Version tag [$(date +%Y.%m)]: " vtag
    vtag="${vtag:-$(date +%Y.%m)}"
    cmd_build --tag "$vtag" --profile "$_PICKED_PROFILE"
}

_menu_select_profile() {
    _pick_profile "Set build profile  (current: ${PROFILE:-lab})" || return 0
    clear; show_logo
    cmd_profile "$_PICKED_PROFILE"
}

_menu_select_mode() {
    local opts=(
        "idle    —  ${MODE_DESC[idle]}"
        "lab     —  ${MODE_DESC[lab]}"
        "server  —  ${MODE_DESC[server]}"
    )
    _pick_from_list "Set startup mode  (current: ${GDL_MODE:-server})" \
        "${opts[@]}" || return 0
    clear; show_logo
    case $PICKED_IDX in
        0) cmd_mode idle ;; 1) cmd_mode lab ;; 2) cmd_mode server ;;
    esac
    if is_running 2>/dev/null; then
        echo ""
        read -rp "  Restart now to apply? [Y/n] " yn
        [[ ! "$yn" =~ ^[Nn]$ ]] && cmd_restart || true
    fi
}

_menu_workspace() {
    clear; show_logo
    echo -e "  ${BOLD}Workspace${NC}\n"
    if [[ -n "${WORKSPACE:-}" ]]; then
        echo "  Current: ${WORKSPACE}"
        [[ -d "$WORKSPACE" ]] \
            && echo -e "  Status:  ${GREEN}exists${NC}" \
            || echo -e "  Status:  ${RED}missing${NC}"
    else
        echo -e "  Current: ${YELLOW}not set${NC}"
    fi
    echo ""
    read -rp "  New path (leave empty to keep, '-' to unset): " ws
    [[ -z "$ws" ]] && return 0
    if [[ "$ws" == "-" ]]; then
        WORKSPACE=""
        save_config
        info "Workspace unset."
        sleep 1
        return 0
    fi
    ws="${ws/#\~/$HOME}"
    ws="$(realpath -m "$ws")"
    if [[ ! -d "$ws" ]]; then
        read -rp "  Directory does not exist. Create it? [Y/n] " create
        if [[ ! "$create" =~ ^[Nn]$ ]]; then
            mkdir -p "$ws"
            info "Created: $ws"
        fi
    fi
    WORKSPACE="$ws"
    save_config
    info "Workspace set to: $WORKSPACE"
    sleep 1
}

_menu_port() {
    load_config
    clear; show_logo
    echo -e "  ${BOLD}Host port${NC}\n"
    echo    "  Current: ${GDL_PORT:-8888}"
    echo ""
    read -rp "  New port (1024–65535, empty to keep): " p
    if [[ -n "${p:-}" ]]; then
        cmd_port "$p"
        sleep 1
    fi
}


_menu_images() {
    load_config
    clear; show_logo
    cmd_images
    echo ""
    read -rp "  Tag to activate (empty to keep current): " tag
    if [[ -n "${tag:-}" ]]; then
        cmd_use "$tag"
        sleep 1
    fi
}

cmd_menu() {
    detect_runtime
    load_config

    # ── Cached state (updated at start and after each action) ─────────────────
    local _cache_running=false _cache_health=""

    _refresh_status() {
        if is_running 2>/dev/null; then
            _cache_running=true
            _cache_health=$($RUNTIME inspect -f '{{.State.Health.Status}}' \
                "$CONTAINER_NAME" 2>/dev/null || echo "")
        else
            _cache_running=false
            _cache_health=""
        fi
    }

    # ── Common header: logo + status block ────────────────────────────────────
    # Pure echo — no subprocess calls, so navigation never flickers.
    _draw_header() {
        clear
        show_logo
        load_config
        local _hstr=""
        case "$_cache_health" in
            healthy)   _hstr="  ${GREEN}healthy${NC}" ;;
            unhealthy) _hstr="  ${RED}unhealthy${NC}" ;;
            starting)  _hstr="  ${YELLOW}starting${NC}" ;;
        esac
        echo -e "  ${BOLD}── Container status${NC}"
        if [[ "$_cache_running" == true ]]; then
            echo -e "  ${GREEN}●${NC} running${_hstr:+  ·${_hstr}}  ·  $(get_image_name)  ·  :${GDL_PORT:-8888}"
        else
            echo -e "  ${RED}○${NC} stopped  ·  $(get_image_name)"
        fi
        echo ""
    }

    # ── Action executor (shared by all submenus) ──────────────────────────────
    _run_action() {
        local action="$1"
        tput cnorm 2>/dev/null || true
        clear; show_logo

        case "$action" in
            logs|shell) trap 'true' INT ;;
        esac

        local _pause=0
        case "$action" in
            shell)
                if is_running; then
                    cmd_shell || true
                else
                    echo ""; error "Container is not running."
                    echo "  Select  Start  from the menu first."; _pause=1
                fi ;;
            logs)      cmd_logs || true ;;
            start)     ( cmd_start   ) || true; _pause=1 ;;
            stop)      ( cmd_stop    ) || true; _pause=1 ;;
            restart)   ( cmd_restart ) || true; _pause=1 ;;
            open)      ( cmd_open    ) || true; _pause=1 ;;
            status)    ( cmd_status  ) || true; _pause=1 ;;
            url)       ( cmd_url     ) || true; _pause=1 ;;
            build)     ( _menu_build ) || true; _pause=1 ;;
            images)    _menu_images ;;
            update)    ( cmd_update  ) || true; _pause=1 ;;
            clean)     ( cmd_clean   ) || true ;;
            workspace) _menu_workspace ;;
            profile)   _menu_select_profile || true ;;
            mode)      _menu_select_mode || true ;;
            port)      _menu_port ;;
        esac

        if [[ $_pause -eq 1 ]]; then
            echo ""
            echo -e "  ${BOLD}Press any key to return...${NC}"
            IFS= read -r -s -n1
        fi

        _refresh_status
        load_config
        trap 'tput cnorm 2>/dev/null || true; echo' INT
        tput civis 2>/dev/null || true
    }

    # ── Generic submenu ────────────────────────────────────────────────────────
    # Args: title label1 action1 label2 action2 ...
    _submenu() {
        local title="$1"; shift
        local -a _items=("$@")
        local _count=$(( ${#_items[@]} / 2 ))
        local _sel=0 _key _esc

        while true; do
            _draw_header
            echo -e "  ${BOLD}↑↓${NC} navigate  ${BOLD}Enter${NC} select  ${BOLD}Esc / q${NC} back\n"
            echo -e "  ${BOLD}── ${title}${NC}\n"
            local _i
            for ((_i=0; _i<_count; _i++)); do
                local _lbl="${_items[$((_i*2))]}"
                if [[ $_i -eq $_sel ]]; then
                    echo -e "  ${GREEN}${BOLD}▶${_lbl}${NC}"
                else
                    echo    "   ${_lbl}"
                fi
            done

            IFS= read -r -s -n1 _key
            if [[ $_key == $'\033' ]]; then
                IFS= read -r -s -n2 -t0.1 _esc || _esc=""
                _key="${_key}${_esc}"
            fi
            case "$_key" in
                $'\033[A'|k) [[ $_sel -gt 0 ]] && _sel=$((_sel-1)) ;;
                $'\033[B'|j) [[ $_sel -lt $((_count-1)) ]] && _sel=$((_sel+1)) ;;
                $'\033'|q|Q) return 0 ;;
                ''|$'\n')
                    _run_action "${_items[$((_sel*2+1))]}"
                    ;;
            esac
        done
    }

    # ── Top-level menu ─────────────────────────────────────────────────────────
    local -a _top_labels=("  Container" "  Build" "  Configuration" "  Help" "  Exit")
    local -a _top_cats=("container"    "build"   "configuration"    "help"  "exit")
    local _n=${#_top_labels[@]}
    local _sel=0 _key _esc

    _refresh_status
    tput civis 2>/dev/null || true
    trap 'tput cnorm 2>/dev/null || true; echo' EXIT INT TERM

    while true; do
        _draw_header
        echo -e "  ${BOLD}↑↓${NC} navigate  ${BOLD}Enter${NC} select  ${BOLD}q${NC} quit\n"
        local _i
        for ((_i=0; _i<_n; _i++)); do
            if [[ $_i -eq $_sel ]]; then
                echo -e "  ${GREEN}${BOLD}▶${_top_labels[$_i]}${NC}"
            else
                echo    "   ${_top_labels[$_i]}"
            fi
        done

        IFS= read -r -s -n1 _key
        if [[ $_key == $'\033' ]]; then
            IFS= read -r -s -n2 -t0.1 _esc || _esc=""
            _key="${_key}${_esc}"
        fi
        case "$_key" in
            $'\033[A'|k) [[ $_sel -gt 0 ]] && _sel=$((_sel-1)) ;;
            $'\033[B'|j) [[ $_sel -lt $((_n-1)) ]] && _sel=$((_sel+1)) ;;
            q|Q) break ;;
            ''|$'\n')
                case "${_top_cats[$_sel]}" in
                    container)
                        _submenu "Container" \
                            "  Start"            start \
                            "  Stop"             stop \
                            "  Restart"          restart \
                            "  Open in browser"  open \
                            "  Container shell"  shell \
                            "  Logs"             logs \
                            "  Status"           status \
                            "  URL"              url
                        ;;
                    build)
                        _submenu "Build" \
                            "  Build image"                      build \
                            "  Images · versions"                images \
                            "  Update  (rebuild, no cache)"      update \
                            "  Clean   (remove container + images)" clean
                        ;;
                    configuration)
                        _submenu "Configuration" \
                            "  Workspace"  workspace \
                            "  Profile"    profile \
                            "  Mode"       mode \
                            "  Port"       port
                        ;;
                    help)
                        tput cnorm 2>/dev/null || true
                        clear
                        ( cmd_help ) || true
                        echo ""
                        echo -e "  ${BOLD}Press any key to return...${NC}"
                        IFS= read -r -s -n1
                        tput civis 2>/dev/null || true
                        ;;
                    exit)
                        break
                        ;;
                esac
                _refresh_status
                load_config
                ;;
        esac
    done

    trap - EXIT INT TERM
    tput cnorm 2>/dev/null || true
    clear
}

# ── Main ───────────────────────────────────────────────────────────────────────

case "${1:-menu}" in
    build)     shift; cmd_build "$@" ;;
    start)     cmd_start ;;
    stop)      cmd_stop ;;
    restart)   cmd_restart ;;
    open)      cmd_open ;;
    shell)     cmd_shell ;;
    exec)      shift; cmd_exec "$@" ;;
    logs)      cmd_logs ;;
    status)    cmd_status ;;
    url)       cmd_url ;;
    clean)     cmd_clean ;;
    update)    cmd_update ;;
    images)    cmd_images ;;
    use)       shift; cmd_use "${1:-}" ;;
    init)      cmd_init ;;
    workspace) shift; cmd_workspace "${1:-}" ;;
    profile)   shift; cmd_profile "${1:-}" ;;
    mode)      shift; cmd_mode "${1:-}" ;;
    port)      shift; cmd_port "${1:-}" ;;
    packages)  shift; cmd_packages "${1:-all}" ;;
    menu)      cmd_menu ;;
    help|--help|-h) cmd_help ;;
    *)
        error "Unknown command: $1"
        cmd_help
        exit 1
        ;;
esac
