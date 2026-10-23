FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860

# libglib is the only system library opencv-python-headless needs
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Run as an unprivileged user (uid 1000 also matches Hugging Face Spaces)
RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=appuser:appuser face_emotion_detection ./face_emotion_detection
RUN mkdir -p /app/face_emotion_detection/webapp/instance \
    && chown appuser:appuser /app/face_emotion_detection/webapp/instance \
    && chmod 700 /app/face_emotion_detection/webapp/instance

USER appuser
WORKDIR /app/face_emotion_detection/webapp
EXPOSE 7860

# Production server. One worker is required for Socket.IO; threads handle concurrency.
CMD gunicorn --workers 1 --threads 50 --bind 0.0.0.0:${PORT} --timeout 60 app:app
