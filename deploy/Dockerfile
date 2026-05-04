FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QT_QPA_PLATFORM=offscreen \
    EDGEVISION_LOG_DIR=/var/log/edgevision

RUN apt-get update && apt-get install -y --no-install-recommends \
        libegl1 libgl1 libglib2.0-0 libdbus-1-3 libxkbcommon0 \
        libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
        libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 \
        libxcb-xkb1 libxkbcommon-x11-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY core/ ./core/
COPY ui/ ./ui/
COPY main.py ./
COPY pyproject.toml ./

RUN useradd --system --create-home --uid 1000 edgevision && \
    mkdir -p /var/log/edgevision /app/captures /app/configs /app/models && \
    chown -R edgevision:edgevision /app /var/log/edgevision

USER edgevision

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python main.py --health || exit 1

ENTRYPOINT ["python", "main.py"]
CMD ["--headless"]
