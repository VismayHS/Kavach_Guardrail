# KAVACH: the gateway, the API and the console in one image.
#   docker build -t kavach .                                   # core (+ MCP proxy, signed receipts, telemetry, Cedar)
#   docker build -t kavach:full --build-arg EXTRAS="torch transformers presidio-analyzer" .
#   docker run -p 8000:8000 kavach                             # http://localhost:8000
FROM python:3.13-slim

ARG EXTRAS=""
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 KAVACH_LOG_JSON=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt "mcp>=2.3" "cryptography>=43" "cedarpy>=4.0" \
        "opentelemetry-sdk>=1.30" "opentelemetry-exporter-otlp-proto-http>=1.30" ${EXTRAS}

COPY kavach ./kavach
COPY agent ./agent
COPY integrations ./integrations
COPY bench/results ./bench/results

RUN useradd --create-home --uid 10001 kavach && chown -R kavach /app
USER kavach

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"
CMD ["python", "-m", "uvicorn", "kavach.server:app", "--host", "0.0.0.0", "--port", "8000"]
