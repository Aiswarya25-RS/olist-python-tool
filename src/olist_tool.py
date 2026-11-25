"""Configurable, validated and idempotent CSV processing for Olist-style data."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd


class OlistToolError(Exception):
    """Base exception for expected processing failures."""


class ConfigurationError(OlistToolError):
    """Raised when configuration is missing or malformed."""


class InputFileError(OlistToolError):
    """Raised when an input CSV cannot be read."""


class ValidationError(OlistToolError):
    """Raised when a file cannot be validated as configured."""


def load_config(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot load config {path}: {exc}") from exc
    for key in ("input_dir", "output_dir", "log_file"):
        if not isinstance(config.get(key), str) or not config[key]:
            raise ConfigurationError(f"Config requires a non-empty '{key}'")
    for key in ("column_mappings", "required_columns"):
        if not isinstance(config.get(key, {}), dict):
            raise ConfigurationError(f"'{key}' must be a JSON object")
    return config


def configure_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("olist_tool")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # Replace handlers so repeated notebook runs don't duplicate log entries.
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OlistToolError(f"Cannot read manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OlistToolError(f"Manifest must contain a JSON object: {path}")
    return value


def process_file(csv_path: Path, config: dict[str, Any], output_dir: Path) -> tuple[int, int]:
    try:
        delimiter = config.get("delimiters", {}).get(csv_path.name, ",")
        if not isinstance(delimiter, str) or not delimiter:
            raise ConfigurationError(f"Delimiter for {csv_path.name} must be a non-empty string")
        frame = pd.read_csv(csv_path, sep=delimiter)
    except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise InputFileError(f"Cannot read {csv_path}: {exc}") from exc

    mappings = config.get("column_mappings", {}).get(csv_path.name, {})
    if not isinstance(mappings, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in mappings.items()
    ):
        raise ConfigurationError(f"Column mapping for {csv_path.name} must map strings to strings")
    missing_sources = sorted(set(mappings) - set(frame.columns))
    if missing_sources:
        raise ValidationError(f"{csv_path.name} is missing mapped source columns: {missing_sources}")
    frame = frame.rename(columns=mappings)
    if not config.get("keep_unmapped_columns", True):
        frame = frame[list(mappings.values())]

    required = config.get("required_columns", {}).get(csv_path.name, [])
    if not isinstance(required, list) or not all(isinstance(name, str) for name in required):
        raise ConfigurationError(f"Required columns for {csv_path.name} must be a list of strings")
    absent = sorted(set(required) - set(frame.columns))
    if absent:
        raise ValidationError(f"{csv_path.name} lacks required standardized columns: {absent}")

    if required:
        invalid = frame[required].isna().any(axis=1)
    else:
        invalid = pd.Series(False, index=frame.index)
    good = frame.loc[~invalid].copy()
    bad = frame.loc[invalid].copy()
    bad.insert(0, "_source_file", csv_path.name)
    bad.insert(1, "_bad_reason", "missing required value: " + ", ".join(required))

    output_dir.mkdir(parents=True, exist_ok=True)
    good.to_csv(output_dir / f"{csv_path.stem}_processed.csv", index=False)
    bad.to_csv(output_dir / f"{csv_path.stem}_bad_records.csv", index=False)
    return len(good), len(bad)


def run(config_path: str | Path = "config.json") -> dict[str, int]:
    config = load_config(config_path)
    input_dir = Path(config["input_dir"])
    output_dir = Path(config["output_dir"])
    logger = configure_logging(Path(config["log_file"]))
    try:
        if not input_dir.is_dir():
            raise InputFileError(f"Input directory does not exist: {input_dir}")
        files = sorted(input_dir.glob("*.csv"))
        if not files:
            raise InputFileError(f"No CSV files found in {input_dir}")

        manifest_path = output_dir / "manifest.json"
        manifest = _read_manifest(manifest_path)
        summary = {"processed_files": 0, "skipped_files": 0, "good_rows": 0, "bad_rows": 0}
        for csv_path in files:
            try:
                checksum = _sha256(csv_path)
                prior = manifest.get(csv_path.name, {})
                output_path = output_dir / f"{csv_path.stem}_processed.csv"
                if prior.get("sha256") == checksum and output_path.exists():
                    summary["skipped_files"] += 1
                    logger.info("Skipped unchanged file %s", csv_path.name)
                    continue
                good_count, bad_count = process_file(csv_path, config, output_dir)
                manifest[csv_path.name] = {"sha256": checksum, "good_rows": good_count, "bad_rows": bad_count}
                summary["processed_files"] += 1
                summary["good_rows"] += good_count
                summary["bad_rows"] += bad_count
                logger.info("Processed %s: %d good, %d bad", csv_path.name, good_count, bad_count)
            except OlistToolError:
                logger.exception("Failed processing %s", csv_path.name)
                raise
            except Exception as exc:
                logger.exception("Unexpected failure processing %s", csv_path.name)
                raise OlistToolError(f"Unexpected failure processing {csv_path.name}: {exc}") from exc

        output_dir.mkdir(parents=True, exist_ok=True)
        bad_files = sorted(output_dir.glob("*_bad_records.csv"))
        if bad_files:
            pd.concat((pd.read_csv(path) for path in bad_files), ignore_index=True).to_csv(
                output_dir / "bad_records.csv", index=False
            )
        else:
            pd.DataFrame(columns=["_source_file", "_bad_reason"]).to_csv(
                output_dir / "bad_records.csv", index=False
            )
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        logger.info("Run complete: %s", summary)
        return summary
    finally:
        for handler in logger.handlers[:]:
            handler.flush()
            handler.close()
            logger.removeHandler(handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.json", help="Path to JSON configuration")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.config), indent=2))
    except OlistToolError as exc:
        logging.getLogger("olist_tool").error("Run failed: %s", exc)
        print(f"Processing failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
