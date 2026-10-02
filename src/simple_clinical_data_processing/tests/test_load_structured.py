import csv
from pathlib import Path
import pytest
from datetime import datetime
from simple_clinical_data_processing.load_structured import (
    load_structured, ValidationError, StructuredData
)
from simple_clinical_data_processing.config import labs_schema, meds_schema


@pytest.fixture(scope="function")
def labs_csv(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("structured")
    path = data_dir / "test_labs.csv"
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=labs_schema["required"])
        writer.writeheader()
        writer.writerow({
            "patient_id": "P001",
            "test_code": "LAB-44",
            "test_name": "Test 1",
            "result_value": "10",
            "result_unit": "mg/dL",
            "result_time": "2023-10-01T12:34:56Z"
        })
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture(scope="function")
def meds_csv(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("structured")
    path = data_dir / "test_meds.csv"
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=meds_schema["required"])
        writer.writeheader()
        writer.writerow({
            "patient_id": "P002",
            "med_code": "MED-17",
            "med_name": "Med 1",
            "dose": "20 mg",
            "frequency": "daily",
            "list_date": "2023-10-02",
            "status": "active"
        })
    yield path
    path.unlink(missing_ok=True)


def test_load_labs_csv(labs_csv):
    result = load_structured(labs_csv.parent)
    assert len(result.labs) == 1
    assert len(result.meds) == 0
    lab_row = result.labs[0]
    assert lab_row["patient_id"] == "P001"
    assert lab_row["test_code"] == "LAB-44"
    assert lab_row["result_value"] == 10.0
    assert not lab_row["_warnings"]


def test_load_meds_csv(meds_csv):
    result = load_structured(meds_csv.parent)
    assert len(result.labs) == 0
    assert len(result.meds) == 1
    med_row = result.meds[0]
    assert med_row["patient_id"] == "P002"
    assert med_row["med_code"] == "MED-17"
    assert med_row["list_date"] == "2023-10-02"
    assert not med_row["_warnings"]


def test_load_missing_field(labs_csv):
    path = labs_csv.parent / "test_labs.csv"
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=labs_schema["required"][:-1])
        writer.writeheader()
        writer.writerow({
            "patient_id": "P001",
            "test_code": "LAB-44",
            "test_name": "Test 1",
            "result_value": "10",
            "result_unit": "mg/dL"
        })

    with pytest.raises(ValidationError):
        load_structured(path.parent)


def test_load_non_numeric_result_value(labs_csv):
    with open(labs_csv, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=labs_schema["required"])
        writer.writeheader()
        writer.writerow({
            "patient_id": "P001",
            "test_code": "LAB-44",
            "test_name": "Test 1",
            "result_value": "pending",
            "result_unit": "mg/dL",
            "result_time": "2023-10-01T12:34:56Z"
        })

    result = load_structured(labs_csv.parent)
    assert len(result.labs) == 1
    assert len(result.meds) == 0
    lab_row = result.labs[0]
    assert lab_row["result_value"] == "pending"
    assert lab_row["_warnings"] == ["result_value is not numeric — stored as text"]


def test_load_invalid_result_time(labs_csv):
    with open(labs_csv, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=labs_schema["required"])
        writer.writeheader()
        writer.writerow({
            "patient_id": "P001",
            "test_code": "LAB-44",
            "test_name": "Test 1",
            "result_value": "10",
            "result_unit": "mg/dL",
            "result_time": "2023-10-01T24:00:00Z"
        })

    with pytest.raises(ValidationError):
        load_structured(labs_csv.parent)


def test_load_unknown_status(meds_csv):
    with open(meds_csv, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=meds_schema["required"])
        writer.writeheader()
        writer.writerow({
            "patient_id": "P002",
            "med_code": "MED-17",
            "med_name": "Med 1",
            "dose": "20 mg",
            "frequency": "daily",
            "list_date": "2023-10-02",
            "status": "pending"
        })

    with pytest.raises(ValidationError):
        load_structured(meds_csv.parent)
