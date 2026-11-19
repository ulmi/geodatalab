#!/usr/bin/env bash
# geodatalab — GIS Data Laboratory control script (the only interface needed).
#
# One CLI, several backends:  container (podman/docker) · pixi · nix (planned)
# Backend-specific code lives in lib/backend-*.sh; shared helpers in lib/common.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/backend-container.sh
source "${SCRIPT_DIR}/lib/backend-container.sh"
# shellcheck source=lib/backend-pixi.sh
source "${SCRIPT_DIR}/lib/backend-pixi.sh"
# shellcheck source=lib/backend-nix.sh
source "${SCRIPT_DIR}/lib/backend-nix.sh"

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

_label() { if be_has label; then "${BACKEND}_label"; else echo "$BACKEND"; fi; }

_restart_hint() {
    if gdl_is_running; then warn "Restart to apply: $0 restart"; fi
}

# ── Backend ────────────────────────────────────────────────────────────────────

cmd_backend() {
    load_config
    if [[ -n "${1:-}" ]]; then
        if ! validate_backend "$1"; then
            error "Invalid backend: $1  (valid: ${BACKENDS[*]})"
            exit 1
        fi
        if [[ "$1" != "$BACKEND" ]] && gdl_is_running; then
            error "The ${BACKEND} workbench is running. Stop it first: $0 stop"
            exit 1
        fi
        BACKEND="$1"
        _CFG_BACKEND="$1"
        save_config
        info "Backend set to: $BACKEND"
        echo "  Build the ${PROFILE} profile for it:  $0 build"
    else
        heading "Backends"
        local b
        for b in "${BACKENDS[@]}"; do
            if [[ "$b" == "$BACKEND" ]]; then
                printf "  ${GREEN}* ${BOLD}%-10s${NC}${GREEN} —  %s${NC}\n" "$b" "${BACKEND_DESC[$b]}"
            else
                printf "    %-10s —  %s\n" "$b" "${BACKEND_DESC[$b]}"
            fi
        done
        echo ""
        echo "  Change with: $0 backend <name>"
        echo "  Workspace, data folders, profile, mode and port are shared by all backends."
    fi
}

# ── Workspace ──────────────────────────────────────────────────────────────────

