FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies + Node.js for qw2
RUN apt-get update && apt-get install -y \
    wget \
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

# Copy application
COPY . .

# Create data directory
RUN mkdir -p /app/data

# Expose port
EXPOSE 8000

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]