#!/usr/bin/env bash
# Installs vision_service.py as a service that starts at boot (plan a' on the UNO Q, or plan b on the Jetson).
# Run from the project folder:  bash tools/install_service.sh
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)/python"
PY="$HOME/breathe-venv/bin/python"
[ -x "$PY" ] || { echo "Missing $PY - create the venv first (GUIDE Part 9)"; exit 1; }
sudo tee /etc/systemd/system/breathe-vision.service >/dev/null <<UNIT
[Unit]
Description=BREATHE Vision camera service
After=network.target
[Service]
User=$USER
WorkingDirectory=$DIR
ExecStart=$PY vision_service.py
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now breathe-vision
sleep 3
curl -s http://127.0.0.1:8765/health && echo && echo "SERVICE OK"