cmd_workspace() {
    load_config
    if [[ -n "${1:-}" ]]; then
        local ws="${1/#\~/$HOME}"
        ws="$(realpath -m "$ws")"
        if [[ ! -d "$ws" ]]; then
            if confirm "Directory does not exist. Create it?" Y; then
                mkdir -p "$ws"
                info "Created: $ws"
            fi
        fi
        WORKSPACE="$ws"
        save_config
        info "Workspace set to: $WORKSPACE"
        _restart_hint
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

# ── Data folders ───────────────────────────────────────────────────────────────

_data_ls() {
    local e status
    heading "Workbench layout"
    printf "  %-22s -> %s  ${BLUE}(rw)${NC}\n" "workspace/" "${WORKSPACE:-not set}"
    for e in "${GDL_DATA_DIRS[@]+"${GDL_DATA_DIRS[@]}"}"; do
        _data_parse "$e"
        if [[ -d "$_D_PATH" ]]; then status=""; else status="  ${RED}missing${NC}"; fi
        printf "  %-22s -> %s  ${BLUE}(%s)${NC}%b\n" "data/${_D_NAME}/" "$_D_PATH" \
            "$([[ $_D_RO -eq 1 ]] && echo ro || echo rw)" "$status"
    done
    [[ ${#GDL_DATA_DIRS[@]} -eq 0 ]] && echo "  (no data folders — add one: $0 data add <name> <path> [--ro])"
    echo "  Jupyter opens in:      ${GDL_OPEN:-/ (workbench root)}"
}

cmd_data() {
    load_config
    local sub="${1:-ls}"
    [[ $# -gt 0 ]] && shift
    case "$sub" in
        ls|list)
            _data_ls
            echo ""
            echo "  In notebooks (any backend):"
            echo "    from pathlib import Path; import os"
            echo "    Path(os.environ['GDL_DATA']) / '<name>'      # or os.environ['GDL_DATA_<NAME>']"
            ;;
        add)
            local name="${1:-}" path="${2:-}" ro=0
            [[ "${3:-}" == "--ro" || "${2:-}" == "--ro" ]] && ro=1
            [[ "$path" == "--ro" ]] && path="${3:-}"
            if [[ -z "$name" || -z "$path" ]]; then
                error "Usage: $0 data add <name> <path> [--ro]"; exit 1
            fi
            if ! [[ "$name" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || [[ "$name" == "dirs" ]]; then
                error "Invalid name '${name}': use lowercase letters, digits, - and _ (not 'dirs')."
                exit 1
            fi
            if [[ "$(_data_index "$name")" != "-1" ]]; then
                error "Data folder '${name}' already exists. Remove it first: $0 data rm ${name}"
                exit 1
            fi
            path="${path/#\~/$HOME}"
            path="$(realpath -m "$path")"
            if [[ ! -d "$path" ]]; then
                warn "Path does not exist (yet): $path"
                confirm "Add it anyway?" N || exit 1
            fi
            GDL_DATA_DIRS+=("${name}=${path}$([[ $ro -eq 1 ]] && echo ':ro' || true)")
            save_config
            info "Added data/${name}/ -> ${path}$([[ $ro -eq 1 ]] && echo '  (read-only)' || true)"
            _restart_hint
            ;;
        rm|remove)
            local name="${1:-}" idx i kept=()
            [[ -z "$name" ]] && { error "Usage: $0 data rm <name>"; exit 1; }
            idx="$(_data_index "$name")"
            [[ "$idx" == "-1" ]] && { error "No data folder named '${name}'."; exit 1; }
            for i in "${!GDL_DATA_DIRS[@]}"; do
                [[ "$i" != "$idx" ]] && kept+=("${GDL_DATA_DIRS[$i]}")
            done
            GDL_DATA_DIRS=("${kept[@]+"${kept[@]}"}")
            [[ "${GDL_OPEN:-}" == "data/${name}" ]] && GDL_OPEN=""
            save_config
            info "Removed data/${name}/  (the folder itself is untouched)"
            _restart_hint
            ;;
        open)
            local target="${1:-}"
            case "$target" in
                ""|/|root) GDL_OPEN="" ;;
                workspace) GDL_OPEN="workspace" ;;
                *)
                    [[ "$(_data_index "$target")" == "-1" ]] && { error "No data folder named '${target}'."; exit 1; }
                    GDL_OPEN="data/${target}" ;;
            esac
            save_config
            info "Jupyter opens in: ${GDL_OPEN:-/ (workbench root)}"
            _restart_hint
            ;;
        *)
            error "Usage: $0 data [ls | add <name> <path> [--ro] | rm <name> | open <name|workspace|root>]"
            exit 1 ;;
    esac
}

# ── Resource limits (container backend) ────────────────────────────────────────

cmd_limits() {
    load_config
    if [[ $# -eq 0 ]]; then
        heading "Resource limits  (container backend)"
        echo "  Memory limit:        ${GDL_MEMORY:-none}"
        echo "  Memory reservation:  ${GDL_MEMORY_RESERVE:-none}"
        echo "  CPUs:                ${GDL_CPUS:-none}"
        echo ""
        echo "  Set:   $0 limits --memory 56G --cpus 78 --reserve 4G"
        echo "  Clear: $0 limits --clear"
        return 0
    fi
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --memory)  GDL_MEMORY="${2:-}"; shift 2 ;;
            --reserve) GDL_MEMORY_RESERVE="${2:-}"; shift 2 ;;
            --cpus)    GDL_CPUS="${2:-}"; shift 2 ;;
            --clear)   GDL_MEMORY=""; GDL_MEMORY_RESERVE=""; GDL_CPUS=""; shift ;;
            *) error "Unknown option: $1"; exit 1 ;;
        esac
    done
    save_config
    info "Limits: memory=${GDL_MEMORY:-none} reserve=${GDL_MEMORY_RESERVE:-none} cpus=${GDL_CPUS:-none}"
    [[ "$BACKEND" != "container" ]] && warn "Limits only apply to the container backend."
    _restart_hint
}

# ── Profiles / modes / port ────────────────────────────────────────────────────

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
        local p
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
        _restart_hint
    else
        heading "Startup mode"
        local m
        for m in "${MODES[@]}"; do
            if [[ "$m" == "${GDL_MODE:-lab}" ]]; then
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

