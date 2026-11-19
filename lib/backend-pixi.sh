# shellcheck shell=bash
# geodatalab — pixi backend: the workbench runs as plain host processes from a
# conda-forge environment managed by pixi (https://pixi.sh). No container
# runtime, no root. Works the same on a laptop or a remote box over ssh.
#
# pixi.toml (repo root) is GENERATED from requirements/<profile>.txt +
# envs/pixi/native.txt by envs/pixi/gen_pixi.py; pixi.lock pins everything.
# One pixi environment per profile, shared by all instances (.pixi/envs/<env>).
#
# Known gaps vs the container: SAGA (not on conda-forge yet), pylasr (lasR).

PIXI_BIN=""
PIXI_MANIFEST="${SCRIPT_DIR}/pixi.toml"
PIXI_LOCK="${SCRIPT_DIR}/pixi.lock"
PIXI_STATE=""     # per instance, see pixi_apply_instance

pixi_apply_instance() { PIXI_STATE="${GDL_STATE_DIR}"; }

_px_find() {
    [[ -n "$PIXI_BIN" ]] && return 0
    local c
    for c in "${GDL_HOME}/bin/pixi" "$(command -v pixi 2>/dev/null || true)" "${HOME}/.pixi/bin/pixi"; do
        if [[ -n "$c" && -x "$c" ]]; then PIXI_BIN="$c"; return 0; fi
    done
    return 1
}

# Download the pixi binary into $GDL_HOME/bin (asks first).
pixi_bootstrap() {
    _px_find && return 0
    local os arch target
    os="$(uname -s)"; arch="$(uname -m)"
    [[ "$arch" == "arm64" ]] && arch="aarch64"
    case "$os" in
        Linux)  target="pixi-${arch}-unknown-linux-musl.tar.gz" ;;
        Darwin) target="pixi-${arch}-apple-darwin.tar.gz" ;;
        *) error "Unsupported platform for pixi: ${os}-${arch}"; exit 1 ;;
    esac
    warn "pixi not found."
    if ! confirm "Download pixi (${target}) to ${GDL_HOME}/bin?" Y; then
        error "pixi is required for the pixi backend (or install it: https://pixi.sh)."
        exit 1
    fi
    command -v curl &>/dev/null || { error "curl is required to download pixi."; exit 1; }
    mkdir -p "${GDL_HOME}/bin"
    curl -fsSL "https://github.com/prefix-dev/pixi/releases/latest/download/${target}" \
        | tar -xz -C "${GDL_HOME}/bin" pixi
    PIXI_BIN="${GDL_HOME}/bin/pixi"
    info "Installed: ${PIXI_BIN}  ($("$PIXI_BIN" --version))"
}

pixi_init() { _px_find || true; }

_px()       { "$PIXI_BIN" "$@"; }
_px_env()   { local p="${1:-${PROFILE:-lab}}"; echo "${p//[^a-z0-9-]/-}"; }   # r+julia -> r-julia
_px_prefix(){ echo "${SCRIPT_DIR}/.pixi/envs/$(_px_env "${1:-}")"; }
_px_root()  { echo "${PIXI_STATE}/root"; }      # per-instance workbench root (symlink farm)
_px_pidf()  { echo "${PIXI_STATE}/jupyter.pid"; }
_px_logf()  { echo "${PIXI_STATE}/jupyter.log"; }
_px_tokf()  { echo "${PIXI_STATE}/token"; }

# Run a command inside the activated env of profile $1 (no re-solve: --frozen).
_px_in() {
    local p="$1"; shift
    local hook
    hook="$(_px shell-hook --manifest-path "$PIXI_MANIFEST" -e "$(_px_env "$p")" --frozen --shell bash)" || return 1
    # conda activation scripts are not `set -u` clean (e.g. PDAL_DRIVER_PATH)
    ( set +u; eval "$hook"; "$@" )
}

_px_need_env() {
    if ! _px_find || [[ ! -x "$(_px_prefix)/bin/python" ]]; then
        error "No pixi environment for profile '${PROFILE}'. Build it first: $0 build"
        exit 1
    fi
}

_px_saga_notice() {
    case "$1" in
        lab|institute)
            warn "SAGA GIS is not on conda-forge — it is skipped on the pixi backend."
            echo "  Use the container backend for SAGA (a conda recipe is planned)." ;;
    esac
}

_px_gen_manifest() {
    command -v python3 &>/dev/null || { error "python3 is needed to generate pixi.toml."; exit 1; }
    python3 "${SCRIPT_DIR}/envs/pixi/gen_pixi.py"
}

