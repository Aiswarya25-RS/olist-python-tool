import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.olist_tool import (
    ConfigurationError,
    InputFileError,
    load_config,
    process_file,
    run,
)


class OlistToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input_dir = self.root / "raw"
        self.output_dir = self.root / "processed"
        self.input_dir.mkdir()
        self.config_path = self.root / "config.json"
        self.config = {
            "input_dir": str(self.input_dir),
            "output_dir": str(self.output_dir),
            "log_file": str(self.root / "logs" / "tool.log"),
            "keep_unmapped_columns": True,
            "column_mappings": {"sample.csv": {"id": "record_id"}},
            "required_columns": {"sample.csv": ["record_id"]},
        }
        self.write_config()

    def tearDown(self):
        self.temp.cleanup()

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")

    def write_csv(self, content="id,name\n1,Ada\n,Missing\n"):
        (self.input_dir / "sample.csv").write_text(content, encoding="utf-8")

    def test_load_config(self):
        self.assertEqual(load_config(self.config_path)["input_dir"], str(self.input_dir))

    def test_missing_config_raises_custom_exception(self):
        with self.assertRaises(ConfigurationError):
            load_config(self.root / "absent.json")

    def test_mapping_preserves_extra_columns_and_splits_bad_records(self):
        self.write_csv()
        good, bad = process_file(self.input_dir / "sample.csv", self.config, self.output_dir)
        result = pd.read_csv(self.output_dir / "sample_processed.csv")
        self.assertEqual((good, bad), (1, 1))
        self.assertIn("record_id", result.columns)
        self.assertIn("name", result.columns)

    def test_run_writes_log_bad_records_and_manifest(self):
        self.write_csv()
        run(self.config_path)
        self.assertTrue((self.root / "logs" / "tool.log").exists())
        self.assertTrue((self.output_dir / "manifest.json").exists())
        self.assertTrue((self.output_dir / "bad_records.csv").exists())
        self.assertEqual(len(pd.read_csv(self.output_dir / "bad_records.csv")), 1)
        # Per-file processing rejects invalid rows; the summary counts them.
        self.assertEqual(json.loads((self.output_dir / "manifest.json").read_text())["sample.csv"]["bad_rows"], 1)

    def test_run_skips_unchanged_input(self):
        self.write_csv()
        first = run(self.config_path)
        second = run(self.config_path)
        self.assertEqual(first["processed_files"], 1)
        self.assertEqual(second["skipped_files"], 1)

    def test_semicolon_delimited_file_uses_configured_delimiter(self):
        self.config["column_mappings"]["sample.csv"] = {"id": "record_id"}
        self.config["delimiters"] = {"sample.csv": ";"}
        self.write_config()
        self.write_csv("id;name\n1;Ada\n")
        good, bad = process_file(self.input_dir / "sample.csv", self.config, self.output_dir)
        result = pd.read_csv(self.output_dir / "sample_processed.csv")
        self.assertEqual((good, bad), (1, 0))
        self.assertEqual(result.loc[0, "name"], "Ada")

    def test_missing_input_directory_fails_gracefully(self):
        self.config["input_dir"] = str(self.root / "missing")
        self.write_config()
        with self.assertRaises(InputFileError):
            run(self.config_path)


if __name__ == "__main__":
    unittest.main()
