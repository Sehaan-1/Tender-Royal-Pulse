import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

class RunSummaryReporter:
    def __init__(self, base_reports_dir: str = "reports"):
        self.base_reports_dir = Path(base_reports_dir)

    def save_summary(self, run_id: str, summary_data: dict[str, Any]):
        run_dir = self.base_reports_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        file_path = run_dir / "run_summary.json"

        try:
            with open(file_path, mode='w', encoding='utf-8') as f:
                json.dump(summary_data, f, indent=4, ensure_ascii=False)
            logger.info(f"Run summary saved to {file_path}")
        except Exception as e:
            logger.error(f"Error saving run summary to {file_path}: {e}")
            raise e
