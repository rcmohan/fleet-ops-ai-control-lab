import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "services"
sys.path.insert(0, str(ROOT))

from fleetops_runtime import load_service_app


def main() -> None:
    for service_path in sorted(path for path in SERVICES.iterdir() if path.is_dir()):
        output = service_path / "openapi.json"
        output.write_text(
            json.dumps(load_service_app(service_path).openapi(), indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
