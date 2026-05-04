# Deploy artifacts

## systemd

```bash
sudo cp deploy/edgevision.service /etc/systemd/system/
sudo useradd --system --create-home --shell /bin/false edgevision
sudo install -d -o edgevision -g edgevision /opt/edgevision
sudo rsync -a --exclude=.venv --exclude=.git . /opt/edgevision/
sudo -u edgevision python3 -m venv /opt/edgevision/.venv
sudo -u edgevision /opt/edgevision/.venv/bin/pip install -r /opt/edgevision/requirements.txt

sudo systemctl daemon-reload
sudo systemctl enable --now edgevision
sudo journalctl -u edgevision -f
```

`ExecStartPre` runs `--health` so the unit fails fast on bad config.
`WatchdogSec=30` requires the app to ping systemd; if the integration is
not in place, drop the line.

## Docker

```bash
docker build -t edgevision -f deploy/Dockerfile .
docker run --rm -it \
    -v $(pwd)/.env:/app/.env:ro \
    -v $(pwd)/configs:/app/configs \
    -v $(pwd)/captures:/app/captures \
    -v $(pwd)/models:/app/models:ro \
    edgevision --headless
```

The image runs `--health` as `HEALTHCHECK`. For real GPIO on host hardware
you'll need `--device /dev/gpiochip0` (Jetson/RPi).
