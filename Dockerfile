# ResolveAI — Cloud Run image (04_GCP_Deployment_Architecture.md SS3).
#
# Stage 1 installs deps and pre-builds the Chroma index from the bundled
# KB/policy corpus, so cold start only *loads* the index instead of
# re-embedding on every restart. Stage 2 is the slim runtime layer: app code
# + data + prebuilt index, nothing else. GEMINI_API_KEY is needed transiently
# in stage 1 to call the embedding API during the build — it's passed via a
# BuildKit secret mount (never an ARG/ENV) so it never lands in an image
# layer or `docker history`, and stage 2 doesn't inherit it at all.

FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY data/kb ./data/kb
COPY data/policies ./data/policies
COPY data/bookings.json ./data/bookings.json

# BuildKit secret mount: `docker build --secret id=gemini_key,env=GEMINI_API_KEY ...`
# (see cloudbuild.yaml for the Cloud Build equivalent).
RUN --mount=type=secret,id=gemini_key \
    GEMINI_API_KEY="$(cat /run/secrets/gemini_key)" python -m app.rag.build

FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

# Starts the in-process Booking & Case MCP server (built inside Backend()
# before the Gradio app launches) and then the Gradio UI on $PORT — the
# single-container topology in 04_GCP_Deployment_Architecture.md SS1 means
# there's no separate MCP process to start.
CMD ["python", "-m", "app.ui.app"]
