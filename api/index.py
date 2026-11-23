from __future__ import annotations

import os
import sys
from pathlib import Path

# Add src directory to python search path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from tender_royal_pulse.web.app import create_app

# In serverless environments (Vercel, AWS Lambda), write to /tmp
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    db_path = "/tmp/tenderpulse.db"
else:
    db_path = str(ROOT_DIR / "data" / "tenderpulse.db")

app = create_app(db_path)
