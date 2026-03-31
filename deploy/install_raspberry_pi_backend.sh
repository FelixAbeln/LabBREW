#!/usr/bin/env bash
set -euo pipefail

TMP_CLONE_DIR=''

cleanup() {
  if [[ -n "$TMP_CLONE_DIR" && -d "$TMP_CLONE_DIR" ]]; then
    rm -rf "$TMP_CLONE_DIR"
  fi
}

trap cleanup EXIT

usage() {
  cat <<'EOF'
Usage: sudo bash deploy/install_raspberry_pi_backend.sh [options]

Installs the LabBREW backend stack on a Raspberry Pi without the React frontend.
The script:
  - installs OS packages needed for the Python backend, mDNS discovery, and BLE support
  - optionally clones the repository from GitHub
  - copies this repository into /opt/labbrew
  - creates a virtual environment
  - installs Python dependencies from requirements.txt and the project package
  - writes /etc/labbrew/labbrew-supervisor.env
  - writes and enables a systemd service for the topology supervisor
  - verifies that the service starts and the local agent API answers
  - can set the Pi hostname to match the fermenter name

Options:
  --source-dir PATH       Source repository to install from.
  --repo-url URL          Git repository to clone when source-dir is not used.
                           Default (non-interactive): https://github.com/FelixAbeln/LabBREW.git
  --git-ref REF           Optional git branch/tag/commit to check out after clone.
  --install-dir PATH      Target install directory. Default: /opt/labbrew
  --service-name NAME     systemd unit name. Default: labbrew-supervisor
  --run-user USER         Dedicated service user. Default: labbrew
  --node-id ID            Fermenter node id. Default: 01
  --node-name NAME        Fermenter node display name. Default: hostname
  --hostname NAME         Explicit Pi hostname/network name to apply.
  --set-hostname          Force hostname update to the chosen hostname.
  --no-set-hostname       Do not change the Pi hostname.
  --advertise-host HOST   Advertised host/IP for service discovery. Default: first non-loopback IPv4 or 127.0.0.1
  --agent-host HOST       Bind host for the local agent API. Default: 0.0.0.0
  --agent-port PORT       Bind port for the local agent API. Default: 8780
  --check-interval SEC    Supervisor health-check interval. Default: 2.0
  --skip-apt              Skip apt package installation.
  --non-interactive       Fail instead of prompting when required values are missing.
  --help                  Show this help text.

After installation:
  - edit /etc/labbrew/<service-name>.env if you want to change node identity or topology path
  - inspect logs with: journalctl -u <service-name> -f
EOF
}

log() {
  printf '[labbrew-install] %s\n' "$*"
}

fail() {
  printf '[labbrew-install] ERROR: %s\n' "$*" >&2
  exit 1
}

warn() {
  printf '[labbrew-install] WARNING: %s\n' "$*" >&2
}

require_command() {
  local command_name="$1"
  local install_hint="$2"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    fail "Required command '$command_name' is not available. $install_hint"
  fi
}

is_interactive() {
  [[ -t 0 && -t 1 && "$NON_INTERACTIVE" != '1' ]]
}

prompt_default() {
  local variable_name="$1"
  local label="$2"
  local default_value="$3"
  local current_value="${!variable_name:-}"
  local answer=''

  if [[ -n "$current_value" ]]; then
    return
  fi

  if ! is_interactive; then
    printf -v "$variable_name" '%s' "$default_value"
    return
  fi

  read -r -p "$label [$default_value]: " answer
  if [[ -z "$answer" ]]; then
    answer="$default_value"
  fi
  printf -v "$variable_name" '%s' "$answer"
}

prompt_yes_no() {
  local variable_name="$1"
  local label="$2"
  local default_value="$3"
  local current_value="${!variable_name:-}"
  local prompt_suffix='[y/N]'
  local answer=''

  if [[ "$default_value" == '1' ]]; then
    prompt_suffix='[Y/n]'
  fi

  if [[ -n "$current_value" ]]; then
    return
  fi

  if ! is_interactive; then
    printf -v "$variable_name" '%s' "$default_value"
    return
  fi

  while true; do
    read -r -p "$label $prompt_suffix: " answer
    answer="${answer,,}"
    if [[ -z "$answer" ]]; then
      printf -v "$variable_name" '%s' "$default_value"
      return
    fi
    if [[ "$answer" == 'y' || "$answer" == 'yes' ]]; then
      printf -v "$variable_name" '1'
      return
    fi
    if [[ "$answer" == 'n' || "$answer" == 'no' ]]; then
      printf -v "$variable_name" '0'
      return
    fi
  done
}

