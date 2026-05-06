import csv
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

class CSVExporter:
    def __init__(self, output_path: str):
        self.output_path = Path(output_path)

    def export(self, data: list[dict[str, Any]], filename: str) -> None:
        if not data:
            logger.warning(f"No data to export to {filename}")
            return

        fieldnames = data[0].keys()
        file_path = self.output_path / filename

        try:
            with open(file_path, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
                writer.writeheader()
                writer.writerows(data)
            logger.info(f"Successfully exported data to {file_path}")
        except Exception as e:
            logger.error(f"Error exporting to CSV {file_path}: {e}")
            raise e
