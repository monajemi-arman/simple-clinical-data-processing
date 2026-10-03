import csv
import os
import shutil
import sys
import unittest
from pathlib import Path

from simple_clinical_data_processing.process_structured import process_structured

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
        self.stream.writeln(BOLD(CYAN("\n━━━ Structured data processing tests ━━━\n")))

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

class TestLoadStructured(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.makedirs("testdata", exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree("testdata", ignore_errors=True)

    def ok(self, message):
        """Record a passed check so the runner can display it."""
        self._checks.append(message)  # pyright: ignore[reportAttributeAccessIssue]

    def test_file_type_detection(self):
        """Headers are mapped to the right file type (lab / med / unknown)."""
        lab_file = Path("testdata/valid_labs.csv")
        lab_file.write_text("patient_id,test_code,test_name,result_value,result_unit,result_time\n123,LAB-001,Complete Blood Count,9.2,mmol/L,2020-01-01T12:00:00Z")

        med_file = Path("testdata/valid_meds.csv")
        med_file.write_text("patient_id,med_code,med_name,dose,frequency,list_date,status\n123,MED-001,Aspirin,81 mg,daily,2020-01-01,active")

        unknown_file = Path("testdata/unknown.csv")
        unknown_file.write_text("patient_id,test_code,test_name,other_column\n123,LAB-001,Complete Blood Count,extra")

        with open(lab_file, "r") as f:
            headers = list(csv.DictReader(f).fieldnames or [])
            self.assertEqual(process_structured()._detect_type(headers), "lab")
            self.ok("lab headers detected as 'lab'")

        with open(med_file, "r") as f:
            headers = list(csv.DictReader(f).fieldnames or [])
            self.assertEqual(process_structured()._detect_type(headers), "med")
            self.ok("medication headers detected as 'med'")

        with open(unknown_file, "r") as f:
            headers = list(csv.DictReader(f).fieldnames or [])
            self.assertIsNone(process_structured()._detect_type(headers))
            self.ok("unrecognised headers return None")

        lab_file.unlink()
        med_file.unlink()
        unknown_file.unlink()

    def test_required_field_validation(self):
        """Rows missing a required field raise ValueError."""
        lab_file = Path("testdata/invalid_labs.csv")
        lab_file.write_text("patient_id,test_code,test_name,result_value,result_unit,result_time\n123,LAB-001,Complete Blood Count,,mmol/L,2020-01-01T12:00:00Z")

        med_file = Path("testdata/invalid_meds.csv")
        med_file.write_text("patient_id,med_code,med_name,dose,frequency,list_date,status\n123,MED-001,Aspirin,81 mg,daily,2020-01-01,\n")

        with self.assertRaises(ValueError), open(lab_file, "r") as f:
            for row in csv.DictReader(f):
                process_structured()._validate_lab_row(row, lab_file.name, 1)
        self.ok("lab row with empty result_value rejected")

        with self.assertRaises(ValueError), open(med_file, "r") as f:
            for row in csv.DictReader(f):
                process_structured()._validate_med_row(row, med_file.name, 1)
        self.ok("med row with empty status rejected")

        lab_file.unlink()
        med_file.unlink()

    def test_date_format_validation(self):
        """Invalid dates produce a warning instead of crashing."""
        lab_file = Path("testdata/invalid_labs_date.csv")
        lab_file.write_text("patient_id,test_code,test_name,result_value,result_unit,result_time\n123,LAB-001,Complete Blood Count,9.2,mmol/L,invalid-date")

        med_file = Path("testdata/invalid_meds_date.csv")
        med_file.write_text("patient_id,med_code,med_name,dose,frequency,list_date,status\n123,MED-001,Aspirin,81 mg,daily,invalid-date,active")

        with open(lab_file, "r") as f:
            for row in csv.DictReader(f):
                result = process_structured()._validate_lab_row(row, lab_file.name, 1)
                self.assertIn("result_time 'invalid-date' is not a valid ISO-8601 datetime", result["_warnings"])
        self.ok("lab result_time warning raised for 'invalid-date'")

        with open(med_file, "r") as f:
            for row in csv.DictReader(f):
                result = process_structured()._validate_med_row(row, med_file.name, 1)
                self.assertIn("list_date 'invalid-date' is not a valid ISO-8601 date (YYYY-MM-DD)", result["_warnings"])
        self.ok("med list_date warning raised for 'invalid-date'")

        lab_file.unlink()
        med_file.unlink()

    def test_enum_validation(self):
        """Unknown medication status values are flagged."""
        med_file = Path("testdata/invalid_meds_status.csv")
        med_file.write_text("patient_id,med_code,med_name,dose,frequency,list_date,status\n123,MED-001,Aspirin,81 mg,daily,2020-01-01,invalid-status")

        with open(med_file, "r") as f:
            for row in csv.DictReader(f):
                result = process_structured()._validate_med_row(row, med_file.name, 1)
                self.assertIn("status 'invalid-status' is not one of ['active', 'inactive', 'discontinued', 'unknown']", result["_warnings"])
        self.ok("status 'invalid-status' flagged as not an allowed value")

        med_file.unlink()

    def test_non_numeric_result_value(self):
        """Non-numeric lab results are kept as text with a warning."""
        lab_file = Path("testdata/non_numeric_result_value.csv")
        lab_file.write_text("patient_id,test_code,test_name,result_value,result_unit,result_time\n123,LAB-001,Complete Blood Count,pending,mmol/L,2020-01-01T12:00:00Z")

        with open(lab_file, "r") as f:
            for row in csv.DictReader(f):
                result = process_structured()._validate_lab_row(row, lab_file.name, 1)
                self.assertIn("result_value 'pending' is not numeric — stored as text", result["_warnings"])
        self.ok("'pending' stored as text with a warning")

        lab_file.unlink()

    def test_optional_fields(self):
        """Empty optional fields are normalised to None."""
        lab_file = Path("testdata/optional_fields.csv")
        lab_file.write_text("patient_id,test_code,test_name,result_value,result_unit,result_time\n123,LAB-001,Complete Blood Count,9.2,,2020-01-01T12:00:00Z")

        with open(lab_file, "r") as f:
            for row in csv.DictReader(f):
                result = process_structured()._validate_lab_row(row, lab_file.name, 1)
                self.assertEqual(result["result_unit"], None)
        self.ok("empty result_unit becomes None")

        lab_file.unlink()


if __name__ == "__main__":
    unittest.main(testRunner=PrettyRunner(stream=sys.stdout, verbosity=0))