sanitize_hostname() {
  local raw="$1"
  local cleaned
  cleaned="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9-]+/-/g; s/^-+//; s/-+$//; s/-{2,}/-/g')"
  cleaned="${cleaned:0:63}"
  cleaned="${cleaned%-}"
  if [[ -z "$cleaned" ]]; then
    cleaned='labbrew-node'
  fi
  printf '%s\n' "$cleaned"
}

require_root() {
  if [[ ${EUID} -ne 0 ]]; then
    fail 'Run this installer with sudo or as root.'
  fi
}

detect_advertise_host() {
  local detected
  detected="$(hostname -I 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i !~ /^127\./) { print $i; exit }}')"
  if [[ -n "${detected}" ]]; then
    printf '%s\n' "$detected"
  else
    printf '127.0.0.1\n'
  fi
}

validate_python_version() {
  local version_output major minor
  version_output="$(python3 -c 'import sys; print(f"{sys.version_info[0]} {sys.version_info[1]}")' 2>/dev/null)" \
    || fail 'python3 is required but was not found on PATH.'
  read -r major minor <<< "$version_output"
  if [[ "$major" -lt 3 || ( "$major" -eq 3 && "$minor" -lt 11 ) ]]; then
    fail "LabBREW requires Python 3.11 or newer, but python3 resolved to ${major}.${minor}. Use Raspberry Pi OS Bookworm or newer, or provide Python 3.11+ before running the installer."
  fi
}

verify_runtime_commands() {
  require_command python3 'Install Python 3.11+ or rerun the installer without --skip-apt.'
  require_command git 'Install git or rerun the installer without --skip-apt.'
  require_command rsync 'Install rsync or rerun the installer without --skip-apt.'
  require_command systemctl 'This installer expects a systemd-based Raspberry Pi OS image.'
  require_command hostnamectl 'This installer expects hostnamectl to be available on the target system.'
}

SOURCE_DIR=''
REPO_URL=''
DEFAULT_REPO_URL='https://github.com/FelixAbeln/LabBREW.git'
GIT_REF=''
INSTALL_DIR='/opt/labbrew'
SERVICE_NAME='labbrew-supervisor'
RUN_USER='labbrew'
RUN_GROUP=''
NODE_ID='01'
NODE_NAME="$(hostname)"
PI_HOSTNAME=''
SET_HOSTNAME=''
ADVERTISE_HOST="$(detect_advertise_host)"
AGENT_HOST='0.0.0.0'
AGENT_PORT='8780'
CHECK_INTERVAL='2.0'
SKIP_APT='0'
NON_INTERACTIVE='0'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-dir)
      SOURCE_DIR="$2"
      shift 2
      ;;
    --repo-url)
      REPO_URL="$2"
      shift 2
      ;;
    --git-ref)
      GIT_REF="$2"
      shift 2
      ;;
    --install-dir)
      INSTALL_DIR="$2"
      shift 2
      ;;
    --service-name)
      SERVICE_NAME="$2"
      shift 2
      ;;
    --run-user)
      RUN_USER="$2"
      shift 2
      ;;
    --node-id)
      NODE_ID="$2"
      shift 2
      ;;
    --node-name)
      NODE_NAME="$2"
      shift 2
      ;;
    --hostname)
      PI_HOSTNAME="$2"
      shift 2
      ;;
    --set-hostname)
      SET_HOSTNAME='1'
      shift
      ;;
    --no-set-hostname)
      SET_HOSTNAME='0'
      shift
      ;;
    --advertise-host)
      ADVERTISE_HOST="$2"
      shift 2
      ;;
    --agent-host)
      AGENT_HOST="$2"
      shift 2
      ;;
    --agent-port)
      AGENT_PORT="$2"
      shift 2
      ;;
    --check-interval)
      CHECK_INTERVAL="$2"
      shift 2
      ;;
    --skip-apt)
      SKIP_APT='1'
      shift
      ;;
    --non-interactive)
      NON_INTERACTIVE='1'
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage >&2
      fail "Unknown argument: $1"
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