cmd_port() {
    load_config
    if [[ -n "${1:-}" ]]; then
        if ! [[ "$1" =~ ^[0-9]+$ ]] || [[ "$1" -lt 1024 || "$1" -gt 65535 ]]; then
            error "Invalid port: $1  (must be 1024–65535)"
            exit 1
        fi
        if [[ " $(_other_instance_ports | tr '\n' ' ') " == *" $1 "* ]]; then
            warn "Port $1 is already configured for another instance (see: $0 instances)."
        fi
        GDL_PORT="$1"
        save_config
        info "Port set to: $GDL_PORT"
        _restart_hint
    else
        heading "Host port"
        echo "  Port: ${GDL_PORT:-8888}"
        echo ""
        echo "  Change with: $0 port <number>"
        echo "  Requires restart to take effect."
    fi
}

# ── Build / lock / images ──────────────────────────────────────────────────────

cmd_build()  { load_config; be build "$@"; }
cmd_images() { load_config; be images; }
cmd_use()    { load_config; be use "${1:-}"; }
cmd_clean()  { load_config; be clean; }
cmd_update() { load_config; be update; }

cmd_lock() {
    load_config
    local target="${1:-${PROFILE:-lab}}" profiles=()
    if [[ "$target" == "all" ]]; then
        profiles=("${PROFILES[@]}")
    elif validate_profile "$target"; then
        profiles=("$target")
    else
        error "Invalid profile: $target  (valid: ${PROFILES[*]} all)"
        exit 1
    fi
    be lock "${profiles[@]}"
}

# ── Lifecycle ──────────────────────────────────────────────────────────────────

cmd_start() {
    load_config
    be start
    gdl_is_running || return 0
    echo ""
    if [[ "${GDL_MODE:-lab}" == "idle" ]]; then
        echo "  Running in idle mode — no Jupyter server."
        echo "  Attach with VS Code Dev Containers, or open a shell: $0 shell"
        echo ""
        echo "  To start JupyterLab: $0 mode lab && $0 restart"
    else
        cmd_url
    fi
}

cmd_stop()    { load_config; be stop; }
cmd_restart() { cmd_stop; cmd_start; }
cmd_exec()    { load_config; be exec "$@"; }
cmd_shell()   { cmd_exec; }
cmd_logs()    { load_config; be logs; }

_get_url_raw() {
    local port="${GDL_PORT:-8888}" token=""
    if [[ -n "${JUPYTER_TOKEN:-}" ]]; then
        token="$JUPYTER_TOKEN"
    else
        token="$(be url_token)"
    fi
    if [[ -n "$token" ]]; then
        echo "http://localhost:${port}/lab?token=${token}"
    else
        echo "http://localhost:${port}/lab"
    fi
}

cmd_url() {
    load_config
    if [[ "${GDL_MODE:-lab}" == "idle" ]]; then
        echo "  Idle mode — no Jupyter server running."
        echo "  Switch modes: $0 mode lab && $0 restart"
        return 0
    fi
    echo -e "  ${BLUE}$(_get_url_raw)${NC}"
    if [[ -z "${JUPYTER_TOKEN:-}" ]] && ! gdl_is_running; then
        echo "  (not running — start it: $0 start)"
    fi
}

cmd_open() {
    load_config
    if [[ "${GDL_MODE:-lab}" == "idle" ]]; then
        error "Idle mode — no Jupyter server running."
        exit 1
    fi
    if ! gdl_is_running; then
        error "Not running. Start it first: $0 start"
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
    load_config
    be status

    heading "Configuration"
    echo "  Instance:   ${GDL_INSTANCE}$([[ "$GDL_INSTANCE" != default ]] && echo "  ($(instance_file "$GDL_INSTANCE") over .geodatalab)" || true)"
    echo "  Backend:    ${BACKEND}"
    echo "  Profile:    ${PROFILE:-lab}"
    echo "  Mode:       ${GDL_MODE:-lab}"
    echo "  Port:       ${GDL_PORT:-8888}"
    [[ "$BACKEND" == "container" ]] && echo "  Active tag: ${IMAGE_TAG:-latest}"
    if [[ "$BACKEND" == "container" && -n "${GDL_MEMORY}${GDL_CPUS}" ]]; then
        echo "  Limits:     memory=${GDL_MEMORY:-none} cpus=${GDL_CPUS:-none}"
    fi
    _data_ls

    if gdl_is_running && [[ "${GDL_MODE:-lab}" != "idle" ]]; then
        heading "URL"
        cmd_url
    fi
}

# ── Packages ───────────────────────────────────────────────────────────────────

