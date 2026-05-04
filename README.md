# EdgeVision Control Hub

## Install (uv — recomendado)

[uv](https://docs.astral.sh/uv/) instala Python y dependencias en segundos sin necesidad de crear el venv manualmente.

```bash
# 1. Instalar uv (una sola vez por máquina)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clonar el repo
git clone https://github.com/xavierror656/forge-iinia.git
cd forge-iinia

# 3. Crear entorno e instalar dependencias desde el lock file
uv sync

# 4. Correr la app
uv run python main.py
```

Para instalar también las herramientas de desarrollo (ruff, mypy, pytest):

```bash
uv sync --extra dev
```

Regenerar el lock file cuando cambien las dependencias:

```bash
uv lock
```

---

## Install (venv clásico)

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.lock
```

Para desarrollo:

```bash
./.venv/bin/python -m pip install -e ".[dev]"
./.venv/bin/pre-commit install
```

Lint y tipos:

```bash
./.venv/bin/ruff check core/
./.venv/bin/mypy core/
```

## Run GUI

```bash
uv run python main.py
# o con venv:
./.venv/bin/python main.py
```

## Run headless validation

```bash
QT_QPA_PLATFORM=offscreen uv run python main.py --headless
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