resolve_source_dir() {
  if [[ -n "$SOURCE_DIR" ]]; then
    SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
    return
  fi

  if [[ -z "$REPO_URL" ]] && is_interactive; then
    local default_repo=''
    read -r -p "GitHub repository URL to install from (leave blank to use local checkout): " REPO_URL
    if [[ -z "$REPO_URL" ]]; then
      default_repo="$(cd "$SCRIPT_DIR/.." && pwd)"
      log "Using local checkout at $default_repo"
      SOURCE_DIR="$default_repo"
      return
    fi
  fi

  if [[ -n "$REPO_URL" ]]; then
    TMP_CLONE_DIR="$(mktemp -d /tmp/labbrew-src.XXXXXX)"
    log "Cloning repository from $REPO_URL"
    git clone "$REPO_URL" "$TMP_CLONE_DIR"
    if [[ -n "$GIT_REF" ]]; then
      log "Checking out git ref $GIT_REF"
      git -C "$TMP_CLONE_DIR" checkout "$GIT_REF"
    fi
    SOURCE_DIR="$TMP_CLONE_DIR"
    return
  fi

  if [[ "$NON_INTERACTIVE" == '1' ]]; then
    REPO_URL="$DEFAULT_REPO_URL"
    log "Using default repository URL: $REPO_URL"
    TMP_CLONE_DIR="$(mktemp -d /tmp/labbrew-src.XXXXXX)"
    log "Cloning repository from $REPO_URL"
    git clone "$REPO_URL" "$TMP_CLONE_DIR"
    if [[ -n "$GIT_REF" ]]; then
      log "Checking out git ref $GIT_REF"
      git -C "$TMP_CLONE_DIR" checkout "$GIT_REF"
    fi
    SOURCE_DIR="$TMP_CLONE_DIR"
    return
  fi

  SOURCE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
}

run_wizard() {
  prompt_default NODE_ID 'Fermenter node id' "$NODE_ID"
  prompt_default NODE_NAME 'Fermenter display name' "$NODE_NAME"
  if [[ -z "$PI_HOSTNAME" ]]; then
    PI_HOSTNAME="$(sanitize_hostname "$NODE_NAME")"
  fi
  prompt_default PI_HOSTNAME 'Pi hostname / network name' "$PI_HOSTNAME"
  prompt_yes_no SET_HOSTNAME 'Set the Raspberry Pi hostname to match this network name?' '1'
  prompt_default ADVERTISE_HOST 'Advertised host/IP for clients' "$ADVERTISE_HOST"
}

VENV_DIR="$INSTALL_DIR/.venv"
ENV_DIR='/etc/labbrew'
ENV_FILE="$ENV_DIR/${SERVICE_NAME}.env"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
LOG_DIR='/var/log/labbrew'
WRAPPER_DIR="$INSTALL_DIR/bin"
WRAPPER_PATH="$WRAPPER_DIR/run_${SERVICE_NAME}.sh"
CONFIG_PATH="$INSTALL_DIR/data/system_topology.yaml"
OPTIONAL_PYTHON_PACKAGES=(
  bleak
  fmpy
  pyarrow
)

install_apt_packages() {
  if [[ "$SKIP_APT" == '1' ]]; then
    log 'Skipping apt package installation.'
    return
  fi

  log 'Installing OS packages required for the backend runtime.'
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y \
    avahi-daemon \
    bluez \
    build-essential \
    ca-certificates \
    curl \
    dbus \
    git \
    libffi-dev \
    libnss-mdns \
    libssl-dev \
    pkg-config \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    rsync
}

enable_optional_os_services() {
  if systemctl list-unit-files avahi-daemon.service >/dev/null 2>&1; then
    log 'Enabling avahi-daemon for .local name resolution and service discovery.'
    systemctl enable --now avahi-daemon || warn 'Could not enable avahi-daemon automatically.'
  fi

  if systemctl list-unit-files bluetooth.service >/dev/null 2>&1; then
    log 'Enabling bluetooth service for BLE-based datasources.'
    systemctl enable --now bluetooth || warn 'Could not enable bluetooth automatically.'
  fi
}