cmd_packages() {
    load_config
    local target="${1:-all}"

    _show_profile() {
        local p="$1"
        local req="${SCRIPT_DIR}/requirements/${p}.txt"
        heading "  ${p}  —  ${PROFILE_DESC[$p]}"
        echo -e "  ${BOLD}System:${NC}  ${PROFILE_SYS[$p]}"
        if [[ "$BACKEND" == "pixi" && ( "$p" == "lab" || "$p" == "institute" ) ]]; then
            echo -e "           ${YELLOW}(pixi backend: SAGA GIS not available)${NC}"
        fi
        if [[ -f "${SCRIPT_DIR}/requirements/locks/${p}.lock" ]]; then
            echo -e "  ${BOLD}Python:${NC}  (locked versions from requirements/locks/${p}.lock)"
        else
            echo -e "  ${BOLD}Python:${NC}  (not locked — run: $0 lock ${p})"
        fi
        if [[ -f "$req" ]]; then
            _expand_requirements "$req" "$p"
        else
            echo "    (requirements file not found)"
        fi
    }

    show_logo
    if [[ "$target" == "all" ]]; then
        local p
        for p in "${PROFILES[@]}"; do
            _show_profile "$p"
            echo ""
        done
    else
        if ! validate_profile "$target"; then
            error "Invalid profile: $target  (valid: ${PROFILES[*]})"
            exit 1
        fi
        _show_profile "$target"
        echo ""
    fi
}

# ── Init wizard ────────────────────────────────────────────────────────────────

cmd_init() {
    load_config

    clear; show_logo
    echo -e "  ${BOLD}Welcome to geodatalab — first-time setup${NC}"
    echo    "  This wizard will configure your environment."
    echo ""
    read -rp "  Press Enter to continue..." _

    # Backend
    local b_opts=() b
    for b in "${BACKENDS[@]}"; do b_opts+=("$(printf '%-10s —  %s' "$b" "${BACKEND_DESC[$b]}")"); done
    if _pick_from_list "Select a backend" "${b_opts[@]}"; then
        BACKEND="${BACKENDS[$PICKED_IDX]}"
        save_config
    fi
    clear; show_logo

    # Workspace
    prompt_workspace
    echo ""

    # Data folder
    if confirm "Add a data folder (e.g. a shared data disk) now?" N; then
        local dname dpath
        read -rp "  Name (e.g. ccdrn): " dname
        read -rp "  Path: " dpath
        if [[ -n "$dname" && -n "$dpath" ]]; then
            ( cmd_data add "$dname" "$dpath" ) || true
            load_config
        fi
    fi

    # Profile
    if _pick_profile "Select a build profile"; then
        PROFILE="$_PICKED_PROFILE"
        save_config
    fi

    # Mode
    local mode_opts=(
        "lab   —  ${MODE_DESC[lab]}"
        "idle  —  ${MODE_DESC[idle]}"
    )
    echo ""
    if _pick_from_list "Select startup mode" "${mode_opts[@]}"; then
        case $PICKED_IDX in
            0) GDL_MODE=lab ;; 1) GDL_MODE=idle ;;
        esac
        save_config
    fi

    # Port
    clear; show_logo
    read -rp "  Host port [${GDL_PORT:-8888}]: " p
    if [[ -n "${p:-}" ]]; then
        cmd_port "$p"
    fi

    echo ""
    info "Configuration saved."
    echo ""
    if confirm "Build the ${BACKEND} workbench now?" Y; then
        echo ""
        cmd_build
        echo ""
        if confirm "Start it now?" Y; then
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
  ./geodatalab.sh [-i <instance>] <command> [options]

${BOLD}Workbench:${NC}
  start                          Start the workbench (Jupyter)
  stop                           Stop it
  restart                        Restart it
  open                           Open JupyterLab in the browser
  shell                          Interactive bash inside the workbench
  exec [cmd...]                  Run a command inside the workbench
  logs                           Follow logs
  status                         State, config, data folders, URL
  url                            Print the JupyterLab URL with token

${BOLD}Build:${NC}
  build [-p <profile>] [-t <tag>] [--no-cache]
                                 Build the image / environment (from locks)
  lock [profile|all]             Re-resolve latest versions and write lock files
  update                         Re-lock and rebuild, restart if running
  images                         List built images            (container)
  use [tag]                      Switch the active image tag  (container)
  clean                          Remove container+images / environment

