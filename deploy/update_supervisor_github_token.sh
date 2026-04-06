#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: sudo bash deploy/update_supervisor_github_token.sh [options]

Updates LABBREW_GITHUB_USER and LABBREW_GITHUB_TOKEN in the supervisor env file.
Creates a timestamped backup before writing.

Options:
  --service-name NAME     systemd service name. Default: labbrew-supervisor
  --env-file PATH         Explicit env file path. Default: /etc/labbrew/<service>.env
  --github-user USER      GitHub username (or x-access-token). Default: x-access-token
  --token TOKEN           Token value (less secure: may appear in shell history/process list)
  --token-file PATH       Read token from first line of file.
  --no-restart            Do not restart service after writing env file.
  --help                  Show this help text.

If no token is provided via --token or --token-file, the script prompts securely.
EOF
}

fail() {
  printf '[labbrew-token-update] ERROR: %s\n' "$*" >&2
  exit 1
}

warn() {
  printf '[labbrew-token-update] WARNING: %s\n' "$*" >&2
}

log() {
  printf '[labbrew-token-update] %s\n' "$*"
}

require_root() {
  if [[ ${EUID} -ne 0 ]]; then
    fail 'Run this script with sudo or as root.'
  fi
}

SERVICE_NAME='labbrew-supervisor'
ENV_FILE=''
GITHUB_USER='x-access-token'
TOKEN=''
TOKEN_FILE=''
RESTART_SERVICE='1'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service-name)
      SERVICE_NAME="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --github-user)
      GITHUB_USER="$2"
      shift 2
      ;;
    --token)
      TOKEN="$2"
      shift 2
      ;;
    --token-file)
      TOKEN_FILE="$2"
      shift 2
      ;;
    --no-restart)
      RESTART_SERVICE='0'
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

require_root

if [[ -z "$ENV_FILE" ]]; then
  ENV_FILE="/etc/labbrew/${SERVICE_NAME}.env"
fi

[[ -f "$ENV_FILE" ]] || fail "Env file not found: $ENV_FILE"

if [[ -n "$TOKEN" && -n "$TOKEN_FILE" ]]; then
  fail 'Use only one of --token or --token-file.'
fi

if [[ -n "$TOKEN" ]]; then
  warn 'Using --token can expose secrets in shell history/process lists. Prefer --token-file or secure prompt.'
fi

if [[ -n "$TOKEN_FILE" ]]; then
  [[ -r "$TOKEN_FILE" ]] || fail "Cannot read token file: $TOKEN_FILE"
  TOKEN="$(head -n 1 "$TOKEN_FILE" | tr -d '\r\n')"
fi

if [[ -z "$TOKEN" ]]; then
  read -r -s -p 'GitHub token: ' TOKEN
  printf '\n'
fi

[[ -n "$TOKEN" ]] || fail 'Token is empty.'
[[ -n "$GITHUB_USER" ]] || fail 'GitHub user is empty.'

BACKUP_PATH="${ENV_FILE}.bak.$(date +%Y%m%d-%H%M%S)"
cp "$ENV_FILE" "$BACKUP_PATH"
log "Backup created: $BACKUP_PATH"

TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

# Remove previous auth values and append fresh ones.
sed '/^LABBREW_GITHUB_USER=/d;/^LABBREW_GITHUB_TOKEN=/d' "$ENV_FILE" > "$TMP_FILE"
printf 'LABBREW_GITHUB_USER=%q\n' "$GITHUB_USER" >> "$TMP_FILE"
printf 'LABBREW_GITHUB_TOKEN=%q\n' "$TOKEN" >> "$TMP_FILE"

install -m 640 "$TMP_FILE" "$ENV_FILE"
unset TOKEN

log "Updated GitHub updater credentials in: $ENV_FILE"

if [[ "$RESTART_SERVICE" == '1' ]]; then
  log "Restarting service: $SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
  systemctl --no-pager --full status "$SERVICE_NAME" || true
else
  log 'Skipping service restart (--no-restart).'
fi

log 'Done.'