# Post-install steps for profile $1 (idempotent).
_px_post_install() {
    local p="$1" prefix
    prefix="$(_px_prefix "$p")"
    # GRASS Python API: same targeted .pth bridge as the container image.
    if [[ -x "${prefix}/bin/grass" ]]; then
        _px_in "$p" bash -c '
            site="$(python -c "import sysconfig; print(sysconfig.get_paths()[\"purelib\"])")"
            grass --config python_path > "$site/gis-bridge.pth"
            python -c "import grass.script" && echo "GRASS Python API bridged: $(cat "$site/gis-bridge.pth")"'
    fi
    if [[ -x "${prefix}/bin/julia" ]]; then
        info "Installing IJulia..."
        _px_in "$p" julia -e 'using Pkg; Pkg.add("IJulia"); using IJulia' || \
            warn "IJulia install failed — Julia kernel unavailable."
    fi
    _px_in "$p" python -m pip check || warn "pip check reported problems (see above)."
}

# Stop if any instance runs Jupyter from profile $1's env.
_px_guard_env() {
    local p="$1" n
    while IFS= read -r n; do
        if ( GDL_INSTANCE="$n"; load_config 2>/dev/null
             [[ "$BACKEND" == "pixi" && "$(_px_env)" == "$(_px_env "$p")" ]] && pixi_is_running ); then
            error "Instance '${n}' is running from the '${p}' environment. Stop it first: $0 -i ${n} stop"
            exit 1
        fi
    done < <(list_instances)
}

# ── Interface ──────────────────────────────────────────────────────────────────

pixi_label() { echo "pixi:$(_px_env)"; }

pixi_is_running() {
    local pidf; pidf="$(_px_pidf)"
    [[ -f "$pidf" ]] && kill -0 "$(cat "$pidf")" 2>/dev/null
}

pixi_health() {
    pixi_is_running || { echo ""; return 0; }
    if port_open "${GDL_PORT:-8888}"; then echo healthy; else echo starting; fi
}

pixi_build() {
    local p="${PROFILE:-lab}"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --profile|-p)
                shift
                validate_profile "${1:-}" || { error "Invalid profile: ${1:-}  (valid: ${PROFILES[*]})"; exit 1; }
                p="$1"; shift ;;
            --tag|-t)   shift; shift; warn "--tag is ignored on the pixi backend." ;;
            --no-cache) shift ;;
            *) error "Unknown build option: $1"; exit 1 ;;
        esac
    done
    pixi_bootstrap
    _px_guard_env "$p"
    _px_saga_notice "$p"
    if ! python3 "${SCRIPT_DIR}/envs/pixi/gen_pixi.py" --check; then
        warn "pixi.toml is out of date with requirements/ — regenerating and re-locking."
        pixi_lock "$p"
    elif [[ ! -f "$PIXI_LOCK" ]]; then
        warn "No pixi.lock yet — solving latest versions."
        pixi_lock "$p"
    fi
    info "Installing environment '$(_px_env "$p")' from pixi.lock..."
    (cd "$SCRIPT_DIR" && _px install --locked -e "$(_px_env "$p")")
    _px_post_install "$p"
    PROFILE="$p"
    save_config
    info "Environment ready: $(_px_prefix "$p")  ($(du -sh "$(_px_prefix "$p")" 2>/dev/null | cut -f1))"
}