${BOLD}Configuration:${NC}
  init                           First-time guided setup wizard
  backend [name]                 Show or set the backend  (container|pixi|nix)
  workspace [path]               Show or set the workspace directory
  data                           List data folders
  data add <name> <path> [--ro]  Add a data folder  -> data/<name>/ in the workbench
  data rm <name>                 Remove a data folder (files untouched)
  data open <name|workspace>     Folder Jupyter opens in
  limits [--memory X] [--cpus N] [--reserve X] [--clear]
                                 Resource limits              (container)
  profile [name]                 Show or set the build profile
  mode [name]                    Show or set the startup mode
  port [number]                  Show or set the host port  (default: 8888)
  packages [profile|all]         List packages included in a profile

${BOLD}Instances${NC} (several workbenches side by side, e.g. one per project):
  instances                      List instances: backend, profile, port, state, data
  instances new <name> [--from <instance>]
                                 Create one (gets its own free port)
  instances rm <name>            Remove one (its container / state; data untouched)
  -i <name> <command>            Run any command for that instance (or GDL_INSTANCE=<name>)
  An instance inherits .geodatalab and stores only what differs:
    ./geodatalab.sh instances new pinhel
    ./geodatalab.sh -i pinhel profile kitchen
    ./geodatalab.sh -i pinhel data add ren /data/REN/Pinhel --ro
    ./geodatalab.sh -i pinhel start

${BOLD}Interactive TUI:${NC}
  menu                           Arrow-key menu (default when called with no args)

${BOLD}Backends:${NC}
  container  ${BACKEND_DESC[container]}  [default]
  pixi       ${BACKEND_DESC[pixi]}
  nix        ${BACKEND_DESC[nix]}

${BOLD}Workbench layout${NC} (identical on every backend):
  \$GDL_ROOT/workspace/      your workspace (read-write)
  \$GDL_ROOT/data/<name>/    each data folder
  Notebooks: Path(os.environ["GDL_DATA"]) / "<name>"

${BOLD}Profiles:${NC}
  kitchen    ${PROFILE_DESC[kitchen]}
  lab        ${PROFILE_DESC[lab]}  [default]
  institute  ${PROFILE_DESC[institute]}
  r+julia    ${PROFILE_DESC[r+julia]}

${BOLD}Environment variables:${NC}
  JUPYTER_TOKEN   Auth token (empty = no auth, unset = auto-generated)
  GDL_BACKEND     One-off backend override (container|pixi)
  GDL_BIND        pixi: listen address (default 127.0.0.1; 0.0.0.0 for LAN)
  GDL_HOME        pixi binary location (default ~/.local/share/geodatalab)
  GDL_ASSUME_YES  1 = answer yes to prompts (scripts / CI)

${BOLD}Examples:${NC}
  ./geodatalab.sh init
  ./geodatalab.sh workspace ~/projects
  ./geodatalab.sh data add ccdrn /media/disk1/CCDRN --ro && ./geodatalab.sh data open ccdrn
  ./geodatalab.sh lock lab && ./geodatalab.sh build --profile lab
  ./geodatalab.sh backend pixi && ./geodatalab.sh build -p kitchen && ./geodatalab.sh start
  ./geodatalab.sh exec python -c "import geopandas; print('ok')"
  ssh box ./geodatalab/geodatalab.sh start   # remote; then: ssh -L 8888:localhost:8888 box
EOF
}

# ── Instances ──────────────────────────────────────────────────────────────────

_instances_ls() {
    local n cur="$GDL_INSTANCE"
    heading "Instances"
    printf "  ${BOLD}%-2s%-16s %-10s %-10s %-6s %-9s %s${NC}\n" "" NAME BACKEND PROFILE PORT STATE DATA
    while IFS= read -r n; do
        (
            GDL_INSTANCE="$n"
            load_config 2>/dev/null || exit 0
            local state="stopped" names="" e mark=" "
            gdl_is_running && state="running"
            for e in "${GDL_DATA_DIRS[@]+"${GDL_DATA_DIRS[@]}"}"; do
                _data_parse "$e"; names+="${_D_NAME}$([[ $_D_RO -eq 1 ]] && echo '(ro)' || true) "
            done
            [[ "$n" == "$cur" ]] && mark="*"
            if [[ "$state" == running ]]; then state="${GREEN}running${NC}  "; else state="stopped  "; fi
            printf "  %-2s%-16s %-10s %-10s %-6s %b %s\n" "$mark" "$n" "$BACKEND" "$PROFILE" "$GDL_PORT" "$state" "${names:--}"
        )
    done < <(list_instances)
    echo ""
    echo "  New:  $0 instances new <name> [--from <instance>]      Use:  $0 -i <name> <command>"
}

