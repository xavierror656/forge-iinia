# EdgeVision Control Hub

## Install en Jetson (JetPack 6.1)

```bash
# 1. Dependencias del sistema
sudo apt update && sudo apt install python3-pip -y

# 2. Clonar e instalar (uv descarga Python 3.10 compatible y los wheels CUDA automáticamente)
git clone https://github.com/xavierror656/forge-iinia.git
cd forge-iinia
uv sync

# 3. cuDSS (dependencia de torch 2.10 en Jetson)
wget https://developer.download.nvidia.com/compute/cudss/0.7.1/local_installers/cudss-local-tegra-repo-ubuntu2204-0.7.1_0.7.1-1_arm64.deb
sudo dpkg -i cudss-local-tegra-repo-ubuntu2204-0.7.1_0.7.1-1_arm64.deb
sudo cp /var/cudss-local-tegra-repo-ubuntu2204-0.7.1/cudss-*-keyring.gpg /usr/share/keyrings/
sudo apt-get update && sudo apt-get -y install cudss

# 4. onnxruntime-gpu (solo necesario para exportar modelos a ONNX/TensorRT)
uv pip install https://github.com/ultralytics/assets/releases/download/v0.0.0/onnxruntime_gpu-1.23.0-cp310-cp310-linux_aarch64.whl

# 5. Reboot y correr
sudo reboot
# tras reboot:
uv run python main.py
```

> `uv sync` instala automáticamente `torch 2.10.0` y `torchvision 0.25.0`
> con los wheels CUDA precompilados para JetPack 6.1 (aarch64/cp310).

---

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