print_hardware_notes() {
  cat <<EOF

Hardware-specific notes:
  - Tilt BLE support expects the Bluetooth stack to be available (bluez/dbus installed; bluetooth service running).
  - mDNS discovery and .local hostnames work best with avahi-daemon enabled.
  - Modbus TCP relay datasources do not need extra Pi drivers.
  - Brewtools Kvaser datasources need the vendor's Linux Kvaser CANlib driver/userspace installed separately.
    This installer does not fetch or install Kvaser drivers automatically.
EOF
}

install_optional_python_packages() {
  local package_name
  for package_name in "${OPTIONAL_PYTHON_PACKAGES[@]}"; do
    log "Installing optional Python package: $package_name"
    if ! "$VENV_DIR/bin/pip" install "$package_name"; then
      warn "Optional package '$package_name' could not be installed. Dry runs can continue without it, but related features may be unavailable."
    fi
  done
}

apply_hostname() {
  if [[ "$SET_HOSTNAME" != '1' ]]; then
    log 'Skipping hostname change.'
    return
  fi

  log "Setting system hostname to $PI_HOSTNAME"
  hostnamectl set-hostname "$PI_HOSTNAME"
}

ensure_run_user() {
  if id -u "$RUN_USER" >/dev/null 2>&1; then
    RUN_GROUP="$(id -gn "$RUN_USER")"
    log "Using existing service user: $RUN_USER"
    return
  fi

  log "Creating dedicated service user: $RUN_USER"
  useradd \
    --system \
    --create-home \
    --home-dir "$INSTALL_DIR" \
    --shell /usr/sbin/nologin \
    --user-group \
    "$RUN_USER"
  RUN_GROUP="$(id -gn "$RUN_USER")"
}

sync_repository() {
  log "Copying repository to $INSTALL_DIR"
  mkdir -p "$INSTALL_DIR"
  rsync -a --delete \
    --exclude '.venv/' \
    --exclude '.pytest_cache/' \
    --exclude '__pycache__/' \
    --exclude 'node_modules/' \
    --exclude 'dist/' \
    --exclude 'htmlcov/' \
    --exclude 'logs/' \
    "$SOURCE_DIR/" "$INSTALL_DIR/"
}

install_python_runtime() {
  log 'Creating Python virtual environment.'
  validate_python_version
  python3 -m venv "$VENV_DIR"

  log 'Installing core Python packages from the project metadata.'
  "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel
  "$VENV_DIR/bin/pip" install "$INSTALL_DIR"
  install_optional_python_packages
}

write_environment_file() {
  log "Writing environment file to $ENV_FILE"
  mkdir -p "$ENV_DIR"
  {
    printf 'CONFIG_PATH=%q\n' "$CONFIG_PATH"
    printf 'ROOT_DIR=%q\n' "$INSTALL_DIR"
    printf 'LOG_DIR=%q\n' "$LOG_DIR"
    printf 'NODE_ID=%q\n' "$NODE_ID"
    printf 'NODE_NAME=%q\n' "$NODE_NAME"
    printf 'ADVERTISE_HOST=%q\n' "$ADVERTISE_HOST"
    printf 'AGENT_HOST=%q\n' "$AGENT_HOST"
    printf 'AGENT_PORT=%q\n' "$AGENT_PORT"
    printf 'CHECK_INTERVAL=%q\n' "$CHECK_INTERVAL"
  } > "$ENV_FILE"
  chown root:"$RUN_GROUP" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
}

write_wrapper_script() {
  log "Writing supervisor wrapper script to $WRAPPER_PATH"
  mkdir -p "$WRAPPER_DIR"
  cat > "$WRAPPER_PATH" <<EOF
#!/usr/bin/env bash
set -euo pipefail

source "$ENV_FILE"

exec "$VENV_DIR/bin/labbrew-supervisor" \
  --config "\$CONFIG_PATH" \
  --root-dir "\$ROOT_DIR" \
  --log-dir "\$LOG_DIR" \
  --advertise-host "\$ADVERTISE_HOST" \
  --node-id "\$NODE_ID" \
  --node-name "\$NODE_NAME" \
  --agent-host "\$AGENT_HOST" \
  --agent-port "\$AGENT_PORT" \
  --check-interval "\$CHECK_INTERVAL"
EOF
  chmod 755 "$WRAPPER_PATH"
}

write_systemd_unit() {
  log "Writing systemd unit to $UNIT_FILE"
  cat > "$UNIT_FILE" <<EOF
[Unit]
Description=LabBREW backend supervisor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_GROUP
WorkingDirectory=$INSTALL_DIR
ExecStart=$WRAPPER_PATH
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
  chmod 644 "$UNIT_FILE"
}

