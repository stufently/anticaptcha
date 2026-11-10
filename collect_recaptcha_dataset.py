#!/usr/bin/env python3
"""
Collect reCAPTCHA images for training dataset

This script collects images from reCAPTCHA challenges for training purposes.
Only collects from public demo pages.
"""
import asyncio
import sys
import os
import json
import random
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '/app')

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# Dataset directory
DATASET_DIR = Path('/app/data/recaptcha_dataset')
IMAGES_DIR = DATASET_DIR / 'images'
LABELS_DIR = DATASET_DIR / 'labels'
METADATA_FILE = DATASET_DIR / 'metadata.json'


class RecaptchaDatasetCollector:
    """Collect reCAPTCHA images for training"""
    
    def __init__(self):
        self.stealth = Stealth()
        self.collected_count = 0
        self.metadata = []
    
    async def setup(self):
        """Create dataset directories"""
        DATASET_DIR.mkdir(parents=True, exist_ok=True)
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        LABELS_DIR.mkdir(parents=True, exist_ok=True)
        
        # Load existing metadata
        if METADATA_FILE.exists():
            with open(METADATA_FILE, 'r') as f:
                self.metadata = json.load(f)
                self.collected_count = len(self.metadata)
        
        print(f"📁 Dataset directory: {DATASET_DIR}")
        print(f"📊 Already collected: {self.collected_count} images\n")
    
    async def collect_from_recaptcha_demo(self, num_samples: int = 50):
        """Collect images from Google reCAPTCHA demo"""
        print(f"🎯 Collecting {num_samples} samples from reCAPTCHA demo...\n")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            
            page = await browser.new_page()
            await self.stealth.apply_stealth_async(page)
            
            collected = 0
            
            while collected < num_samples:
                try:
                    # Navigate to demo
                    print(f"[{collected+1}/{num_samples}] Loading reCAPTCHA demo...")
                    await page.goto(
                        'https://www.google.com/recaptcha/api2/demo',
                        timeout=60000,
                        wait_until='domcontentloaded'
                    )
                    
                    await asyncio.sleep(random.uniform(2.0, 4.0))
                    
                    # Find reCAPTCHA
                    await page.wait_for_selector('iframe[src*="recaptcha"]', timeout=15000)
                    
                    # Click checkbox
                    checkbox_frame = page.frame_locator('iframe[title*="reCAPTCHA"]')
                    await checkbox_frame.locator('#recaptcha-anchor').click()
                    
                    await asyncio.sleep(random.uniform(3.0, 5.0))
                    
                    # Check for challenge
                    # Wait for challenge iframe to appear
                    await page.wait_for_selector('iframe[src*="bframe"]', timeout=5000)
                    challenge_frame = page.frame_locator('iframe[src*="bframe"]')

                    try:
                        # Wait for image select challenge content
                        await challenge_frame.locator('.rc-imageselect').wait_for(timeout=5000)
                        
                        # Get instruction
                        instruction = await challenge_frame.locator('.rc-imageselect-instructions').text_content()
                        
                        # Extract target
                        target = self._extract_target(instruction)
                        
                        if not target:
                            print(f"   ⚠️ Unknown target: {instruction[:50]}")
                            continue
                        
                        print(f"   🎯 Target: {target}")
                        
                        # Get all images
                        tiles = await challenge_frame.locator('.rc-image-tile-wrapper').all()
                        
                        # Save each image
                        for i, tile in enumerate(tiles):
                            img = tile.locator('img')
                            screenshot = await img.screenshot()
                            
                            # Generate unique filename
                            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                            filename = f"{target}_{timestamp}_{i}.png"
                            
                            # Save image
                            image_path = IMAGES_DIR / filename
                            with open(image_path, 'wb') as f:
                                f.write(screenshot)
                            
                            # Save metadata
                            image_metadata = {
                                'filename': filename,
                                'target': target,
                                'instruction': instruction,
                                'collected_at': datetime.now().isoformat(),
                                'source': 'google_recaptcha_demo',
                                'image_index': i
                            }
                            
                            self.metadata.append(image_metadata)
                            
                            # Save metadata incrementally
                            with open(METADATA_FILE, 'w') as f:
                                json.dump(self.metadata, f, indent=2)
                        
                        collected += 1
                        print(f"   ✅ Collected {len(tiles)} images for '{target}'")
                        
                        # Random delay before next collection
                        await asyncio.sleep(random.uniform(2.0, 5.0))
                    
                    except Exception as e:
                        print(f"   ⚠️ No challenge: {e}")
                        await asyncio.sleep(3)
                
                except Exception as e:
                    print(f"   ❌ Error: {e}")
                    await asyncio.sleep(5)
            
            await browser.close()
        
        print(f"\n✅ Collected {collected} samples ({len(self.metadata)} total images)")
    
    def _extract_target(self, instruction: str) -> str:
        """Extract target class from instruction"""
        instruction_lower = instruction.lower()
        
        # Map instructions to YOLO class names
        target_mapping = {
            'car': 'car',
            'bus': 'bus',
            'truck': 'truck',
            'bicycle': 'bicycle',
            'motorcycle': 'motorcycle',
            'traffic light': 'traffic_light',
            'fire hydrant': 'fire_hydrant',
            'crosswalk': 'crosswalk',
            'stairs': 'stairs',
            'bridge': 'bridge',
            'mountain': 'mountain',
            'palm tree': 'palm_tree',
            'chimney': 'chimney',
            'pedestrian': 'pedestrian',
            'parking meter': 'parking_meter',
            'bench': 'bench',
        }
        
        for keyword, class_name in target_mapping.items():
            if keyword in instruction_lower:
                return class_name
        
        return None
    
    async def create_yolo_dataset(self):
        """Convert collected images to YOLO format"""
        print("\n🔄 Converting to YOLO format...\n")
        
        # Create YOLO directory structure
        yolo_dir = DATASET_DIR / 'yolo'
        train_images = yolo_dir / 'images' / 'train'
        train_labels = yolo_dir / 'labels' / 'train'
        
        train_images.mkdir(parents=True, exist_ok=True)
        train_labels.mkdir(parents=True, exist_ok=True)
        
        # Get unique classes
        classes = sorted(set(item['target'] for item in self.metadata))
        class_to_id = {cls: i for i, cls in enumerate(classes)}
        
        print(f"📊 Classes: {len(classes)}")
        for i, cls in enumerate(classes):
            count = sum(1 for item in self.metadata if item['target'] == cls)
            print(f"   {i}: {cls} ({count} images)")
        
        # Save classes file
        classes_file = yolo_dir / 'classes.txt'
        with open(classes_file, 'w') as f:
            f.write('\n'.join(classes))
        
        print(f"\n✅ YOLO dataset created at {yolo_dir}")
        print(f"   Images: {train_images}")
        print(f"   Labels: {train_labels}")
        print(f"   Classes: {classes_file}")
        
        # Note: For full YOLO training, you need bounding box annotations
        # This script collects images, but manual annotation is needed
        print("\n⚠️ NOTE: Images collected but need bounding box annotations for YOLO training")
        print("   Use tool like LabelImg or CVAT for annotation")


async def main():
    """Main collection workflow"""
    print("🚀 reCAPTCHA Dataset Collector")
    print("="*60)
    
    collector = RecaptchaDatasetCollector()
    
    # Setup
    await collector.setup()
    
    # Collect images
    await collector.collect_from_recaptcha_demo(num_samples=50)
    
    # Create YOLO dataset structure
    await collector.create_yolo_dataset()
    
    print("\n" + "="*60)
    print("📊 Collection Complete!")
    print("="*60)
    print(f"   Total images: {len(collector.metadata)}")
    print(f"   Dataset: {DATASET_DIR}")
    print("\n💡 Next steps:")
    print("   1. Annotate images with bounding boxes (LabelImg, CVAT)")
    print("   2. Train Yolo: yolo detect train data=dataset/yolo model=yolov8n.pt epochs=100")
    print("   3. Update solver to use custom model")


if __name__ == "__main__":
    asyncio.run(main())