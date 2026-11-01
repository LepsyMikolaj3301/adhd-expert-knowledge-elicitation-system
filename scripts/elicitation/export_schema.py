"""Write the ElicitationDocument JSON Schema to data/schemas/elicitation_document.schema.json.

Usage: python scripts/elicitation/export_schema.py
"""

import json
from pathlib import Path

from app.elicitation.schema import ElicitationDocument

OUT = Path(__file__).resolve().parents[2] / "data" / "schemas" / "elicitation_document.schema.json"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    schema = ElicitationDocument.model_json_schema()
    OUT.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(OUT.parent.parent.parent)}")


if __name__ == "__main__":
    main()
