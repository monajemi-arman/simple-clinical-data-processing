"""
load_structured.py
------------------
Loads CSV files (labs / meds), validates every row, and converts the result
into ClinicalOutput documents (schema_version 1.0), one per patient.

Input can be a CSV file, a directory of CSV files, or any mix of the two.

Column-based detection
  Labs  → must contain all of: patient_id, test_code, test_name,
                                result_value, result_unit, result_time
  Meds  → must contain all of: patient_id, med_code, med_name,
                                dose, frequency, list_date, status

A ValidationError is raised if any *required* field is missing.
Soft issues (non-numeric value, bad date format, unknown status) are collected
as warnings and surface in the output as `quality.warnings` and
`review_status = "needs_review"`.

CLI
  python -m simple_clinical_data_processing.load_structured <input...> [-o output.json]
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from simple_clinical_data_processing.config import labs_schema, meds_schema

# ── constants ────────────────────────────────────────────────────────────────

_LAB_COLUMNS: frozenset[str] = frozenset(labs_schema["required"])
_MED_COLUMNS: frozenset[str] = frozenset(meds_schema["required"])
_MED_STATUS_ENUM: frozenset[str] = frozenset(meds_schema["properties"]["status"]["enum"])

_STRUCTURED_DIR = Path(__file__).parent.parent.parent / "data" / "structured"

SCHEMA_VERSION = "1.0"

LabRow = dict[str, Any]
MedRow = dict[str, Any]
ClinicalOutput = dict[str, Any]  # conforms to the ClinicalOutput JSON Schema


class ValidationError(ValueError):
    """Raised when a required field is missing or blank."""


@dataclass
class StructuredData:
    labs: list[LabRow] = field(default_factory=list)
    meds: list[MedRow] = field(default_factory=list)

    def to_clinical_outputs(self) -> list[ClinicalOutput]:
        """Convert the validated rows into one ClinicalOutput per patient."""
        return build_clinical_outputs(self)

    @staticmethod
    def _detect_type(headers: list[str]) -> str | None:
        return _detect_type(headers)

    @staticmethod
    def _validate_lab_row(row: dict[str, str], file_name: str, line: int) -> LabRow:
        return _validate_lab_row(row, file_name, line)

    @staticmethod
    def _validate_med_row(row: dict[str, str], file_name: str, line: int) -> MedRow:
        return _validate_med_row(row, file_name, line)


# ── helpers ──────────────────────────────────────────────────────────────────

_ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_valid_datetime(value: str) -> bool:
    if not _ISO_DATETIME_RE.match(value):
        return False
    try:
        datetime.fromisoformat(value.rstrip("Z"))
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


# ── per-row validators ───────────────────────────────────────────────────────

def _validate_lab_row(row: dict[str, str], file_name: str, line: int) -> LabRow:
    warnings: list[str] = []
    out: LabRow = {
        "_warnings": warnings,
        "_source": {"document_id": file_name, "line": line},
    }

    for col in labs_schema["required"]:
        raw = (row.get(col) or "").strip()
        if col == "result_unit":
            continue  # optional
        if not raw:
            raise ValidationError(
                f"{file_name}:{line} — required field '{col}' is missing or blank"
            )

    out["patient_id"] = row["patient_id"].strip()
    out["test_code"] = row["test_code"].strip()
    out["test_name"] = row["test_name"].strip()

    raw_value = (row.get("result_value") or "").strip()
    if not raw_value:
        warnings.append("result_value is empty")
        out["result_value"] = None
    else:
        try:
            out["result_value"] = float(raw_value)
        except ValueError:
            warnings.append(f"result_value '{raw_value}' is not numeric — stored as text")
            out["result_value"] = raw_value

    raw_unit = (row.get("result_unit") or "").strip()
    out["result_unit"] = raw_unit or None
    if not raw_unit:
        warnings.append("result_unit is empty")

    raw_time = (row.get("result_time") or "").strip()
    out["result_time"] = raw_time
    if not _is_valid_datetime(raw_time):
        warnings.append(f"result_time '{raw_time}' is not a valid ISO-8601 datetime")

    return out


def _validate_med_row(row: dict[str, str], file_name: str, line: int) -> MedRow:
    warnings: list[str] = []
    out: MedRow = {
        "_warnings": warnings,
        "_source": {"document_id": file_name, "line": line},
    }

    for col in meds_schema["required"]:
        if not (row.get(col) or "").strip():
            raise ValidationError(
                f"{file_name}:{line} — required field '{col}' is missing or blank"
            )

    out["patient_id"] = row["patient_id"].strip()
    out["med_code"] = row["med_code"].strip()
    out["med_name"] = row["med_name"].strip()
    out["dose"] = row["dose"].strip()
    out["frequency"] = row["frequency"].strip()

    raw_date = row["list_date"].strip()
    out["list_date"] = raw_date
    if not _is_valid_date(raw_date):
        warnings.append(f"list_date '{raw_date}' is not a valid ISO-8601 date (YYYY-MM-DD)")

    raw_status = row["status"].strip().lower()
    out["status"] = raw_status
    if raw_status not in _MED_STATUS_ENUM:
        warnings.append(
            f"status '{raw_status}' is not one of {meds_schema['properties']['status']['enum']}"
        )

    return out


# ── conversion to ClinicalOutput ─────────────────────────────────────────────

# CSV med status → (assertion, temporality). Adjust keys to match your meds schema enum.
_MED_STATUS_MAP: dict[str, tuple[str, str]] = {
    "active":           ("present", "current"),
    "current":          ("present", "current"),
    "on-hold":          ("present", "current"),
    "on_hold":          ("present", "current"),
    "planned":          ("present", "planned"),
    "completed":        ("present", "historical"),
    "stopped":          ("present", "historical"),
    "discontinued":     ("present", "historical"),
    "inactive":         ("present", "historical"),
    "entered-in-error": ("absent",  "unknown"),
}

_DOSE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(.*?)\s*$")


def _split_dose(dose: str) -> tuple[float | None, str | None]:
    """'500 mg' → (500.0, 'mg'); 'one tablet' → (None, None)."""
    m = _DOSE_RE.match(dose)
    if not m:
        return None, None
    return float(m.group(1)), (m.group(2) or None)


def _review_status(warnings: list[str]) -> str:
    return "needs_review" if warnings else "accepted"


def _source_ref(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": row["_source"]["document_id"],
        "field_path": f"row[{row['_source']['line']}]",
        "text_span": None,
    }


def _lab_to_fact(row: LabRow) -> dict[str, Any]:
    raw_value = row["result_value"]
    time_ok = _is_valid_datetime(row["result_time"])
    return {
        "category": "observation",
        "concept": {"system": None, "code": row["test_code"], "display": row["test_name"]},
        "value": {
            "number": raw_value if isinstance(raw_value, float) else None,
            "text": raw_value if isinstance(raw_value, str) else None,
            "unit": row["result_unit"],
        },
        "assertion": "present",
        "temporality": "current" if time_ok else "unknown",
        "effective_time": row["result_time"] if time_ok else None,
        "source_ref": _source_ref(row),
        "extraction_method": "rule",
        "review_status": _review_status(row["_warnings"]),
    }


def _med_to_fact(row: MedRow) -> dict[str, Any]:
    number, unit = _split_dose(row["dose"])
    assertion, temporality = _MED_STATUS_MAP.get(row["status"], ("uncertain", "unknown"))
    return {
        "category": "medication",
        "concept": {"system": None, "code": row["med_code"], "display": row["med_name"]},
        "value": {
            "number": number,
            "text": f"{row['dose']} {row['frequency']}".strip(),
            "unit": unit,
        },
        "assertion": assertion,
        "temporality": temporality,
        "effective_time": row["list_date"] if _is_valid_date(row["list_date"]) else None,
        "source_ref": _source_ref(row),
        "extraction_method": "rule",
        "review_status": _review_status(row["_warnings"]),
    }


def _find_conflicts(labs: list[LabRow], meds: list[MedRow]) -> list[str]:
    """Same lab/time with different values, or same med/date with different dose/status."""
    conflicts: list[str] = []

    seen_labs: dict[tuple, LabRow] = {}
    for r in labs:
        prev = seen_labs.setdefault((r["test_code"], r["result_time"]), r)
        if prev is not r and prev["result_value"] != r["result_value"]:
            conflicts.append(
                f"lab {r['test_code']} at {r['result_time']}: "
                f"{prev['result_value']!r} vs {r['result_value']!r}"
            )

    seen_meds: dict[tuple, MedRow] = {}
    for r in meds:
        prev = seen_meds.setdefault((r["med_code"], r["list_date"]), r)
        if prev is not r and (prev["dose"], prev["status"]) != (r["dose"], r["status"]):
            conflicts.append(
                f"med {r['med_code']} on {r['list_date']}: "
                f"({prev['dose']}, {prev['status']}) vs ({r['dose']}, {r['status']})"
            )

    return conflicts


def _build_patient_output(
    patient_id: str, labs: list[LabRow], meds: list[MedRow]
) -> ClinicalOutput:
    warnings = [
        f"{r['_source']['document_id']}:{r['_source']['line']} — {w}"
        for r in (*labs, *meds)
        for w in r["_warnings"]
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "patient": {"source_patient_id": patient_id, "birth_date": None},
        "encounter": {"source_encounter_id": None, "event_time": None},
        "facts": [_lab_to_fact(r) for r in labs] + [_med_to_fact(r) for r in meds],
        "quality": {
            # The CSVs don't carry these, so they're reported as missing.
            "missing_required": [
                "patient.birth_date",
                "encounter.source_encounter_id",
                "encounter.event_time",
            ],
            "conflicts": _find_conflicts(labs, meds),
            "warnings": warnings,
        },
    }


def build_clinical_outputs(data: StructuredData) -> list[ClinicalOutput]:
    """Group validated rows by patient and build one ClinicalOutput each."""
    labs_by_patient: dict[str, list[LabRow]] = defaultdict(list)
    meds_by_patient: dict[str, list[MedRow]] = defaultdict(list)
    for r in data.labs:
        labs_by_patient[r["patient_id"]].append(r)
    for r in data.meds:
        meds_by_patient[r["patient_id"]].append(r)

    patient_ids = sorted(labs_by_patient.keys() | meds_by_patient.keys())
    return [
        _build_patient_output(pid, labs_by_patient[pid], meds_by_patient[pid])
        for pid in patient_ids
    ]


# ── input resolution & loading ───────────────────────────────────────────────

def resolve_inputs(sources: Iterable[Path]) -> list[Path]:
    """
    Expand each source into CSV files:
      • a directory → every *.csv directly inside it (sorted)
      • a file      → used as-is
    Duplicates are dropped, order is preserved.
    """
    files: list[Path] = []
    for src in sources:
        if src.is_dir():
            found = sorted(src.glob("*.csv"))
            if not found:
                raise FileNotFoundError(f"No CSV files found in directory {src}")
            files.extend(found)
        elif src.is_file():
            files.append(src)
        else:
            raise FileNotFoundError(f"Input not found: {src}")
    return list(dict.fromkeys(files))


def _load_csv(csv_path: Path, result: StructuredData) -> None:
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

        for line_num, row in enumerate(reader, start=2):  # header is line 1
            if file_type == "lab":
                result.labs.append(_validate_lab_row(row, csv_path.name, line_num))
            else:
                result.meds.append(_validate_med_row(row, csv_path.name, line_num))


def process_structured(
    source: Path | Iterable[Path] = _STRUCTURED_DIR,
) -> StructuredData:
    """
    Load and validate CSVs from a file, a directory, or a list of either.

    Raises
    ------
    FileNotFoundError  If an input doesn't exist or a directory has no CSVs.
    ValidationError    If any required field is missing or blank in any row.
    ValueError         If a CSV's columns can't be identified as labs or meds.
    """
    sources = [Path(source)] if isinstance(source, (str, Path)) else [Path(s) for s in source]
    result = StructuredData()
    for csv_path in resolve_inputs(sources):
        _load_csv(csv_path, result)
    return result


def load_clinical_output(
    source: Path | Iterable[Path] = _STRUCTURED_DIR,
) -> list[ClinicalOutput]:
    """Load, validate, and convert CSVs into ClinicalOutput documents."""
    return process_structured(source).to_clinical_outputs()


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    import json
    import sys

    args = sys.argv[1:]
    if not args:
        print("usage: load_structured <file-or-dir ...> [-o output.json]", file=sys.stderr)
        return 2

    output = None
    if "-o" in args:
        i = args.index("-o")
        if i + 1 >= len(args):
            print("error: -o needs a file name", file=sys.stderr)
            return 2
        output = Path(args[i + 1])
        del args[i:i + 2]

    if not args:
        print("error: no input files or directories given", file=sys.stderr)
        return 2

    try:
        docs = load_clinical_output([Path(a) for a in args])
    except (OSError, ValueError) as exc:  # ValidationError is a ValueError
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(docs, indent=2, ensure_ascii=False)
    if output:
        output.write_text(text, encoding="utf-8")
        print(f"Wrote {len(docs)} document(s) to {output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
