#!/bin/bash
# Complete pipeline: train model, update solver, test

set -e

echo "🚀 Complete Training Pipeline"
echo "================================"

# Step 1: Train model
echo ""
echo "📊 Step 1: Training custom Yolo model..."
docker run --rm \
  -v "$(pwd):/app:ro" \
  -v "$(pwd)/data:/app/data" \
  anticaptcha:latest \
  python -u train_custom_yolo.py

# Step 2: Update solver
echo ""
echo "🔧 Step 2: Updating solver to use custom model..."
python update_solver_model.py

# Step 3: Test
echo ""
echo "🧪 Step 3: Testing on real CAPTCHAs..."
docker run --rm anticaptcha:latest python test_multiple_sites.py

echo ""
echo "✅ Pipeline complete!"