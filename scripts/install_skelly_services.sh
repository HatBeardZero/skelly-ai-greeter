#!/usr/bin/env bash
# Installs two systemd USER services so the Skelly bridge and the greeter start on boot
# and restart if they crash. Run once as your normal user (not root):
#   bash scripts/install_skelly_services.sh
#
# Before running:
#  - skelly_greeter.py must be at ~/skelly_greeter.py (or edit GREETER_PATH below)
#  - ~/.skelly_env must exist (copy .env.example and fill it in)
#  - the greeter venv must exist at ~/greeter-venv
#  - the Skelly bridge repo must be cloned to ~/SkellyUltra
set -euo pipefail

GREETER_PATH="${GREETER_PATH:-%h/skelly_greeter.py}"
BRIDGE_DIR="${BRIDGE_DIR:-%h/SkellyUltra/custom_components/skelly_ultra/skelly_ultra_srv}"

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this as your normal user, not root (PipeWire lives in your user session)." >&2
  exit 1
fi
[ -f "$HOME/.skelly_env" ] || { echo "Missing ~/.skelly_env (copy .env.example and fill it in)." >&2; exit 1; }

UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"

cat > "$UNIT_DIR/skelly-server.service" <<UNIT
[Unit]
Description=Skelly Ultra Bluetooth/REST bridge
After=pipewire.service wireplumber.service
Wants=pipewire.service wireplumber.service

[Service]
WorkingDirectory=${BRIDGE_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 run_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
UNIT

cat > "$UNIT_DIR/skelly-greeter.service" <<UNIT
[Unit]
Description=Skelly AI greeter
After=skelly-server.service
Wants=skelly-server.service

[Service]
EnvironmentFile=%h/.skelly_env
Environment=PYTHONUNBUFFERED=1
ExecStart=%h/greeter-venv/bin/python ${GREETER_PATH}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
UNIT

# Let user services start at boot without anyone logging in
sudo loginctl enable-linger "$USER"

systemctl --user daemon-reload
systemctl --user enable skelly-server.service skelly-greeter.service

cat <<'MSG'

Installed and enabled (not started yet).

1. Stop any copies you are running by hand so the ports are free.
2. Start them:   systemctl --user start skelly-server skelly-greeter
3. Logs:         journalctl --user-unit skelly-greeter -f
4. Status:       systemctl --user status skelly-server skelly-greeter
5. Reboot test:  sudo reboot, wait two minutes, then check the Skelly's sink is back:
                 pactl list sinks short | grep -i <your speaker address with _ for :>

After editing the greeter or ~/.skelly_env:  systemctl --user restart skelly-greeter
MSG
