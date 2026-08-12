FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Deploy defaults: use Groq for both transcription and analysis so the container stays light (no
# whisper model download / big RAM) and runs on a cheap always-on host. Override at runtime if needed.
ENV TRANSCRIBER=groq
ENV LLM_PROVIDER=groq

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY profile.example.yaml ./profile.example.yaml

# Run as a non-root user. The app only ever needs to write to its data dir, so there is no reason
# for a process that parses untrusted URLs and third-party feeds to be root inside the container.
# /app/data is created and chowned here because the named volume mounts over it at runtime and
# inherits this ownership — without it the unprivileged user cannot write the database.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# The host maps $PORT; default to 8000 for local `docker run`. Real profile arrives via PROFILE_YAML.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
