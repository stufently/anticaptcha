#!/bin/bash
# Auto-run after training: update solver, test, report

set -e

echo "🎯 Final Steps After Training"
echo "================================"

# Wait for training to complete
echo ""
echo "⏳ Waiting for training completion..."
for i in {1..60}; do
  if grep -q "Results\|Training complete\|✅" /tmp/training_final.log 2>/dev/null; then
    echo "✅ Training detected as complete!"
    break
  fi
  sleep 30
done

# Give it a few more seconds to finish writing
sleep 5

# Show final results
echo ""
echo "📊 Final Training Results:"
tail -50 /tmp/training_final.log | grep -E "Epoch|mAP|Results|Speed" || tail -20 /tmp/training_final.log

# Check if model exists
if [ ! -f /home/deploy/github/anticaptcha/runs/detect/recaptcha_custom/weights/best.pt ]; then
  echo ""
  echo "❌ Trained model not found!"
  echo "   Expected: runs/detect/recaptcha_custom/weights/best.pt"
  exit 1
fi

echo ""
echo "✅ Trained model found:"
ls -lh /home/deploy/github/anticaptcha/runs/detect/recaptcha_custom/weights/best.pt

# Update solver
echo ""
echo "🔧 Updating solver to use trained model..."
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
  python test_multiple_sites.py

echo ""
echo "✅ Pipeline complete!"
echo ""
echo "📊 Summary:"
echo "   - Model trained: runs/detect/recaptcha_custom/weights/best.pt"
echo "   - Solver updated: workers/solvers/recaptcha.py"
echo "   - Tests executed: test_multiple_sites.py"
echo ""
echo "🎯 Next: Check test results above to see success rate improvement"