# SubTranscribe Studio - Production Docker Environment
FROM python:3.12-slim-bookworm

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install system audio, video, and X11 graphics dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    portaudio19-dev \
    libasound2-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libxcb-cursor0 \
    libxcb-xinerama0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libx11-xcb1 \
    libegl1 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy just requirements.txt first (it lives inside subtranscribe/, colocated
# with the code that needs it) so this layer only rebuilds when deps change,
# not on every source edit.
COPY subtranscribe/requirements.txt subtranscribe/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r subtranscribe/requirements.txt

# Copy application files (assets/ lives inside subtranscribe/ too, so it
# comes along with that copy — no separate assets/ line needed)
COPY main.py .
COPY subtranscribe/ subtranscribe/
COPY VERSION .
COPY bin/ bin/

# Default entry point for SubTranscribe Studio
CMD ["python", "main.py"]
