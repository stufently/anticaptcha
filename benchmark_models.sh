#!/bin/bash
# Real-world benchmark of Vision LLM models on CAPTCHA

set -e

echo "========================================="
echo "Vision LLM Model Benchmark"
echo "========================================="

# Check if qw2 is available
if ! command -v qwen &> /dev/null; then
    echo "❌ qwen CLI not found"
    echo "Install with: npm install -g @qwen-code/qwen-code"
    exit 1
fi

echo "✅ qwen CLI found: $(which qwen)"
echo ""

# Check if qw2 config exists
if [ ! -d ~/.qwen ]; then
    echo "❌ ~/.qwen directory not found"
    echo "Please configure qw2 first"
    exit 1
fi

echo "✅ qw2 config found: ~/.qwen"
echo ""

# Test prompt
PROMPT="Analyze this reCAPTCHA image. Select all tiles with cars. Return JSON array of tile indices [0-8]."

# Check for test images
if [ -d "data/synthetic" ]; then
    echo "✅ Found synthetic images"
    TEST_IMAGE=$(ls data/synthetic/*.png 2>/dev/null | head -1)
else
    echo "⚠️ No test images found"
    echo "Creating synthetic test image..."

    # Create a simple test image with Python
    python3 << 'PY'
from PIL import Image, ImageDraw
import os

os.makedirs("data/synthetic", exist_ok=True)

# Create a 3x3 grid image
img = Image.new('RGB', (300, 300), color='white')
draw = ImageDraw.Draw(img)

# Draw grid
for i in range(1, 3):
    draw.line([(i*100, 0), (i*100, 300)], fill='black', width=2)
    draw.line([(0, i*100), (300, i*100)], fill='black', width=2)

# Add text
draw.text((10, 10), "Test CAPTCHA", fill='black')

img.save('data/synthetic/test_captcha.png')
print(f"Created: data/synthetic/test_captcha.png")
PY

    TEST_IMAGE="data/synthetic/test_captcha.png"
fi

echo "✅ Test image: $TEST_IMAGE"
echo ""

# Run benchmark
echo "========================================="
echo "Running benchmark..."
echo "========================================="

# Number of iterations
ITERATIONS=3

# Results file
RESULTS_FILE="benchmark_results_$(date +%Y%m%d_%H%M%S).json"

# Initialize results
echo "{" > $RESULTS_FILE
echo "  \"timestamp\": \"$(date -Iseconds)\"," >> $RESULTS_FILE
echo "  \"iterations\": $ITERATIONS," >> $RESULTS_FILE
echo "  \"results\": {" >> $RESULTS_FILE

# Test qw2 with default model (Kimi)
echo ""
echo "📊 Testing default model (3 iterations)..."

for i in $(seq 1 $ITERATIONS); do
    echo "  Iteration $i/$ITERATIONS..."

    START=$(date +%s.%N)

    # Run qw2
    OUTPUT=$(qwen "$PROMPT $TEST_IMAGE" --approval-mode auto --max-wall-time 30s 2>&1)

    END=$(date +%s.%N)

    # Calculate time
    TIME=$(echo "$END - $START" | bc)

    echo "    Time: ${TIME}s"
    echo "    Output: $(echo "$OUTPUT" | head -1)"

    # Save result
    if [ $i -eq 1 ]; then
        echo "    \"iteration_$i\": {" >> $RESULTS_FILE
    else
        echo "    \"iteration_$i\": {" >> $RESULTS_FILE
    fi

    echo "      \"time\": $TIME," >> $RESULTS_FILE
    echo "      \"output\": $(echo "$OUTPUT" | head -1 | jq -Rs .)" >> $RESULTS_FILE

    if [ $i -lt $ITERATIONS ]; then
        echo "    }," >> $RESULTS_FILE
    else
        echo "    }" >> $RESULTS_FILE
    fi
done

echo "  }" >> $RESULTS_FILE
echo "}" >> $RESULTS_FILE

echo ""
echo "========================================="
echo "Benchmark Complete!"
echo "========================================="
echo ""
echo "Results saved to: $RESULTS_FILE"
echo ""

# Calculate statistics
echo "Statistics:"
cat $RESULTS_FILE | python3 << 'PY'
import json
import sys

data = json.load(sys.stdin)

times = []
for key, value in data['results'].items():
    if key.startswith('iteration_'):
        times.append(float(value['time']))

if times:
    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)

    print(f"  Average time: {avg_time:.2f}s")
    print(f"  Min time: {min_time:.2f}s")
    print(f"  Max time: {max_time:.2f}s")
PY

echo ""
echo "✅ Benchmark completed successfully"