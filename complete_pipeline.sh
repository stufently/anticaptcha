#!/bin/bash
# Final pipeline: wait for training, update solver, test

echo "🚀 Final Pipeline - Complete Implementation"
echo "============================================"

# Wait for training to complete
echo ""
echo "⏳ Waiting for training to complete..."
for i in {1..60}; do
  if [ -f /tmp/training_new.log ]; then
    if grep -q "Training complete\|✅ Training complete" /tmp/training_new.log 2>/dev/null; then
      echo "✅ Training completed!"
      break
    fi
    if grep -q "Error\|Traceback\|Failed" /tmp/training_new.log 2>/dev/null; then
      echo "❌ Training failed!"
      tail -30 /tmp/training_new.log
      exit 1
    fi
    echo "[$i] Training in progress..."
  fi
  sleep 30
done

# Update solver to use custom model
echo ""
echo "🔧 Updating solver to use custom model..."
if [ -f /home/deploy/github/anticaptcha/data/runs/detect/recaptcha_custom/weights/best.pt ]; then
  python /home/deploy/github/anticaptcha/update_solver_model.py
  echo "✅ Solver updated"
else
  echo "⚠️ Trained model not found"
fi

# Test on real CAPTCHAs
echo ""
echo "🧪 Testing on real CAPTCHAs..."
cd /home/deploy/github/anticaptcha
docker run --rm anticaptcha:latest python test_multiple_sites.py

echo ""
echo "✅ Pipeline complete!"