#!/usr/bin/env bash
set -Eeuo pipefail

REPO='waqaarhussain/telegram-bridge'
BRANCH='main'
RAW="https://raw.githubusercontent.com/${REPO}/${BRANCH}"
BASE='/opt/forexpert-bridge'
MODE="${1:-install}"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo 'Run as root or pipe the installer to sudo bash.' >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

if [[ "$MODE" != '--update' ]]; then
  apt-get update
  apt-get install -y python3 python3-venv python3-pip ca-certificates curl sqlite3
fi

mkdir -p "$BASE"

# Preserve these local-only files on reinstall/update:
#   config.json
#   telegram_session.session
#   bridge.sqlite3

fetch() {
  local remote="$1"
  local target="$2"
  curl -fsSL "$RAW/$remote" -o "$target"
}

fetch bridge.py "$BASE/bridge.py"
fetch setup.py "$BASE/setup.py"
fetch reconfigure.sh "$BASE/reconfigure.sh"
fetch requirements.txt "$BASE/requirements.txt"
fetch forexpert-bridge.service /etc/systemd/system/forexpert-bridge.service

chmod 700 "$BASE"
chmod 600 "$BASE/bridge.py" "$BASE/setup.py" "$BASE/requirements.txt"
chmod 700 "$BASE/reconfigure.sh"

if [[ ! -x "$BASE/.venv/bin/python" ]]; then
  python3 -m venv "$BASE/.venv"
fi
"$BASE/.venv/bin/python" -m pip install --upgrade pip >/dev/null
"$BASE/.venv/bin/pip" install -r "$BASE/requirements.txt"
"$BASE/.venv/bin/python" -m py_compile "$BASE/bridge.py" "$BASE/setup.py"

if [[ ! -f "$BASE/config.json" || ! -f "$BASE/telegram_session.session" ]]; then
  echo
  echo '============================================================'
  echo ' Telegram login + source/destination selection'
  echo '============================================================'
  "$BASE/.venv/bin/python" "$BASE/setup.py"
fi

chmod 600 "$BASE/config.json" 2>/dev/null || true
chmod 600 "$BASE/telegram_session.session" 2>/dev/null || true
chmod 600 "$BASE/bridge.sqlite3" 2>/dev/null || true

cat >/usr/local/sbin/update-live <<'HELPER'
#!/usr/bin/env bash
set -Eeuo pipefail
curl -fsSL https://raw.githubusercontent.com/waqaarhussain/telegram-bridge/main/install.sh | bash -s -- --update
HELPER
chmod 755 /usr/local/sbin/update-live

cat >/usr/local/sbin/bridge-config <<'HELPER'
#!/usr/bin/env bash
set -Eeuo pipefail
exec /opt/forexpert-bridge/reconfigure.sh
HELPER
chmod 755 /usr/local/sbin/bridge-config

systemctl daemon-reload
systemctl enable forexpert-bridge >/dev/null
systemctl restart forexpert-bridge

echo
echo '============================================================'
echo ' Telegram Bridge installed'
echo '============================================================'
echo
echo 'Status:'
systemctl --no-pager --full status forexpert-bridge || true
echo
echo 'Live logs:'
echo '  sudo journalctl -u forexpert-bridge -f'
echo
echo 'Change source/destination:'
echo '  sudo bridge-config'
echo
echo 'Future updates:'
echo '  sudo update-live'
echo
