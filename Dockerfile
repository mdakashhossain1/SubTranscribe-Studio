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
    python3-tk \
    tk-dev \
    tcl-dev \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY subgen.py .
COPY assets/ assets/
COPY bin/ bin/

# Default entry point for SubTranscribe Studio
CMD ["python", "subgen.py"]
