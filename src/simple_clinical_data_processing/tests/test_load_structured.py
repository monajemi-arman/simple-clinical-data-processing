import csv
import os
import unittest
from pathlib import Path

from simple_clinical_data_processing.load_structured import load_structured


class TestLoadStructured(unittest.TestCase):

    def test_file_type_detection(self):
        # Test lab file detection
        lab_file = Path("testdata/valid_labs.csv")
        lab_file.write_text("patient_id,test_code,test_name,result_value,result_unit,result_time\n123,LAB-001,Complete Blood Count,9.2,mmol/L,2020-01-01T12:00:00Z")

        # Test med file detection
        med_file = Path("testdata/valid_meds.csv")
        med_file.write_text("patient_id,med_code,med_name,dose,frequency,list_date,status\n123,MED-001,Aspirin,81 mg,daily,2020-01-01,active")

        # Test unrecognised file
        unknown_file = Path("testdata/unknown.csv")
        unknown_file.write_text("patient_id,test_code,test_name,other_column\n123,LAB-001,Complete Blood Count,extra")

        # Check lab file detection
        with open(lab_file, "r") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is not None:
                headers = list(reader.fieldnames)
                self.assertEqual(load_structured()._detect_type(headers), "lab")

        # Check med file detection
        with open(med_file, "r") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is not None:
                headers = list(reader.fieldnames)
                self.assertEqual(load_structured()._detect_type(headers), "med")

        # Check unrecognised file
        with open(unknown_file, "r") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is not None:
                headers = list(reader.fieldnames)
                self.assertIsNone(load_structured()._detect_type(headers))

        # Clean up
        lab_file.unlink()
        med_file.unlink()
        unknown_file.unlink()

    def test_required_field_validation(self):
        # Test lab file with missing required field
        lab_file = Path("testdata/invalid_labs.csv")
        lab_file.write_text("patient_id,test_code,test_name,result_value,result_unit,result_time\n123,LAB-001,Complete Blood Count,,mmol/L,2020-01-01T12:00:00Z")

        # Test med file with missing required field
        med_file = Path("testdata/invalid_meds.csv")
        med_file.write_text("patient_id,med_code,med_name,dose,frequency,list_date,status\n123,MED-001,Aspirin,81 mg,daily,2020-01-01,\n")

        # Check lab file validation
        with self.assertRaises(ValueError), open(lab_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                load_structured()._validate_lab_row(row, lab_file.name, 1)

        # Check med file validation
        with self.assertRaises(ValueError), open(med_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                load_structured()._validate_med_row(row, med_file.name, 1)

        # Clean up
        lab_file.unlink()
        med_file.unlink()

    def test_date_format_validation(self):
        # Test invalid date format in lab file
        lab_file = Path("testdata/invalid_labs_date.csv")
        lab_file.write_text("patient_id,test_code,test_name,result_value,result_unit,result_time\n123,LAB-001,Complete Blood Count,9.2,mmol/L,invalid-date")

        # Test invalid date format in med file
        med_file = Path("testdata/invalid_meds_date.csv")
        med_file.write_text("patient_id,med_code,med_name,dose,frequency,list_date,status\n123,MED-001,Aspirin,81 mg,daily,invalid-date,active")

        # Check lab file validation
        with open(lab_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                result = load_structured()._validate_lab_row(row, lab_file.name, 1)
                self.assertIn("result_time 'invalid-date' is not a valid ISO-8601 datetime", result["_warnings"])

        # Check med file validation
        with open(med_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                result = load_structured()._validate_med_row(row, med_file.name, 1)
                self.assertIn("list_date 'invalid-date' is not a valid ISO-8601 date (YYYY-MM-DD)", result["_warnings"])

        # Clean up
        lab_file.unlink()
        med_file.unlink()

    def test_enum_validation(self):
        # Test invalid status in med file
        med_file = Path("testdata/invalid_meds_status.csv")
        med_file.write_text("patient_id,med_code,med_name,dose,frequency,list_date,status\n123,MED-001,Aspirin,81 mg,daily,2020-01-01,invalid-status")

        # Check med file validation
        with open(med_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                result = load_structured()._validate_med_row(row, med_file.name, 1)
                self.assertIn("status 'invalid-status' is not one of ['active', 'inactive', 'discontinued', 'unknown']", result["_warnings"])

        # Clean up
        med_file.unlink()

    def test_non_numeric_result_value(self):
        # Test non-numeric result value in lab file
        lab_file = Path("testdata/non_numeric_result_value.csv")
        lab_file.write_text("patient_id,test_code,test_name,result_value,result_unit,result_time\n123,LAB-001,Complete Blood Count,pending,mmol/L,2020-01-01T12:00:00Z")

        # Check lab file validation
        with open(lab_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                result = load_structured()._validate_lab_row(row, lab_file.name, 1)
                self.assertIn("result_value 'pending' is not numeric — stored as text", result["_warnings"])

        # Clean up
        lab_file.unlink()

    def test_optional_fields(self):
        # Test optional fields in lab file
        lab_file = Path("testdata/optional_fields.csv")
        lab_file.write_text("patient_id,test_code,test_name,result_value,result_unit,result_time\n123,LAB-001,Complete Blood Count,9.2,,2020-01-01T12:00:00Z")

        # Check lab file validation
        with open(lab_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                result = load_structured()._validate_lab_row(row, lab_file.name, 1)
                self.assertEqual(result["result_unit"], None)

        # Clean up
        lab_file.unlink()

if __name__ == '__main__':
    os.makedirs("testdata", exist_ok=True)
    unittest.main()