cmd_instances() {
    local sub="${1:-ls}"
    [[ $# -gt 0 ]] && shift
    case "$sub" in
        ls|list) _instances_ls ;;
        new|add)
            local name="${1:-}" from="" port f
            [[ "${2:-}" == "--from" ]] && from="${3:-}"
            if ! validate_instance_name "$name"; then
                error "Usage: $0 instances new <name> [--from <instance>]   (name: lowercase letters, digits, -; not 'default')"
                exit 1
            fi
            f="$(instance_file "$name")"
            [[ -f "$f" ]] && { error "Instance '${name}' already exists."; exit 1; }
            if [[ -n "$from" && "$from" != "default" && ! -f "$(instance_file "$from")" ]]; then
                error "No instance '${from}' to copy from."; exit 1
            fi
            GDL_INSTANCE="$name"
            port="$(gdl_free_port)"
            mkdir -p "$INSTANCE_DIR"
            {
                echo "# geodatalab instance '${name}' — only what differs from .geodatalab"
                if [[ -n "$from" && "$from" != "default" ]]; then
                    grep -vE '^(#|GDL_PORT=)' "$(instance_file "$from")" || true
                fi
                echo "GDL_PORT=${port}"
            } > "$f"
            info "Created instance '${name}' on port ${port}${from:+ (copied from ${from})}"
            echo "  Configure:  $0 -i ${name} profile|data|open|mode|backend ..."
            echo "  Start:      $0 -i ${name} start"
            ;;
        rm|remove)
            local name="${1:-}"
            validate_instance_name "$name" || { error "Usage: $0 instances rm <name>"; exit 1; }
            [[ -f "$(instance_file "$name")" ]] || { error "No instance '${name}'."; exit 1; }
            if ( GDL_INSTANCE="$name"; load_config; gdl_is_running ); then
                error "Instance '${name}' is running. Stop it first: $0 -i ${name} stop"
                exit 1
            fi
            confirm "Remove instance '${name}' (config + generated state; data folders untouched)?" N || exit 0
            ( GDL_INSTANCE="$name"; load_config
              if [[ "$BACKEND" == "container" ]]; then be init 2>/dev/null; compose_run down 2>/dev/null || true; fi ) || true
            if [[ -d "${GDL_STATE_ROOT}/${name}" ]]; then
                find "${GDL_STATE_ROOT}/${name}" -type l -delete     # symlink farm: links only
                rm -rf -- "${GDL_STATE_ROOT:?}/${name:?}"
            fi
            rm -f -- "$(instance_file "$name")"
            info "Removed instance '${name}'."
            ;;
        *) error "Usage: $0 instances [ls | new <name> [--from <instance>] | rm <name>]"; exit 1 ;;
    esac
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
    _pick_profile "Build ${BACKEND} — select profile  (current: ${PROFILE:-lab})" || return 0
    clear; show_logo
    if [[ "$BACKEND" != "container" ]]; then
        cmd_build --profile "$_PICKED_PROFILE"
        return
    fi
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
        "lab   —  ${MODE_DESC[lab]}"
        "idle  —  ${MODE_DESC[idle]}"
    )
    _pick_from_list "Set startup mode  (current: ${GDL_MODE:-lab})" \
        "${opts[@]}" || return 0
    clear; show_logo
    case $PICKED_IDX in
        0) cmd_mode lab ;; 1) cmd_mode idle ;;
    esac
    if gdl_is_running; then
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
    load_config

    # ── Cached state (updated at start and after each action) ─────────────────
    local _cache_running=false _cache_health=""

    _refresh_status() {
        if gdl_is_running; then
            _cache_running=true
            _cache_health=$(be health 2>/dev/null || echo "")
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
        echo -e "  ${BOLD}── Workbench  ·  ${BACKEND}$([[ "$GDL_INSTANCE" != default ]] && echo "  ·  instance ${GDL_INSTANCE}" || true)${NC}"
        if [[ "$_cache_running" == true ]]; then
            echo -e "  ${GREEN}●${NC} running${_hstr:+  ·${_hstr}}  ·  $(_label)  ·  :${GDL_PORT:-8888}"
        else
            echo -e "  ${RED}○${NC} stopped  ·  $(_label)"
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
                if gdl_is_running; then
                    cmd_shell || true
                else
                    echo ""; error "Workbench is not running."
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
            lock)      ( cmd_lock    ) || true; _pause=1 ;;
            images)    _menu_images ;;
            update)    ( cmd_update  ) || true; _pause=1 ;;
            clean)     ( cmd_clean   ) || true ;;
            workspace) _menu_workspace ;;
            instances) ( _instances_ls ) || true; _pause=1 ;;
            backend)   _menu_backend || true ;;
            data)      _menu_data || true ;;
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
    local -a _top_labels=("  Workbench" "  Build" "  Configuration" "  Help" "  Exit")
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
                        _submenu "Workbench" \
                            "  Start"            start \
                            "  Stop"             stop \
                            "  Restart"          restart \
                            "  Open in browser"  open \
                            "  Shell"            shell \
                            "  Logs"             logs \
                            "  Status"           status \
                            "  URL"              url
                        ;;
                    build)
                        _submenu "Build" \
                            "  Build"                            build \
                            "  Lock    (pin latest package versions)" lock \
                            "  Images · versions"                images \
                            "  Update  (re-lock + rebuild)"      update \
                            "  Clean   (remove image(s) / environment)" clean
                        ;;
                    configuration)
                        _submenu "Configuration" \
                            "  Instances"     instances \
                            "  Backend"       backend \
                            "  Workspace"     workspace \
                            "  Data folders"  data \
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

