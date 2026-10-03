import json
import os
import sys
from collections import defaultdict
from functools import cache
from pathlib import Path
from typing import cast

from medspacy import load
from medspacy.target_matcher import TargetMatcher, TargetRule

# Resolved relative to this script, so it works regardless of the caller's cwd
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Resolved relative to this script, so it works regardless of the caller's cwd
DEFAULT_RULES_PATH = str(PROJECT_ROOT / "config" / "target-rules.json")
DEFAULT_INPUT_PATH = str(PROJECT_ROOT / "data" / "narrative")


def load_target_rules(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    rules = []
    for item in config["target_rules"]:
        rules.append(
            TargetRule(
                literal=item["literal"],
                category=item["category"],
                pattern=item.get(
                    "pattern"
                ),  # regex string; None falls back to the literal
            )
        )
    return rules


@cache
def get_nlp(rules_path=DEFAULT_RULES_PATH):
    """Load the medSpaCy model + rules once per rules file (lazy, cached)."""
    nlp = load()
    target_matcher = cast(TargetMatcher, nlp.get_pipe("medspacy_target_matcher"))
    target_matcher.add(load_target_rules(rules_path))
    return nlp


def process_clinical_text(file_path, nlp):
    # Read the file content
    with open(file_path, "r", encoding="utf-8") as file:
        text = file.read()

    # Process with medSpacy
    doc = nlp(text)

    # Initialize output structure
    output = {
        "schema_version": "1.0",
        "patient": {"source_patient_id": None, "birth_date": None},
        "encounter": {"source_encounter_id": None, "event_time": None},
        "facts": [],
        "quality": {"missing_required": [], "conflicts": [], "warnings": []},
    }

    # Extract patient information
    patient_info = defaultdict(str)
    for ent in doc.ents:
        if ent.label_ == "PATIENT_ID":
            patient_info["source_patient_id"] = ent.text
        elif ent.label_ == "BIRTH_DATE":
            patient_info["birth_date"] = ent.text

    # Extract encounter information
    encounter_info = defaultdict(str)
    for ent in doc.ents:
        if ent.label_ == "ENCOUNTER_ID":
            encounter_info["source_encounter_id"] = ent.text
        elif ent.label_ == "EVENT_TIME":
            encounter_info["event_time"] = ent.text

    # Map extracted information to output structure
    output["patient"].update(patient_info)
    output["encounter"].update(encounter_info)

    # Extract clinical facts
    for ent in doc.ents:
        assertion = "present"
        if ent._.is_negated:
            assertion = "absent"
        elif ent._.is_uncertain:
            assertion = "possible"

        fact = {
            "category": ent.label_.lower(),
            "concept": {"system": None, "code": None, "display": ent.text},
            "value": {"number": None, "text": ent.text, "unit": None},
            "assertion": assertion,
            "temporality": "current",
            "effective_time": None,
            "source_ref": {
                "document_id": file_path,
                "field_path": f"{ent.label_.lower()}_{ent.start_char}",
                "text_span": ent.text,
            },
            "extraction_method": "model",
            "review_status": "needs_review",
        }
        output["facts"].append(fact)

    # Validate against the schema
    required_fields = {
        "patient": ["source_patient_id", "birth_date"],
        "encounter": ["source_encounter_id", "event_time"],
    }

    for section, fields in required_fields.items():
        for field in fields:
            if output[section][field] is None:
                output["quality"]["missing_required"].append(f"{section}.{field}")

    return output


def collect_input_files(path):
    """Return a sorted list of file paths for a file or a folder.

    - File: returns [path]
    - Folder: returns every regular file directly inside it (non-recursive,
      hidden files skipped).
    """
    path = os.fspath(path)
    if os.path.isfile(path):
        return [path]

    if os.path.isdir(path):
        with os.scandir(path) as entries:
            return sorted(
                entry.path
                for entry in entries
                if entry.is_file() and not entry.name.startswith(".")
            )

    raise FileNotFoundError(f"Path not found: {path}")


def save_output_to_file(output, output_path):
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(output, file, indent=2)


def process_narrative(
    input_path=DEFAULT_INPUT_PATH,
    output_path=None,
    rules_path=DEFAULT_RULES_PATH,
):
    """Main entry point: process a clinical text file or a folder of them.

    Args:
        input_path: path to a file, or to a folder (all files directly inside
            it are processed).
        output_path: optional path; if given, the result list is also written
            there as JSON.
        rules_path: JSON file with the target rules (defaults to
            config/target-rules.json next to this script).

    Returns:
        A list of result dicts, one per processed file (a one-element list for
        a single file). Files that can't be read/processed are reported on
        stderr and skipped.

    Raises:
        FileNotFoundError: if input_path doesn't exist.
    """
    files = collect_input_files(input_path)  # raises FileNotFoundError
    nlp = get_nlp(os.fspath(rules_path))

    results = []
    for file_path in files:
        try:
            results.append(process_clinical_text(file_path, nlp))
        except Exception as e:  # e.g. binary/non-UTF-8 files  # noqa: BLE001
            print(f"Skipping {file_path}: {e}", file=sys.stderr)

    if output_path:
        save_output_to_file(results, os.fspath(output_path))

    return results


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(
            "Usage: python process_narrative.py <input_file_or_folder> [output_file_path]"
        )
        return 1

    input_path = argv[0]
    output_path = argv[1] if len(argv) > 1 else None

    try:
        results = process_narrative(input_path, output_path)
    except FileNotFoundError as e:
        print(e)
        return 1

    if output_path:
        print(f"Output saved to {output_path} ({len(results)} document(s))")
    else:
        print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
