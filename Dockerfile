# BMAD crew (CrewAI) — container image for the k8s deployment.
# Build context is the repo root; the app lives in bmad-crew/.
FROM python:3.11-slim

# uv for fast, reproducible dependency resolution.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install deps first for better layer caching.
COPY bmad-crew/pyproject.toml ./
RUN uv pip install --system --no-cache -r <(uv pip compile pyproject.toml 2>/dev/null || echo "") \
    || uv pip install --system --no-cache . 2>/dev/null || true

# Copy the application source and install the package itself.
COPY bmad-crew/ ./
RUN uv pip install --system --no-cache .

# CrewAI writes memory/telemetry consent under $HOME; make it writable & non-root.
ENV HOME=/app CREWAI_STORAGE_DIR=/app/.crewai CREWAI_DISABLE_TELEMETRY=true
RUN mkdir -p /app/.crewai /app/output && \
    useradd -m -u 10001 crew && chown -R crew:crew /app
USER crew

EXPOSE 8000

# Serve the kickoff API. Override with the CLI entrypoint for batch runs.
CMD ["uvicorn", "bmad_crew.server:app", "--host", "0.0.0.0", "--port", "8000"]