# Re-resolve to the latest versions. pixi.lock covers all profiles; with a
# single profile only that environment is updated.
pixi_lock() {
    pixi_bootstrap
    _px_gen_manifest
    if [[ $# -ge ${#PROFILES[@]} || ! -f "$PIXI_LOCK" ]]; then
        info "Solving all environments → pixi.lock ..."
        (cd "$SCRIPT_DIR" && _px lock)
    else
        local p envs=()
        for p in "$@"; do envs+=(-e "$(_px_env "$p")"); done
        info "Updating ${*} in pixi.lock ..."
        (cd "$SCRIPT_DIR" && _px update "${envs[@]}")
    fi
    info "Wrote pixi.lock  (install with: $0 build)"
}

pixi_update() {
    local was_running=0
    if pixi_is_running; then was_running=1; pixi_stop; fi
    pixi_lock "${PROFILE:-lab}"
    pixi_build --profile "${PROFILE:-lab}"
    [[ $was_running -eq 1 ]] && pixi_start
    info "Update complete."
}

pixi_start() {
    ensure_workspace
    if pixi_is_running; then
        warn "Already running."
        return 0
    fi
    _px_need_env
    if [[ "${GDL_MODE:-lab}" == "idle" ]]; then
        warn "Mode is 'idle' — nothing to start on the pixi backend."
        echo "  Use the environment directly:  $0 shell   (or: $0 mode lab)"
        return 0
    fi
    if port_open "${GDL_PORT:-8888}"; then
        error "Port ${GDL_PORT:-8888} is already in use. Change it: $0 port <n>"
        exit 1
    fi

    mkdir -p "$PIXI_STATE"
    local root token hook args=()
    root="$(_px_root)"
    gdl_build_root_farm "$root"
    gdl_env_kv "$root"

    if [[ -n "${JUPYTER_TOKEN+x}" ]]; then
        token="$JUPYTER_TOKEN"
    else
        [[ -s "$(_px_tokf)" ]] || { od -An -tx1 -N24 /dev/urandom | tr -d ' \n' > "$(_px_tokf)"; chmod 600 "$(_px_tokf)"; }
        token="$(cat "$(_px_tokf)")"
    fi

    args=(--no-browser --ip="${GDL_BIND:-127.0.0.1}" --port="${GDL_PORT:-8888}"
          "--ServerApp.root_dir=${root}" "--IdentityProvider.token=${token}")
    if [[ -n "${GDL_OPEN:-}" && -d "${root}/${GDL_OPEN}" ]]; then
        args+=("--ContentsManager.preferred_dir=${GDL_OPEN}")
    fi

    hook="$(_px shell-hook --manifest-path "$PIXI_MANIFEST" -e "$(_px_env)" --frozen --shell bash)"
    info "Starting  [instance: ${GDL_INSTANCE}, env: $(_px_env), port: ${GDL_PORT:-8888}]..."
    local launcher=()
    command -v setsid &>/dev/null && launcher=(setsid)
    (
        set +u
        eval "$hook"
        cd "${root}/workspace" || exit 1
        exec "${launcher[@]+"${launcher[@]}"}" env "${GDL_ENV_KV[@]}" jupyter lab "${args[@]}"
    ) > "$(_px_logf)" 2>&1 < /dev/null &
    echo $! > "$(_px_pidf)"

    local elapsed=0
    printf "  Waiting for Jupyter"
    while [[ $elapsed -lt 60 ]]; do
        if ! pixi_is_running; then
            echo " failed."; error "Jupyter exited — see: $0 logs"; tail -20 "$(_px_logf)" >&2; exit 1
        fi
        port_open "${GDL_PORT:-8888}" && { echo " ready."; return 0; }
        printf "."; sleep 1; elapsed=$((elapsed + 1))
    done
    echo ""; warn "Still starting — check: $0 logs"
}

pixi_stop() {
    local pidf pid
    pidf="$(_px_pidf)"
    if ! pixi_is_running; then
        info "Not running."; rm -f -- "$pidf"; return 0
    fi
    pid="$(cat "$pidf")"
    info "Stopping Jupyter (pid ${pid})..."
    kill -TERM -- "-${pid}" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    local _
    for _ in $(seq 1 20); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL -- "-${pid}" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    fi
    rm -f -- "$pidf"
    info "Stopped."
}

pixi_exec() {
    _px_need_env
    mkdir -p "$PIXI_STATE"
    local root; root="$(_px_root)"
    gdl_build_root_farm "$root" >/dev/null
    gdl_env_kv "$root"
    [[ $# -eq 0 ]] && set -- bash
    _px_in "${PROFILE:-lab}" bash -c 'cd "$1" && shift && exec env "$@"' _ \
        "${root}/workspace" "${GDL_ENV_KV[@]}" "$@"
}

pixi_logs() {
    [[ -f "$(_px_logf)" ]] || { info "No log yet."; return 0; }
    tail -n 50 -f "$(_px_logf)"
}

pixi_url_token() {
    pixi_is_running || return 0
    [[ -n "${JUPYTER_TOKEN+x}" ]] && return 0
    cat "$(_px_tokf)" 2>/dev/null || true
}

pixi_status() {
    local prefix; prefix="$(_px_prefix)"
    heading "pixi  ·  instance ${GDL_INSTANCE}"
    if pixi_is_running; then
        echo -e "  State:    ${GREEN}running${NC}  (pid $(cat "$(_px_pidf)"), $(pixi_health))"
    else
        echo -e "  State:    ${RED}stopped${NC}"
    fi
    echo "  Binary:   ${PIXI_BIN:-not installed (installed on first build)}"
    if [[ -x "${prefix}/bin/python" ]]; then
        echo "  Env:      $(_px_env)  ${prefix}  ($(du -sh "$prefix" 2>/dev/null | cut -f1))"
    else
        echo "  Env:      $(_px_env)  (not installed — $0 build)"
    fi
    echo "  Root:     $(_px_root)"
    echo "  Log:      $(_px_logf)"
    [[ -f "$PIXI_LOCK" ]] && echo "  Lock:     pixi.lock" || echo "  Lock:     none (next build solves latest)"
}

pixi_clean() {
    local env; env="$(_px_env)"
    echo -e "${YELLOW}This will remove the pixi environment '${env}' (shared by every instance using profile ${PROFILE}).${NC}"
    if confirm "Are you sure?" N; then
        pixi_is_running && pixi_stop
        _px_guard_env "${PROFILE:-lab}"
        if _px_find; then (cd "$SCRIPT_DIR" && _px clean -e "$env"); fi
        info "Cleaned."
    else
        info "Cancelled."
    fi
}
