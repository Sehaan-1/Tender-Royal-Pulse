import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

class JSONLExporter:
    def __init__(self, output_path: str):
        self.output_path = Path(output_path)

    def export(self, data: list[dict[str, Any]], filename: str):
        if not data:
            logger.warning(f"No data to export to {filename}")
            return

        file_path = self.output_path / filename

        try:
            with open(file_path, mode='w', encoding='utf-8') as f:
                for entry in data:
                    f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            logger.info(f"Successfully exported data to {file_path}")
        except Exception as e:
            logger.error(f"Error exporting to JSONL {file_path}: {e}")
            raise e
