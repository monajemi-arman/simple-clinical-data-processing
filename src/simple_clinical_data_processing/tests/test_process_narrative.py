
import json
import sys
import tempfile
import unittest
from pathlib import Path

from simple_clinical_data_processing.process_narrative import process_narrative

# ── Pretty output ────────────────────────────────────────────────────────────

USE_COLOR = sys.stdout.isatty()

def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

GREEN = lambda t: _c("32", t)
RED = lambda t: _c("31", t)
BOLD = lambda t: _c("1", t)
DIM = lambda t: _c("2", t)
CYAN = lambda t: _c("36", t)


class PrettyResult(unittest.TextTestResult):
    """Prints one block per test: status, description, and each passed check."""

    def startTestRun(self):
        super().startTestRun()
        self.stream.writeln(BOLD(CYAN("\n━━━ Narrative processing tests ━━━\n")))

    def startTest(self, test):
        super().startTest(test)
        test._checks = []  # pyright: ignore[reportAttributeAccessIssue]

    def _report(self, test, symbol, colour):
        name = test._testMethodName.removeprefix("test_").replace("_", " ").title()
        self.stream.writeln(f"{colour(symbol)} {BOLD(name)}")
        desc = test.shortDescription()
        if desc:
            self.stream.writeln(DIM(f"    {desc}"))
        for check in getattr(test, "_checks", []):
            self.stream.writeln(f"    {GREEN('✔')} {check}")

    def addSuccess(self, test):
        super().addSuccess(test)
        self._report(test, "✔", GREEN)
        self.stream.writeln("")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._report(test, "✘", RED)
        self.stream.writeln(RED("    ✘ failed here (details below)\n"))

    def addError(self, test, err):
        super().addError(test, err)
        self._report(test, "✘", RED)
        self.stream.writeln(RED("    ✘ error here (details below)\n"))

    def printErrors(self):
        if self.errors or self.failures:
            self.stream.writeln(BOLD(RED("━━━ Details ━━━")))
        super().printErrors()


class PrettyRunner(unittest.TextTestRunner):
    resultclass = PrettyResult  # pyright: ignore[reportAssignmentType]

    def run(self, test):
        result = super().run(test)
        total = result.testsRun
        bad = len(result.failures) + len(result.errors)
        passed = total - bad - len(result.skipped)
        line = f"{passed}/{total} tests passed"
        self.stream.writeln(
            BOLD(GREEN(f"{line}")) if result.wasSuccessful() else BOLD(RED(f"{line}, {bad} failed"))
        )
        return result


# ── Tests ────────────────────────────────────────────────────────────────────

TEST_RULES = {
    "target_rules": [
        # Lookbehinds so the entity text is just the value, which is what
        # process_clinical_text copies into the output.
        {"literal": "PATIENT_ID", "category": "PATIENT_ID",
         "pattern": r"(?<=PATIENT_ID: )\d+"},
        {"literal": "BIRTH_DATE", "category": "BIRTH_DATE",
         "pattern": r"(?<=BIRTH_DATE: )\d{4}-\d{2}-\d{2}"},
        {"literal": "ENCOUNTER_ID", "category": "ENCOUNTER_ID",
         "pattern": r"(?<=ENCOUNTER_ID: )\d+"},
        {"literal": "EVENT_TIME", "category": "EVENT_TIME",
         "pattern": r"(?<=EVENT_TIME: )\S+"},
        {"literal": "Malaria", "category": "DISEASE"},
        {"literal": "High", "category": "SEVERITY"},
    ]
}

ALL_MISSING = [
    "patient.source_patient_id",
    "patient.birth_date",
    "encounter.source_encounter_id",
    "encounter.event_time",
]


class TestProcessNarrative(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.rules_path = Path(cls.tmp.name) / "rules.json"
        cls.rules_path.write_text(json.dumps(TEST_RULES))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def ok(self, message):
        """Record a passed check so the runner can display it."""
        if not hasattr(self, "_checks"):
            self._checks = []
        self._checks.append(message)  # pyright: ignore[reportAttributeAccessIssue]

    def run_on(self, text):
        """Write `text` to a temp file and run the pipeline on it."""
        path = Path(self.tmp.name) / f"{self._testMethodName}.txt"
        path.write_text(text)
        return process_narrative(
            input_path=str(path), output_path=None, rules_path=str(self.rules_path)
        )

    def test_empty_file(self):
        """Empty file should produce a valid output with no facts."""
        output = self.run_on("")

        self.assertEqual(output[0]['schema_version'], '1.0')
        self.assertEqual(output[0]['facts'], [])
        self.ok("Empty file produced valid output with no facts")

    def test_valid_patient_id(self):
        """File with PATIENT_ID entity should have it in the output."""
        output = self.run_on("PATIENT_ID: 123")
        self.assertEqual(output[0]['patient']['source_patient_id'], '123')
        self.ok("PATIENT_ID found in output")

    def test_valid_birth_date(self):
        """File with BIRTH_DATE entity should have it in the output."""
        output = self.run_on("BIRTH_DATE: 1990-01-01")
        self.assertEqual(output[0]['patient']['birth_date'], '1990-01-01')
        self.ok("BIRTH_DATE found in output")

    def test_valid_encounter_id(self):
        """File with ENCOUNTER_ID entity should have it in the output."""
        output = self.run_on("ENCOUNTER_ID: 456")
        self.assertEqual(output[0]['encounter']['source_encounter_id'], '456')
        self.ok("ENCOUNTER_ID found in output")

    def test_valid_event_time(self):
        """File with EVENT_TIME entity should have it in the output."""
        output = self.run_on("EVENT_TIME: 2020-01-01T12:00:00Z")
        self.assertEqual(output[0]['encounter']['event_time'], '2020-01-01T12:00:00Z')
        self.ok("EVENT_TIME found in output")

    def test_fact_extraction(self):
        """File with clinical facts should have them in the output."""
        output = self.run_on("Disease: Malaria, Severity: High")
        self.assertEqual(len(output[0]['facts']), 2)
        self.ok("Clinical facts extracted and added to output")

    def test_negated_fact(self):
        """Negated fact should have assertion 'absent' in the output."""
        output = self.run_on("No evidence of Malaria.")
        self.assertGreaterEqual(len(output[0]['facts']), 1)
        self.assertEqual(output[0]['facts'][0]['assertion'], 'absent')
        self.ok("Negated fact has correct assertion")

    def test_uncertain_fact(self):
        """Uncertain fact should have assertion 'possible' in the output."""
        output = self.run_on("Possible Malaria.")
        self.assertGreaterEqual(len(output[0]['facts']), 1)
        self.assertEqual(output[0]['facts'][0]['assertion'], 'possible')
        self.ok("Uncertain fact has correct assertion")

    def test_missing_required_fields(self):
        """Missing required fields should be reported in quality.missing_required."""
        output = self.run_on("")
        self.assertEqual(output[0]['quality']['missing_required'], ALL_MISSING)
        self.ok("Missing required fields reported in quality.missing_required")


if __name__ == "__main__":
    unittest.main(testRunner=PrettyRunner(stream=sys.stdout, verbosity=0))