_menu_backend() {
    local opts=() b
    for b in "${BACKENDS[@]}"; do opts+=("$(printf '%-10s —  %s' "$b" "${BACKEND_DESC[$b]}")"); done
    _pick_from_list "Set backend  (current: ${BACKEND})" "${opts[@]}" || return 0
    clear; show_logo
    ( cmd_backend "${BACKENDS[$PICKED_IDX]}" ) || true
    load_config
    sleep 1
}

_menu_data() {
    local key name path ro
    while true; do
        clear; show_logo
        load_config
        _data_ls
        echo ""
        echo "  a add  ·  r remove  ·  o open-in  ·  any other key: back"
        IFS= read -r -s -n1 key
        case "$key" in
            a|A)
                echo ""
                read -rp "  Name (e.g. ccdrn): " name
                read -rp "  Host path: " path
                read -rp "  Read-only? [y/N] " ro
                [[ -z "$name" || -z "$path" ]] && continue
                if [[ "$ro" =~ ^[Yy]$ ]]; then ( cmd_data add "$name" "$path" --ro ) || true
                else ( cmd_data add "$name" "$path" ) || true; fi
                sleep 1 ;;
            r|R)
                echo ""
                read -rp "  Name to remove: " name
                [[ -n "$name" ]] && { ( cmd_data rm "$name" ) || true; sleep 1; } ;;
            o|O)
                echo ""
                read -rp "  Open Jupyter in (name | workspace | root): " name
                ( cmd_data open "$name" ) || true
                sleep 1 ;;
            *) return 0 ;;
        esac
    done
}

# ── Main ───────────────────────────────────────────────────────────────────────

# Global option: -i/--instance NAME (or GDL_INSTANCE=NAME) selects a workbench instance
while [[ "${1:-}" == "-i" || "${1:-}" == "--instance" || "${1:-}" == --instance=* ]]; do
    if [[ "$1" == --instance=* ]]; then GDL_INSTANCE="${1#--instance=}"; shift
    else GDL_INSTANCE="${2:-}"; shift 2 || true; fi
    if [[ "$GDL_INSTANCE" != "default" ]] && ! validate_instance_name "$GDL_INSTANCE"; then
        error "Invalid instance name: '${GDL_INSTANCE}'"; exit 1
    fi
done

case "${1:-menu}" in
    build)     shift; cmd_build "$@" ;;
    lock)      shift; cmd_lock "${1:-}" ;;
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
    backend)   shift; cmd_backend "${1:-}" ;;
    instances|instance) shift; cmd_instances "$@" ;;
    render)    load_config; container_render ;;   # regenerate .gdl/compose.data.yml (Dev Containers; any backend)
    workspace) shift; cmd_workspace "${1:-}" ;;
    data)      shift; cmd_data "$@" ;;
    limits)    shift; cmd_limits "$@" ;;
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
