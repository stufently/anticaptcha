#!/bin/bash
# Train Yolo model on reCAPTCHA dataset

# Dataset path
DATASET_DIR="/app/data/recaptcha_dataset"
YOLO_DIR="$DATASET_DIR/yolo"

# Check if dataset exists
if [ ! -d "$YOLO_DIR" ]; then
    echo "❌ Dataset not found. Run collect_recaptcha_dataset.py first."
    exit 1
fi

# Check if annotations exist
LABELS_DIR="$YOLO_DIR/labels/train"
if [ -z "$(ls -A $LABELS_DIR 2>/dev/null)" ]; then
    echo "⚠️ No label files found. You need to annotate images first."
    echo ""
    echo "Options for annotation:"
    echo "  1. LabelImg: pip install labelImg && labelImg"
    echo "  2. CVAT: https://github.com/opencv/cvat"
    echo "  3. Roboflow: https://roboflow.com"
    exit 1
fi

# Create dataset.yaml for YOLO
cat > "$YOLO_DIR/dataset.yaml" << EOF
path: $YOLO_DIR
train: images/train
val: images/train  # Use same for validation (split if more data)

nc: $(wc -l < "$YOLO_DIR/classes.txt")
names: $(cat "$YOLO_DIR/classes.txt" | tr '\n' ',' | sed 's/,$//')
EOF

echo "📁 Dataset: $YOLO_DIR"
echo "📊 Classes: $(wc -l < "$YOLO_DIR/classes.txt")"
echo ""

# Train Yolo
echo "🚀 Training Yolo model..."
yolo detect train \
    data="$YOLO_DIR/dataset.yaml" \
    model=yolov8n.pt \
    epochs=100 \
    imgsz=640 \
    batch=16 \
    device=cpu \
    project="$DATASET_DIR/models" \
    name="recaptcha_custom"

echo ""
echo "✅ Training complete!"
echo "   Model: $DATASET_DIR/models/recaptcha_custom/weights/best.pt"
echo ""
echo "💡 To use in solver:"
echo "   self.yolo_model = YOLO('data/recaptcha_dataset/models/recaptcha_custom/weights/best.pt')"