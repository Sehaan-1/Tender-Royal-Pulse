import csv
import json
import unittest
from pathlib import Path

from tenderpulse.exporters.csv_exporter import CSVExporter
from tenderpulse.exporters.jsonl_exporter import JSONLExporter


class TestExporters(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("tests/temp_export")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.sample_data = [
            {"id": "1", "title": "Tender A", "desc": "Description with, comma"},
            {"id": "2", "title": "Tender B", "desc": 'Description with "quotes"'},
            {"id": "3", "title": "Tender C", "desc": "Description with\nnewline"},
        ]

    def test_csv_export_escaping(self):
        exporter = CSVExporter(self.test_dir)
        filename = "test.csv"
        exporter.export(self.sample_data, filename)

        file_path = self.test_dir / filename
        with open(file_path, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["desc"], "Description with, comma")
            self.assertEqual(rows[1]["desc"], 'Description with "quotes"')
            self.assertEqual(rows[2]["desc"], "Description with\nnewline")

    def test_jsonl_export_validity(self):
        exporter = JSONLExporter(self.test_dir)
        filename = "test.jsonl"
        exporter.export(self.sample_data, filename)

        file_path = self.test_dir / filename
        with open(file_path, encoding='utf-8') as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 3)
            for line in lines:
                data = json.loads(line)
                self.assertIn("id", data)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir)

if __name__ == "__main__":
    unittest.main()
