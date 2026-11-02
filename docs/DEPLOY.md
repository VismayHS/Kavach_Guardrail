# Deploying KAVACH

Three ways to run it: one container, the full stack with observability (docker compose), or Kubernetes (Helm).

## 1. One container

```bash
docker build -t kavach .
docker run -p 8000:8000 --env-file .env kavach         # console and API on http://localhost:8000
```

Optional extras (the CPU injection classifier and Presidio) go in at build time:

```bash
docker build -t kavach:full --build-arg EXTRAS="torch transformers presidio-analyzer" .
```

The image runs as a non-root user (uid 10001). It has a health check on `/healthz` and writes one JSON log line per decision. Tool arguments are never logged.

## 2. Full stack: docker compose

```bash
docker compose up -d --build
```

| Service | URL | What it shows |
|---|---|---|
| KAVACH | http://localhost:8000 | Console and API |
| Grafana | http://localhost:3000 | The "KAVACH: agent action firewall" dashboard: verdicts, latency p50/p95/p99, rules that fired, approvals, undo windows, kills |
| Prometheus | http://localhost:9090 | `/metrics` scrape and alert rules: canary tripped, deny spike, approval backlog, slow p95, pause active |
| Jaeger | http://localhost:16686 | One span per decision (service `kavach`), carrying verdict, rules and receipt but no arguments |

How the data flows:

- **Traces:** KAVACH sends OTLP to the OpenTelemetry collector (`deploy/otel-collector.yaml`), which forwards to Jaeger.
- **Metrics:** Prometheus scrapes `kavach:8000/metrics`.
- **Dashboard:** Grafana is provisioned from `deploy/grafana/`. Regenerate it with `python deploy/grafana/make_dashboard.py`.

If `.env` exists, compose reads the Qualcomm keys from it.

To get a production-profile run, put these in `.env`:

- `KAVACH_PROFILE=prod`
- `KAVACH_AUTH_SECRET` and `KAVACH_RECEIPT_KEY`, each 32 characters or more
- `KAVACH_SIGNING_KEY`, pointing to the private key made by `python -m kavach.receipts keygen keys/`

Without them, the server refuses to start in the prod profile.

## 3. Kubernetes: Helm

```bash
python -m kavach.receipts keygen keys/
helm install kavach deploy/helm/kavach \
  --set secrets.authSecret=$(openssl rand -hex 32) \
  --set secrets.receiptKey=$(openssl rand -hex 32) \
  --set-file secrets.signingKeyPem=keys/kavach_signing.pem
kubectl port-forward svc/kavach 8000:8000
```

The chart defaults to the **prod profile**:

- It won't render without the three secrets.
- To bring your own Secret instead, set `secrets.existingSecret`. It needs the keys `auth-secret`, `receipt-key` and `signing.pem`.

What the chart sets up:

- **Pod hardening:** non-root, read-only root filesystem, every capability dropped, the RuntimeDefault seccomp profile, and an `emptyDir` at `/tmp`.
- **Probes:** liveness on `/healthz`, readiness on `/readyz` (policy loaded, risk model trained, receipt chain valid), and a startup probe.
- **Options:**
  - `persistence.enabled`: a volume at `/data`.
  - `ingress.enabled`.
  - `serviceMonitor.enabled`: for the Prometheus Operator.
  - `networkPolicy.enabled`: egress limited to DNS and the CIDRs you list.

**One replica.** The receipt chain has one writer, so the deployment uses the `Recreate` strategy and `replicaCount: 1`.

How it was checked:

- `helm lint`.
- `helm template` piped through `kubeconform`: 6 resources valid. The ServiceMonitor was skipped because it is a CRD.
- The image run the way the chart runs it (`--read-only`, uid 10001, all capabilities dropped, the prod profile with real keys). It reported ready.
