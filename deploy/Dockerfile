FROM python:3.12-slim

LABEL org.opencontainers.image.title="TouchLink Relay"
LABEL org.opencontainers.image.description="TouchLink relay server — WebSocket pairing"
LABEL org.opencontainers.image.licenses="MIT"

# Không cần build tools vì aiohttp đã có wheel sẵn cho slim
RUN pip install --no-cache-dir "aiohttp>=3.9"

WORKDIR /app
COPY relay_server.py .

# Biến môi trường mặc định — override khi chạy container
ENV PORT=8430 \
    RELAY_TRUSTED_PROXY=1 \
    RELAY_ANONYMIZE_LOGS=0 \
    RELAY_MAX_CONNS_IP=20 \
    RELAY_MAX_CONN_ID=10 \
    RELAY_MAX_CONN_TOTAL=30 \
    RELAY_MAX_AUTH_FAIL=5 \
    RELAY_AUTH_BAN_S=180 \
    RELAY_MAX_CONNS_TOTAL=10

EXPOSE 8430

# Healthcheck cho container orchestrator
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/healthz', timeout=4)"

# Chạy trực tiếp không buffering để log ngay lập tức
CMD ["python", "-u", "relay_server.py", "--trusted-proxy"]
