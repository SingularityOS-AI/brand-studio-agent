FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    ffmpeg \
    chromium \
    fonts-noto-color-emoji \
    fontconfig \
    ca-certificates \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Set before npm install so HyperFrames/puppeteer never downloads its own Chrome.
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    CHROME_PATH=/usr/bin/chromium \
    PUPPETEER_SKIP_DOWNLOAD=true \
    PORT=8080 \
    PYTHONUNBUFFERED=1

RUN npm install -g hyperframes@0.8.75

RUN python3 -m venv /opt/venv
COPY requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

COPY fonts/ /usr/local/share/fonts/brandstudio/
RUN fc-cache -f

COPY . /srv/render_service
WORKDIR /srv

RUN useradd -m render
USER render

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/opt/venv/bin/uvicorn", "render_service.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
