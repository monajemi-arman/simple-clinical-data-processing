"""
load_structured.py
------------------
Loads every CSV under data/structured/, identifies each file as labs or meds
by inspecting its column headers, validates every row against the matching
JSON Schema, and returns two typed lists.

Column-based detection
  Labs  → must contain all of: patient_id, test_code, test_name,
                                result_value, result_unit, result_time
  Meds  → must contain all of: patient_id, med_code, med_name,
                                dose, frequency, list_date, status

Validation rules (applied per-row)
  • All required columns must be non-empty.
  • result_time / list_date must parse as ISO-8601 date(-time).
  • result_value for labs is allowed to be non-numeric (e.g. "pending"),
    but the fact is recorded as a warning.
  • status for meds must be one of the enum values in the schema.

A ValidationError is raised if any *required* field is missing.
Soft issues (unknown code, non-numeric value, bad date format) are
collected as warnings attached to each row dict under the key "_warnings".
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Any

from simple_clinical_data_processing.config import labs_schema, meds_schema

# ── column signatures used for file-type detection ──────────────────────────

_LAB_COLUMNS: frozenset[str] = frozenset(
    labs_schema["required"]
)
_MED_COLUMNS: frozenset[str] = frozenset(
    meds_schema["required"]
)

_STRUCTURED_DIR = Path(__file__).parent.parent.parent.parent / "data" / "structured"

# ── public result types ──────────────────────────────────────────────────────

LabRow = dict[str, Any]   # keys match labs-schema.json properties + "_warnings"
MedRow = dict[str, Any]   # keys match meds-schema.json properties + "_warnings"


@dataclass
class StructuredData:
    labs: list[LabRow] = field(default_factory=list)
    meds: list[MedRow] = field(default_factory=list)


# ── exceptions ───────────────────────────────────────────────────────────────

class ValidationError(ValueError):
    """Raised when a required field is missing or blank."""


# ── helpers ──────────────────────────────────────────────────────────────────

_ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",
)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_valid_datetime(value: str) -> bool:
    if not _ISO_DATETIME_RE.match(value):
        return False
    try:
        datetime.fromisoformat(value.rstrip("Z").replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _is_valid_date(value: str) -> bool:
    if not _ISO_DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _detect_type(headers: list[str]) -> str | None:
    """Return 'lab', 'med', or None if the header set is unrecognised."""
    col_set = frozenset(h.strip().lower() for h in headers)
    if _LAB_COLUMNS <= col_set:
        return "lab"
    if _MED_COLUMNS <= col_set:
        return "med"
    return None


# ── per-row validators ────────────────────────────────────────────────────────

def _validate_lab_row(row: dict[str, str], file_name: str, line: int) -> LabRow:
    warnings: list[str] = []
    out: LabRow = {"_warnings": warnings}

    # required non-empty fields
    for col in labs_schema["required"]:
        raw = row.get(col, "").strip()
        if col in ("result_value", "result_unit"):
            # these are allowed to be empty/non-numeric — handled below
            pass
        elif not raw:
            raise ValidationError(
                f"{file_name}:{line} — required field '{col}' is missing or blank"
            )

    out["patient_id"] = row["patient_id"].strip()
    out["test_code"] = row["test_code"].strip()
    out["test_name"] = row["test_name"].strip()

    # result_value: try numeric, fall back to string
    raw_value = row.get("result_value", "").strip()
    if not raw_value:
        warnings.append(f"result_value is empty")
        out["result_value"] = None
    else:
        try:
            out["result_value"] = float(raw_value)
        except ValueError:
            warnings.append(
                f"result_value '{raw_value}' is not numeric — stored as text"
            )
            out["result_value"] = raw_value

    # result_unit: optional
    raw_unit = row.get("result_unit", "").strip()
    out["result_unit"] = raw_unit if raw_unit else None
    if not raw_unit:
        warnings.append("result_unit is empty")

    # result_time: must be a valid ISO-8601 datetime
    raw_time = row.get("result_time", "").strip()
    out["result_time"] = raw_time
    if not _is_valid_datetime(raw_time):
        warnings.append(
            f"result_time '{raw_time}' is not a valid ISO-8601 datetime"
        )

    return out


_MED_STATUS_ENUM: frozenset[str] = frozenset(
    meds_schema["properties"]["status"]["enum"]
)


def _validate_med_row(row: dict[str, str], file_name: str, line: int) -> MedRow:
    warnings: list[str] = []
    out: MedRow = {"_warnings": warnings}

    # required non-empty fields
    for col in meds_schema["required"]:
        raw = row.get(col, "").strip()
        if not raw:
            raise ValidationError(
                f"{file_name}:{line} — required field '{col}' is missing or blank"
            )

    out["patient_id"] = row["patient_id"].strip()
    out["med_code"] = row["med_code"].strip()
    out["med_name"] = row["med_name"].strip()
    out["dose"] = row["dose"].strip()
    out["frequency"] = row["frequency"].strip()

    # list_date: must be YYYY-MM-DD
    raw_date = row["list_date"].strip()
    out["list_date"] = raw_date
    if not _is_valid_date(raw_date):
        warnings.append(
            f"list_date '{raw_date}' is not a valid ISO-8601 date (YYYY-MM-DD)"
        )

    # status: must be in enum
    raw_status = row["status"].strip().lower()
    out["status"] = raw_status
    if raw_status not in _MED_STATUS_ENUM:
        warnings.append(
            f"status '{raw_status}' is not one of {sorted(_MED_STATUS_ENUM)}"
        )

    return out


# ── public API ───────────────────────────────────────────────────────────────

def load_structured(data_dir: Path = _STRUCTURED_DIR) -> StructuredData:
    """
    Read all *.csv files under *data_dir*, detect their type, validate each
    row, and return a :class:`StructuredData` containing the parsed rows.

    Raises
    ------
    ValidationError
        If any required field is missing or blank in any row.
    ValueError
        If a CSV file's columns cannot be identified as labs or meds.
    """
    result = StructuredData()

    csv_files = sorted(data_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")

    for csv_path in csv_files:
        with csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise ValueError(f"{csv_path.name}: file is empty or has no header row")

            file_type = _detect_type(list(reader.fieldnames))
            if file_type is None:
                raise ValueError(
                    f"{csv_path.name}: columns {list(reader.fieldnames)!r} do not match "
                    "labs or meds schema signatures"
                )

            for line_num, row in enumerate(reader, start=2):  # 1-based, header is line 1
                if file_type == "lab":
                    result.labs.append(
                        _validate_lab_row(row, csv_path.name, line_num)
                    )
                else:
                    result.meds.append(
                        _validate_med_row(row, csv_path.name, line_num)
                    )

    return result
