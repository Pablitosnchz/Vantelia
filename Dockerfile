FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

# Instala Chromium + deps OS para Playwright (IG autosend headless).
# Debian Bookworm: instalamos deps manualmente porque --with-deps falla
# (paquetes ttf-unifont/ttf-ubuntu-font-family ya no existen).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libnspr4 libnss3 libasound2 libatk-bridge2.0-0 libatk1.0-0 \
        libcairo2 libcups2 libdbus-1-3 libdrm2 libgbm1 libpango-1.0-0 \
        libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
        libxkbcommon0 libxrandr2 libxshmfence1 \
        fonts-liberation fonts-unifont \
    && rm -rf /var/lib/apt/lists/* \
    && python -m playwright install chromium

COPY . /app

EXPOSE 8000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
