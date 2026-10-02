import json
from pathlib import Path

_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"

output_schema = json.loads((_CONFIG_DIR / "output-schema.json").read_text())
labs_schema = json.loads((_CONFIG_DIR / "labs-schema.json").read_text())
meds_schema = json.loads((_CONFIG_DIR / "meds-schema.json").read_text())
