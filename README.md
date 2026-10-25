# Production-Style LLM Serving & Observability on Kubernetes

A Codespaces-friendly starter project for learning how to deploy an LLM API and observe it with Prometheus and Grafana. It uses a lightweight mock backend by default so you can test the platform without downloading a large model or using a GPU. It can optionally call the Groq OpenAI-compatible API.

> This is a production-style learning project, not a claim of production readiness. Real production use needs authentication, rate limiting, TLS, secret management, model-provider controls, durable telemetry, load testing, and an operational review.

## Architecture

Client → Kubernetes Service → FastAPI serving API → mock backend or Groq API.

Prometheus scrapes `/metrics`; Grafana dashboards show request rate, request status, latency, prompt size, and output size. The API emits structured, low-sensitivity logs to stdout for the platform log collector.

## Stack

- FastAPI + Uvicorn: HTTP inference API
- Docker: repeatable image
- Kubernetes: Deployment, Service, probes, resource requests/limits, non-root container
- Prometheus: metrics scraping
- Grafana: provisioned dashboard
- Optional Groq API: external model inference

## Project layout

```text
.
├── app/main.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── k8s/
│   ├── namespace.yaml
│   ├── app.yaml
│   ├── groq-secret.example.yaml
│   └── servicemonitor.example.yaml
└── observability/
    ├── prometheus.yml
    └── grafana/
        ├── provisioning/
        └── dashboards/
```

## Run in GitHub Codespaces (quickest path)

Codespaces does not automatically provide a Kubernetes cluster. First run the API and observability stack with Docker Compose; then deploy the API manifests to a Kubernetes cluster you can access.

1. Open this repository in Codespaces.
2. Start the stack:

   ```bash
   docker compose up --build
   ```

3. Open the forwarded ports:
   - API docs: `http://localhost:8000/docs`
   - Prometheus: `http://localhost:9090`
   - Grafana: `http://localhost:3000` (user `admin`, password `change-me-locally`)

   In Codespaces, use the Ports tab to open each forwarded port.

4. Test the mock inference endpoint:

   ```bash
   curl -X POST http://localhost:8000/generate \
     -H 'Content-Type: application/json' \
     -d '{"prompt":"Explain Kubernetes readiness probes in simple terms","max_tokens":120}'
   ```

5. Check metrics at `http://localhost:8000/metrics`. Make a few requests, then view the provisioned **LLM Serving Overview** dashboard in Grafana.

Stop the stack with `Ctrl+C`, then `docker compose down`.

## Use a real model API (optional)

The default `MODEL_BACKEND=mock` avoids API cost and secrets. To use Groq, set the environment variables in the Codespaces secret/settings or in your local shell; do not commit credentials.

```bash
export MODEL_BACKEND=groq
export GROQ_API_KEY="your-real-key"
export GROQ_MODEL="openai/gpt-oss-120b"
docker compose up --build
```

If Compose is already running, recreate the service after changing environment variables:

```bash
docker compose up --build --force-recreate
```

Never put real API keys in `docker-compose.yml`, a Kubernetes manifest, screenshots, or Git commits. If a key was pushed, revoke it and remove it from the affected commit history.

## Kubernetes deployment

You need a reachable Kubernetes cluster and a configured `kubectl` context. Codespaces itself is a development environment, not a Kubernetes cluster by default.

1. Build the image:

   ```bash
   docker build -t llm-serving-observability:latest .
   ```

2. For a remote cluster, push the image to a registry you control and update `image:` in `k8s/app.yaml`. The image reference in that file is a placeholder. For a local cluster, load the image using that cluster's documented workflow.

3. Deploy the app:

   ```bash
   kubectl apply -f k8s/namespace.yaml
   kubectl apply -f k8s/app.yaml
   kubectl -n llm-serving rollout status deployment/llm-serving-api
   kubectl -n llm-serving port-forward service/llm-serving-api 8000:8000
   ```

4. In another terminal, test it using the same `curl` command shown above.

### Prometheus/Grafana on Kubernetes

For a practical Kubernetes monitoring setup, install `kube-prometheus-stack` with Helm in a cluster where you have permission to install cluster-level monitoring. It includes Prometheus, Grafana, Alertmanager, and Kubernetes dashboards. If its Prometheus instance uses the Prometheus Operator, review `k8s/servicemonitor.example.yaml`, set the `release` label to match your Helm release, and apply it:

```bash
kubectl apply -f k8s/servicemonitor.example.yaml
```

The ServiceMonitor custom resource only works when the Prometheus Operator CRDs are installed and its selector matches the resource labels.

## Metrics

- `llm_requests_total`: inference request count by endpoint and status
- `llm_request_duration_seconds`: end-to-end request latency histogram
- `llm_prompt_characters`: prompt size histogram
- `llm_output_characters`: output size histogram

Do not add raw prompts, user IDs, API keys, or other high-cardinality/sensitive data to Prometheus labels.

## Troubleshooting

- **Docker command unavailable:** confirm Docker is enabled for your Codespace; otherwise use a remote container build or a supported environment.
- **Dashboard has no data:** make a few requests, check Prometheus → Status → Targets, and verify the `llm-serving-api` target is UP.
- **Kubernetes `ImagePullBackOff`:** the placeholder image must be replaced with a real pushed image reference.
- **ServiceMonitor rejected:** install the Prometheus Operator CRDs or use Prometheus scrape configuration instead.
- **Groq request fails:** check the API key, model availability, network access, and provider error logs. Never print the key in logs.

## Next production-hardening milestones

1. Add authentication, rate limiting, request size limits, and TLS at the ingress/API gateway.
2. Use a proper secret manager and least-privilege RBAC.
3. Add distributed tracing with OpenTelemetry and a trace backend.
4. Add alert rules for high error rate, p95 latency, and pod restarts.
5. Add load tests, autoscaling, rolling deployment strategy, and a rollback runbook.
6. For self-hosted model inference, evaluate a dedicated serving engine (for example, vLLM) and GPU scheduling; this starter does not host model weights itself.
