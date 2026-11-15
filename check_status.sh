#!/bin/bash
# Check status of all background processes

echo "📊 Anticaptcha Status Check"
echo "============================"
echo ""

# Check dataset collection
echo "1. Dataset Collection:"
if docker ps | grep -q anticaptcha_collector; then
    echo "   Status: ✅ Running"
    count=$(ls /home/deploy/github/anticaptcha/data/recaptcha_dataset/images/ 2>/dev/null | wc -l)
    echo "   Images collected: $count"
    echo "   Latest log:"
    tail -5 /tmp/dataset_collection.log 2>/dev/null | sed 's/^/      /'
else
    echo "   Status: ⏹️ Not running"
    if [ -f /tmp/dataset_collection.log ]; then
        echo "   Last log:"
        tail -5 /tmp/dataset_collection.log 2>/dev/null | sed 's/^/      /'
    fi
fi

echo ""
echo "2. Docker Image:"
if docker images | grep -q anticaptcha; then
    echo "   Status: ✅ Built"
    docker images anticaptcha:latest | tail -1 | sed 's/^/   /'
else
    echo "   Status: ❌ Not built"
fi

echo ""
echo "3. Dataset:"
if [ -d /home/deploy/github/anticaptcha/data/recaptcha_dataset/images ]; then
    count=$(ls /home/deploy/github/anticaptcha/data/recaptcha_dataset/images/ 2>/dev/null | wc -l)
    echo "   Images: $count"
    if [ -f /home/deploy/github/anticaptcha/data/recaptcha_dataset/metadata.json ]; then
        classes=$(cat /home/deploy/github/anticaptcha/data/recaptcha_dataset/metadata.json | jq -r 'group_by(.target) | .[] | "\(.[]["target"])"' | sort | uniq -c | awk '{print "   - " $2 ": " $1}')
        echo "   Classes:"
        echo "$classes"
    fi
else
    echo "   Status: ❌ Not created"
fi

echo ""
echo "4. Trained Model:"
if [ -f /home/deploy/github/anticaptcha/runs/detect/recaptcha_custom/weights/best.pt ]; then
    echo "   Status: ✅ Trained"
    ls -lh /home/deploy/github/anticaptcha/runs/detect/recaptcha_custom/weights/best.pt | sed 's/^/   /'
else
    echo "   Status: ❌ Not trained yet"
fi

echo ""
echo "============================"
echo "📋 Next Steps:"
if [ ! -f /home/deploy/github/anticaptcha/runs/detect/recaptcha_custom/weights/best.pt ]; then
    if [ $(ls /home/deploy/github/anticaptcha/data/recaptcha_dataset/images/ 2>/dev/null | wc -l) -lt 50 ]; then
        echo "   1. Wait for dataset collection to complete"
    else
        echo "   1. Train model: docker run --rm -v \"$(pwd)/data:/app/data\" anticaptcha:latest python train_custom_yolo.py"
    fi
    echo "   2. Update solver: python update_solver_model.py"
    echo "   3. Test: docker run --rm anticaptcha:latest python test_multiple_sites.py"
else
    echo "   ✅ Model trained! Test it:"
    echo "   docker run --rm anticaptcha:latest python test_multiple_sites.py"
fi