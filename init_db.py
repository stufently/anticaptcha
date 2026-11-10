#!/usr/bin/env python3
"""Create database tables (same as the API does on startup).

Users and API keys are created through the API with ANTICAPTCHA_ADMIN_TOKEN;
no default account with a known password is created here.
"""
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from app.config import settings  # noqa: E402
from app.database import init_db  # noqa: E402


def main():
    init_db()
    print(f"✅ Database initialized: {settings.database_path}")


if __name__ == "__main__":
    main()
