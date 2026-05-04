# EdgeVision Control Hub

## Install

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

For a fully reproducible install, use the lock file:

```bash
./.venv/bin/python -m pip install -r requirements.lock
```

Regenerate the lock with:

```bash
./.venv/bin/pip-compile --strip-extras --output-file=requirements.lock requirements.txt
```

For development (linting, type-checking, hooks):

```bash
./.venv/bin/python -m pip install -e ".[dev]"
./.venv/bin/pre-commit install
```

Run lint and type checks manually:

```bash
./.venv/bin/ruff check core/
./.venv/bin/mypy core/
```

## Run GUI

```bash
./.venv/bin/python main.py
```

## Run headless validation

```bash
QT_QPA_PLATFORM=offscreen ./.venv/bin/python main.py --headless
```

## Config

Copy `.env.example` to `.env` and edit the values:

```bash
cp .env.example .env
```

Use `.env` for:

```bash
FORGE_URL=
FORGE_USERNAME=
FORGE_PASSWORD=
FORGE_TOKEN=
MODEL_DIR=models
CAPTURE_DIR=captures
SIMULATION_MODE=true
```

The GUI loads `FORGE_USERNAME/FORGE_PASSWORD` automatically and uses them for API requests.
In the Forge tab, select a project to load its labels, then pick a GPIO port and assign the selected labels to that port.

Video input is stored in `configs/inference_source.json`. The app will auto-detect USB/CSI cameras on Linux and can be switched to RTSP from the Settings dialog.
Use the RTSP section in Settings to add, remove, and set the default stream.
