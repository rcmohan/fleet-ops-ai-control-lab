import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fleetops_runtime import build_app  # noqa: E402
from fleetops_runtime.loader import load_service  # noqa: E402


def main() -> None:
    for contract_file in sorted((ROOT / "services").glob("*/contract.py")):
        service = load_service(contract_file.parent, ROOT / "database")
        output = contract_file.parent / "openapi.json"
        # Building the app does not connect to a database; only the schema is generated.
        spec = build_app(service.contract, service.handlers).openapi()
        output.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