set_permissions() {
  log 'Preparing writable directories and ownership.'
  mkdir -p "$LOG_DIR"
  chown -R "$RUN_USER:$RUN_GROUP" "$INSTALL_DIR" "$LOG_DIR"
}

enable_service() {
  log "Reloading systemd and enabling $SERVICE_NAME"
  systemctl daemon-reload
  systemctl enable --now "$SERVICE_NAME"
}

verify_installation() {
  local verify_host='127.0.0.1'
  local info_url="http://${verify_host}:${AGENT_PORT}/agent/info"
  local summary_url="http://${verify_host}:${AGENT_PORT}/agent/summary"
  local response=''
  local attempt=''

  log "Verifying $SERVICE_NAME startup and local agent API"

  for attempt in $(seq 1 30); do
    if systemctl is-active --quiet "$SERVICE_NAME"; then
      break
    fi
    sleep 2
  done

  if ! systemctl is-active --quiet "$SERVICE_NAME"; then
    systemctl --no-pager --full status "$SERVICE_NAME" || true
    journalctl -u "$SERVICE_NAME" -n 80 --no-pager || true
    fail "Service $SERVICE_NAME did not become active during verification."
  fi

  for attempt in $(seq 1 30); do
    response="$(curl -fsS --max-time 5 "$info_url" 2>/dev/null || true)"
    if [[ -n "$response" ]]; then
      break
    fi
    sleep 2
  done

  if [[ -z "$response" ]]; then
    journalctl -u "$SERVICE_NAME" -n 80 --no-pager || true
    fail "Local agent endpoint $info_url did not respond during verification."
  fi

  python3 - "$response" "$NODE_ID" "$NODE_NAME" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
expected_id = sys.argv[2]
expected_name = sys.argv[3]

if payload.get("node_id") != expected_id:
    raise SystemExit(f"agent info node_id mismatch: expected {expected_id!r}, got {payload.get('node_id')!r}")
if payload.get("node_name") != expected_name:
    raise SystemExit(f"agent info node_name mismatch: expected {expected_name!r}, got {payload.get('node_name')!r}")
PY

  if ! curl -fsS --max-time 5 "$summary_url" >/dev/null; then
    journalctl -u "$SERVICE_NAME" -n 80 --no-pager || true
    fail "Local agent summary endpoint $summary_url did not respond during verification."
  fi

  log "Verification succeeded: $SERVICE_NAME is active and the local agent API responded."
}

print_summary() {
  cat <<EOF

LabBREW backend install complete.

Source:          $SOURCE_DIR
Installed to:    $INSTALL_DIR
Virtualenv:      $VENV_DIR
Service:         $SERVICE_NAME
Environment:     $ENV_FILE
Topology config: $CONFIG_PATH
Node identity:   $NODE_ID / $NODE_NAME
Hostname:        $PI_HOSTNAME (changed: $SET_HOSTNAME)
Logs:            $LOG_DIR and journalctl -u $SERVICE_NAME

Useful commands:
  sudo systemctl status $SERVICE_NAME
  sudo journalctl -u $SERVICE_NAME -f
  sudo systemctl restart $SERVICE_NAME

If this node should advertise a different address or name, edit:
  $ENV_FILE
and then run:
  sudo systemctl restart $SERVICE_NAME
EOF

  print_hardware_notes
}

require_root
run_wizard
PI_HOSTNAME="$(sanitize_hostname "$PI_HOSTNAME")"
if [[ -z "$SET_HOSTNAME" ]]; then
  SET_HOSTNAME='1'
fi
install_apt_packages
verify_runtime_commands
resolve_source_dir
if [[ -z "$SOURCE_DIR" ]]; then
  SOURCE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
fi

[[ -f "$SOURCE_DIR/pyproject.toml" ]] || fail "No pyproject.toml found in source directory: $SOURCE_DIR"
[[ -f "$SOURCE_DIR/data/system_topology.yaml" ]] || fail "No topology file found at $SOURCE_DIR/data/system_topology.yaml"

apply_hostname
ensure_run_user
sync_repository
install_python_runtime
enable_optional_os_services
write_environment_file
write_wrapper_script
write_systemd_unit
set_permissions
enable_service
verify_installation
print_summary