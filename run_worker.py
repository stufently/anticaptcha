#!/usr/bin/env python3
"""Run background worker for CAPTCHA solving"""
import asyncio
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from workers.task_worker import main

if __name__ == "__main__":
    print("🚀 Starting CAPTCHA worker...")
    asyncio.run(main())