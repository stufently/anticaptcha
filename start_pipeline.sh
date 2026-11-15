#!/bin/bash
# Quick start script for training pipeline

set -e

echo "🚀 Starting reCAPTCHA Training Pipeline"
echo "========================================"

# Check if Docker is available
if command -v docker &> /dev/null; then
    echo "✅ Docker found, using containerized approach"
    
    # Build image if not exists
    if ! docker images | grep -q "anticaptcha"; then
        echo "📦 Building Docker image..."
        docker build -t anticaptcha:latest .
    fi
    
    echo ""
    echo "📊 Step 1: Collecting dataset"
    docker run --rm --name anticaptcha_collector \
        --user 1002:1002 \
        -v "$(pwd):/app:ro" \
        -v "$(pwd)/data:/app/data" \
        anticaptcha:latest \
        python -u collect_recaptcha_dataset.py
    
    echo ""
    echo "🧠 Step 2: Training model"
    docker run --rm --name anticaptcha_trainer \
        --user 1002:1002 \
        -v "$(pwd):/app:ro" \
        -v "$(pwd)/data:/app/data" \
        anticaptcha:latest \
        python -u train_custom_yolo.py
    
    echo ""
    echo "✅ Pipeline complete!"
    echo "   Model saved to: data/recaptcha_dataset/runs/detect/recaptcha_custom/weights/best.pt"
    
else
    echo "⚠️ Docker not found"
    echo "   Install Docker or run scripts directly:"
    echo "   pip install -r requirements.txt"
    echo "   playwright install chromium"
    echo "   python collect_recaptcha_dataset.py"
    echo "   python train_custom_yolo.py"
fi