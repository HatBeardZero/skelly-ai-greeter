#!/usr/bin/env bash
# Installs two systemd USER services so the Skelly server and greeter start on boot
# and restart themselves if they crash. Run once, as your normal user (not root):
#   bash install_skelly_services.sh
#
# Before running:
#  - ~/skelly_greeter.py must be the current version
#  - ~/.skelly_env must contain the line:  ANTHROPIC_API_KEY=sk-ant-...
#  - the greeter venv must exist at ~/greeter-venv
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this as your normal user, not root (PipeWire lives in your user session)." >&2
  exit 1
fi

UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"

cat > "$UNIT_DIR/skelly-server.service" <<'EOF'
[Unit]
Description=Skelly Ultra Bluetooth/REST server
After=pipewire.service wireplumber.service
Wants=pipewire.service wireplumber.service

[Service]
WorkingDirectory=%h/SkellyUltra/custom_components/skelly_ultra/skelly_ultra_srv
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 run_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

cat > "$UNIT_DIR/skelly-greeter.service" <<'EOF'
[Unit]
Description=Skelly AI greeter
After=skelly-server.service
Wants=skelly-server.service

[Service]
EnvironmentFile=%h/.skelly_env
Environment=FILLER_DIR=%h/fillers
Environment="SOX_EFFECT=gain -3 pitch -300 reverb 30 50 80"
Environment=PYTHONUNBUFFERED=1
ExecStart=%h/greeter-venv/bin/python %h/skelly_greeter.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

# Let user services start at boot without anyone logging in
sudo loginctl enable-linger "$USER"

systemctl --user daemon-reload
systemctl --user enable skelly-server.service skelly-greeter.service

cat <<'MSG'

Installed and enabled (not started yet).

1. Stop any copies you're running by hand (the tmux windows / Ctrl+C), so the ports are free.
2. Start them now:
     systemctl --user start skelly-server skelly-greeter
3. Watch the greeter's log:
     journalctl --user -u skelly-greeter -f
   and the server's:
     journalctl --user -u skelly-server -f
4. Check status any time:
     systemctl --user status skelly-server skelly-greeter
5. The real test: reboot (sudo reboot), wait about two minutes, then run
     pactl list sinks short | grep EC_B4_87
   The Skelly's speaker should come back by itself.

After editing ~/skelly_greeter.py later, apply the change with:
     systemctl --user restart skelly-greeter
MSG
