FROM python:3.12-slim

WORKDIR /app

# Playwright tarayıcıları non-root kullanıcının erişebileceği ortak bir yola kurulur.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libxshmfence1 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN patchright install --with-deps && playwright install chromium --with-deps

COPY . .

RUN mkdir -p /app/cookies_output /app/logs \
    && groupadd -r appuser \
    && useradd -r -g appuser -d /app appuser \
    && chown -R appuser:appuser /app /ms-playwright

# Root olarak çalıştırma — container escape saldırı yüzeyini azaltır.
USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--loop", "uvloop", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
