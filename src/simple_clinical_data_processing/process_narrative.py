import json
import os
import sys
from collections import defaultdict
from typing import cast

from medspacy import load
from medspacy.target_matcher import TargetMatcher, TargetRule

# Define target rules
rules = [
    TargetRule("metformin", "MEDICATION"),
    TargetRule("pneumonia", "PROBLEM"),
    TargetRule("chest pain", "PROBLEM"),
]


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


# Load the model and add the rules from the JSON file
nlp = load()
target_matcher = cast(TargetMatcher, nlp.get_pipe("medspacy_target_matcher"))
target_matcher.add(load_target_rules("config/target-rules.json"))


def process_clinical_text(file_path):
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
        if ent.label_ in ["MEDICATION", "PROBLEM"]:
            fact = {
                "category": ent.label_.lower(),
                "concept": {"system": None, "code": None, "display": ent.text},
                "value": {"number": None, "text": ent.text, "unit": None},
                "assertion": "present",
                "temporality": "current",
                "effective_time": None,
                "source_ref": {
                    "document_id": file_path,
                    "field_path": f"{ent.label_.lower()}_{ent.id}",
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


def save_output_to_file(output, output_path):
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(output, file, indent=2)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print(
            "Usage: python process_clinical_data.py <input_file_path> [output_file_path]"
        )
        sys.exit(1)

    input_file_path = sys.argv[1]
    output_file_path = None
    if len(sys.argv) > 2:
        output_file_path = sys.argv[2]

    if not os.path.exists(input_file_path):
        print(f"File not found: {input_file_path}")
        sys.exit(1)

    result = process_clinical_text(input_file_path)
    if output_file_path:
        save_output_to_file(result, output_file_path)
        print(f"Output saved to {output_file_path}")
    else:
        print(json.dumps(result, indent=2))
