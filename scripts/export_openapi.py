import importlib.util
import json
from pathlib import Path

from fleetops_runtime import build_app


ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "services"


def load_contract(contract_file: Path):
    module_name = f"contract_{contract_file.parent.name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, contract_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {contract_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CONTRACT


def main() -> None:
    for contract_file in sorted(SERVICES.glob("*/contract.py")):
        contract = load_contract(contract_file)
        output = contract_file.parent / "openapi.json"
        output.write_text(
            json.dumps(build_app(contract).openapi(), indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

