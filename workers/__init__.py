"""Background workers"""
import os

# Must run before ultralytics is imported: makes YOLO checkpoint loading use
# torch.load(weights_only=True) + an allow-list instead of full pickle, also
# when the worker is started outside Docker (python run_worker.py).
os.environ.setdefault("ULTRALYTICS_SAFE_LOAD", "1")
