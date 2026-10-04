# Simple Clinical Data Processing
Processing structured and narrative clinical data into a predefined format. Using NLP with medSpacy for narrative text processing.

[![Architecture diagram of monajemi-arman/simple-clinical-data-processing](https://gitdiagram.com/monajemi-arman/simple-clinical-data-processing/diagram.png)](https://gitdiagram.com/monajemi-arman/simple-clinical-data-processing?utm_source=readme&utm_medium=picture)

# Usage
The main script will automatically process the input data from data/narrative/ and data/structured/ and output the results.
```
uv run python src/simple_clinical_data_processing/main.py
```

# Tests
Run the tests using pytest:
```
uv run pytest
```
