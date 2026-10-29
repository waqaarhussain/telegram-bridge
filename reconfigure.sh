#!/usr/bin/env bash
set -Eeuo pipefail
systemctl stop forexpert-bridge 2>/dev/null || true
/opt/forexpert-bridge/.venv/bin/python /opt/forexpert-bridge/setup.py
systemctl restart forexpert-bridge
echo
echo 'Bridge restarted.'
echo 'Live logs: sudo journalctl -u forexpert-bridge -f'
