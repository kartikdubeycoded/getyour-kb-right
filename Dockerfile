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

EXPOSE 8000

# The host maps $PORT; default to 8000 for local `docker run`. Real profile arrives via PROFILE_YAML.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
