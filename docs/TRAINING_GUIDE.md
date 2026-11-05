# Training Yolo on reCAPTCHA Images

## Overview

This guide covers collecting reCAPTCHA images and training a custom Yolo model.

## Step 1: Collect Images

```bash
# Run dataset collector
python collect_recaptcha_dataset.py
```

This will:
- Load reCAPTCHA demo pages
- Trigger challenges
- Save images with metadata
- Organize by target class

**Output:**
```
data/recaptcha_dataset/
├── images/           # Collected images
│   ├── car_20260105_*.png
│   ├── bus_20260105_*.png
│   └── ...
├── labels/           # YOLO labels (empty initially)
├── metadata.json     # Image metadata
└── yolo/             # YOLO dataset structure
    ├── images/train/
    ├── labels/train/
    └── classes.txt
```

## Step 2: Annotate Images

### Option A: LabelImg (Recommended for small datasets)

```bash
pip install labelImg
labelImg data/recaptcha_dataset/yolo/images/train data/recaptcha_dataset/yolo/classes.txt
```

**Instructions:**
1. Open LabelImg
2. Load images from `yolo/images/train`
3. Draw bounding boxes around target objects
4. Save as YOLO format (txt files)

### Option B: CVAT (For large datasets)

1. Install CVAT: https://github.com/opencv/cvat
2. Create project and upload images
3. Annotate with team
4. Export as YOLO format

### Option C: Roboflow (Cloud-based)

1. Upload to Roboflow: https://roboflow.com
2. Annotate in browser
3. Export as YOLO format

## Step 3: Train Yolo Model

```bash
# Make script executable
chmod +x train_yolo_recaptcha.sh

# Run training
./train_yolo_recaptcha.sh
```

Or manually:

```bash
yolo detect train \
    data=data/recaptcha_dataset/yolo/dataset.yaml \
    model=yolov8n.pt \
    epochs=100 \
    imgsz=640 \
    batch=16 \
    device=cpu \
    project=data/recaptcha_dataset/models \
    name=recaptcha_custom
```

**Training parameters:**
- `epochs`: Number of training cycles (50-200 recommended)
- `imgsz`: Image size (640 default)
- `batch`: Batch size (16 for CPU, 32 for GPU)
- `device`: cpu or cuda

## Step 4: Use Custom Model

Update `workers/solvers/recaptcha.py`:

```python
async def setup(self):
    if HAS_ML:
        try:
            # Use custom trained model
            self.yolo_model = YOLO('data/recaptcha_dataset/models/recaptcha_custom/weights/best.pt')
            print("✅ Custom Yolo model loaded")
        except Exception as e:
            print(f"⚠️ Could not load model: {e}")
```

## Expected Results

### Dataset Size Impact
- **100 images per class**: 60-70% accuracy
- **500 images per class**: 80-85% accuracy
- **1000+ images per class**: 90-95% accuracy

### Training Time
- **CPU**: 1-2 hours for 1000 images
- **GPU (NVIDIA)**: 10-20 minutes for 1000 images

### Classes to Collect

Priority classes (not in COCO):
1. **crosswalk** - пешеходные переходы
2. **stairs** - лестницы
3. **mountain** - горы
4. **palm_tree** - пальмы
5. **chimney** - дымоходы
6. **bridge** - мосты

Classes already in COCO:
- car, bus, truck, bicycle, motorcycle
- traffic_light, fire_hydrant

## Tips

### Improve Accuracy
1. **Diverse images**: Collect from different angles, lighting
2. **Balanced dataset**: Equal number per class
3. **Data augmentation**: Yolo does this automatically
4. **Fine-tuning**: Use smaller learning rate

### Avoid Overfitting
- Use validation split
- Monitor loss curves
- Stop when validation loss increases

### Production Deployment
1. Test on real CAPTCHAs
2. Measure accuracy per class
3. Retrain on misclassified images
4. Iterate

## Legal Note

- Only collect from public demo pages
- Respect Terms of Service
- Use for educational/research purposes
- Do not redistribute dataset

## Troubleshooting

### No challenges appear
- Use stealth mode
- Add random delays
- Rotate IPs if needed

### Poor accuracy
- Collect more images
- Check annotation quality
- Adjust hyperparameters

### Training fails
- Check GPU memory
- Reduce batch size
- Check dataset format