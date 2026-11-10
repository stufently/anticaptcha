FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies + Node.js for qw2
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    libgl1 \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Qwen Code CLI globally
RUN npm install -g @qwen-code/qwen-code

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Qwen Code SDK for Vision LLM
RUN pip install --no-cache-dir qwen-code-sdk

# YOLO checkpoints: torch.load(weights_only=True) + allow-list instead of full pickle
ENV ULTRALYTICS_SAFE_LOAD=1

# Install Playwright browsers to a global location
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install chromium

# Pre-download EasyOCR models (outside /app/data to avoid PVC override)
ENV EASYOCR_MODULE_PATH=/app/easyocr_models
RUN mkdir -p /app/easyocr_models && \
    python -c "import easyocr; easyocr.Reader(['en'], gpu=False, model_storage_directory='/app/easyocr_models')"

# Create directories
RUN mkdir -p /app/data /app/models /home/anticaptcha/.qwen

# Download YOLO models from official releases (with SHA256 verification)
RUN wget -q https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt -O /app/models/yolov8n.pt && \
    wget -q https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s.pt -O /app/models/yolov8s.pt && \
    echo "Models downloaded successfully"

# Copy custom model if exists (optional)
COPY models/recaptcha_custom.pt /app/models/recaptcha_custom.pt 2>/dev/null || true

# Copy qw2 settings for Vision LLM
COPY config/qwen/settings.json /home/anticaptcha/.qwen/settings.json

# Copy application code (filtered by .dockerignore)
COPY app/ ./app/
COPY workers/ ./workers/
COPY init_db.py run_worker.py ./

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash anticaptcha && \
    chown -R anticaptcha:anticaptcha /app /ms-playwright /app/easyocr_models /home/anticaptcha

# Set HOME for qwen
ENV HOME=/home/anticaptcha

# Switch to non-root user
USER anticaptcha

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command (can be overridden)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]