import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from simple_clinical_data_processing.process_narrative import process_narrative
from simple_clinical_data_processing.process_structured import load_clinical_output

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "config" / "output-schema.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"


def load_validator() -> Draft202012Validator:
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        schema = json.load(fh)
    Draft202012Validator.check_schema(schema)
    # format_checker makes "date" / "date-time" actually enforced
    return Draft202012Validator(
        schema, format_checker=Draft202012Validator.FORMAT_CHECKER
    )


def validate_documents(
    docs: list[dict], source: str, validator: Draft202012Validator
) -> int:
    """Validate each document, print any errors, return the error count."""
    error_count = 0
    for i, doc in enumerate(docs):
        # str() each path element: paths mix str and int, which can't be compared
        errors = sorted(
            validator.iter_errors(doc),
            key=lambda e: [str(p) for p in e.absolute_path],
        )
        for err in errors:
            path = "/".join(str(p) for p in err.absolute_path) or "<root>"
            print(f"[{source} #{i}] {path}: {err.message}", file=sys.stderr)
        error_count += len(errors)
    status = "OK" if error_count == 0 else f"{error_count} error(s)"
    print(f"{source}: {len(docs)} document(s) validated - {status}")
    return error_count


def print_documents(structured_docs: list[dict], narrative_docs: list[dict]) -> None:
    """Pretty-print both document sets to the terminal."""
    print("\n=== STRUCTURED DOCUMENTS ===")
    print(json.dumps(structured_docs, indent=2, ensure_ascii=False))
    print("\n=== NARRATIVE DOCUMENTS ===")
    print(json.dumps(narrative_docs, indent=2, ensure_ascii=False))


def save_documents(structured_docs: list[dict], narrative_docs: list[dict]) -> None:
    """Ask where to save, then write each document set to its own JSON file."""
    default_dir = DEFAULT_OUTPUT_DIR
    answer = input(
        f"Folder to save into? Press Enter to use the default [{default_dir}]: "
    ).strip()
    out_dir = Path(answer).expanduser() if answer else default_dir

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, docs in (
            ("structured_docs.json", structured_docs),
            ("narrative_docs.json", narrative_docs),
        ):
            path = out_dir / name
            with path.open("w", encoding="utf-8") as fh:
                json.dump(docs, fh, indent=2, ensure_ascii=False)
            print(f"Saved {len(docs)} document(s) to {path}")
    except OSError as exc:
        print(f"Sorry, couldn't save the files: {exc}", file=sys.stderr)


def offer_output(structured_docs: list[dict], narrative_docs: list[dict]) -> None:
    """Friendly end-of-run menu: view in terminal, save to file, or skip."""
    # Skip silently when there's no human to answer (e.g. cron, CI, piped input)
    if not sys.stdin.isatty():
        return

    print(
        "\nAll done! What would you like to do with the structured and "
        "narrative documents?\n"
        "  [1] Show them here in the terminal\n"
        "  [2] Save them to files\n"
        "  [3] Both\n"
        "  [4] Nothing, just exit"
    )

    while True:
        try:
            choice = input("Your choice (1-4): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nOkay, exiting.")
            return

        if choice in {"1", "t", "terminal", "show"}:
            print_documents(structured_docs, narrative_docs)
            return
        if choice in {"2", "f", "file", "save"}:
            save_documents(structured_docs, narrative_docs)
            return
        if choice in {"3", "b", "both"}:
            print_documents(structured_docs, narrative_docs)
            save_documents(structured_docs, narrative_docs)
            return
        if choice in {"4", "n", "no", "exit", "q", "quit"}:
            print("Okay, exiting. Goodbye!")
            return

        print("Sorry, I didn't catch that. Please enter 1, 2, 3 or 4.")


def main() -> int:
    validator = load_validator()

    structured_docs = load_clinical_output()  # defaults to data/structured
    narrative_docs = process_narrative()  # defaults to data/narrative

    errors = validate_documents(structured_docs, "structured", validator)
    errors += validate_documents(narrative_docs, "narrative", validator)

    offer_output(structured_docs, narrative_docs)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
