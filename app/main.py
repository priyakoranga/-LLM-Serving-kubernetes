import os
import time
import logging
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
from starlette.requests import Request

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("llm-serving")

APP_NAME = "llm-serving-api"
MODEL_BACKEND = os.getenv("MODEL_BACKEND", "mock").lower()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

REQUESTS = Counter(
    "llm_requests_total",
    "Number of inference requests",
    ["endpoint", "status"],
)
LATENCY = Histogram(
    "llm_request_duration_seconds",
    "End-to-end inference request duration in seconds",
    ["endpoint"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30),
)
PROMPT_CHARS = Histogram(
    "llm_prompt_characters",
    "Prompt size in characters",
    buckets=(50, 100, 250, 500, 1000, 2000, 4000, 8000),
)
OUTPUT_CHARS = Histogram(
    "llm_output_characters",
    "Generated output size in characters",
    buckets=(50, 100, 250, 500, 1000, 2000, 4000, 8000),
)

app = FastAPI(
    title="LLM Serving API",
    description="A small LLM API with Prometheus metrics for Kubernetes observability.",
    version="1.0.0",
)

class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    max_tokens: int = Field(default=256, ge=1, le=2048)

class GenerateResponse(BaseModel):
    model: str
    output: str
    latency_seconds: float
    backend: str

@app.middleware("http")
async def request_metrics(request: Request, call_next):
    # The inference endpoint records its own duration and status. This middleware
    # intentionally avoids prompt text or other sensitive data in logs/labels.
    start = time.perf_counter()
    try:
        response = await call_next(request)
        return response
    finally:
        elapsed = time.perf_counter() - start
        if request.url.path not in ("/metrics", "/healthz", "/readyz"):
            logger.info(
                "request_complete method=%s path=%s duration_seconds=%.4f",
                request.method, request.url.path, elapsed
            )

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/readyz")
async def readyz():
    if MODEL_BACKEND == "groq" and not GROQ_API_KEY:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY is not configured")
    return {"status": "ready", "backend": MODEL_BACKEND}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

async def generate_with_groq(prompt: str, max_tokens: int) -> str:
    if not GROQ_API_KEY:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY is not configured")
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    async with httpx.AsyncClient(timeout=45.0) as client:
        try:
            response = await client.post(
                f"{GROQ_BASE_URL.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning("model_provider_http_error status=%s", exc.response.status_code)
            raise HTTPException(status_code=502, detail="Model provider returned an error")
        except httpx.RequestError:
            logger.exception("model_provider_connection_error")
            raise HTTPException(status_code=502, detail="Could not reach model provider")
    data = response.json()
    return data["choices"][0]["message"]["content"]

@app.post("/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest):
    started = time.perf_counter()
    status = "success"
    PROMPT_CHARS.observe(len(request.prompt))
    try:
        if MODEL_BACKEND == "groq":
            output = await generate_with_groq(request.prompt, request.max_tokens)
            model_name = GROQ_MODEL
        else:
            # Safe default for Codespaces: test the API and dashboards without
            # downloading or hosting a large model. Replace with a real backend later.
            output = (
                "Mock LLM response. Your prompt was received successfully. "
                "Connect a real model provider by setting MODEL_BACKEND=groq."
            )
            model_name = "mock-llm"
        OUTPUT_CHARS.observe(len(output))
        elapsed = time.perf_counter() - started
        REQUESTS.labels(endpoint="/generate", status="success").inc()
        LATENCY.labels(endpoint="/generate").observe(elapsed)
        logger.info("inference_complete backend=%s latency_seconds=%.4f", MODEL_BACKEND, elapsed)
        return GenerateResponse(
            model=model_name,
            output=output,
            latency_seconds=round(elapsed, 4),
            backend=MODEL_BACKEND,
        )
    except HTTPException:
        status = "error"
        REQUESTS.labels(endpoint="/generate", status=status).inc()
        LATENCY.labels(endpoint="/generate").observe(time.perf_counter() - started)
        raise
    except Exception:
        status = "error"
        REQUESTS.labels(endpoint="/generate", status=status).inc()
        LATENCY.labels(endpoint="/generate").observe(time.perf_counter() - started)
        logger.exception("inference_unhandled_error")
        raise HTTPException(status_code=500, detail="Internal inference error")
