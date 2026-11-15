#!/bin/bash
# Execute final steps after training completes

set -e

echo "🎯 Final Steps - Update Solver and Test"
echo "========================================"

# Wait for training completion
echo ""
echo "⏳ Waiting for training to complete..."
for i in {1..60}; do
  if tail -100 /tmp/training_final.log | grep -q "Results\|Speed.*ms"; then
    echo "✅ Training detected as complete!"
    sleep 5
    break
  fi
  sleep 30
done

# Check if model exists
if [ ! -f /home/deploy/github/anticaptcha/runs/detect/recaptcha_custom/weights/best.pt ]; then
  echo "❌ Trained model not found!"
  echo "   Checking training log for errors..."
  tail -50 /tmp/training_final.log
  exit 1
fi

echo ""
echo "✅ Trained model found:"
ls -lh /home/deploy/github/anticaptcha/runs/detect/recaptcha_custom/weights/best.pt

# Show final metrics
echo ""
echo "📊 Final Training Metrics:"
tail -100 /tmp/training_final.log | grep -E "all.*mAP|Speed" | tail -10

# Update solver
echo ""
echo "🔧 Updating solver to use custom model..."
cd /home/deploy/github/anticaptcha
python update_solver_model.py

# Test on real CAPTCHAs
echo ""
echo "🧪 Testing on real CAPTCHAs..."
docker run --rm \
  -v "$(pwd):/app:ro" \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/runs:/app/runs" \
  anticaptcha:latest \
  python test_multiple_sites.py 2>&1 | tee /tmp/test_results.log

echo ""
echo "✅ All steps complete!"
echo ""
echo "📋 Summary:"
echo "   1. Model trained: runs/detect/recaptcha_custom/weights/best.pt"
echo "   2. Solver updated: workers/solvers/recaptcha.py"
echo "   3. Tests executed: test_multiple_sites.py"
echo ""
echo "📊 Test results saved to: /tmp/test_results.log"