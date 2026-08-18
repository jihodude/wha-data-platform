#!/usr/bin/env python3
"""push_durable_inputs.py — mirror the build's local-only durable inputs
to the SharePoint hub so a fresh cloud instance can hydrate them.

Found by the 8/8 D1 cloud-vs-checkpoint diff: 259 drops cells diverged and
2,018 drop rows vanished because `data/raw/crystal` (the manifested Crystal
export archive — "the archived file is the receipt") and the drops-hygiene
cache exist only on this Mac. SharePoint is the platform's durable truth;
receipts belong there.

Pushes under  Reports/Membership Performance Report/Data/durable/ :
  crystal/<period>/<file>       — the archive, verbatim
  drops_hygiene_FY<year>.json   — hygiene cache
  index.json                    — file list the runner's hydration reads

Idempotent: re-running re-pushes everything (small: ~3 MB).
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = "Reports/Membership Performance Report/Data/durable"


def main() -> int:
    from src.hub.datahub import DataHub
    hub = DataHub.connect(require_sharepoint=False)
    if getattr(hub, "_sp", None) is None:
        print("⛔ SharePoint not connected"); return 1

    index = []
    crystal = ROOT / "data/raw/crystal"
    for f in sorted(crystal.rglob("*")):
        if f.is_file():
            rel = f"crystal/{f.relative_to(crystal)}"
            hub.write_hub_file(f"{BASE}/{rel}", f.read_bytes())
            index.append({"rel": rel, "dst": f"data/raw/crystal/{f.relative_to(crystal)}"})
            print("  ↑", rel)
    for f in sorted((ROOT / "data/cache").glob("drops_hygiene_FY*.json")):
        rel = f.name
        hub.write_hub_file(f"{BASE}/{rel}", f.read_bytes())
        index.append({"rel": rel, "dst": f"data/cache/{f.name}"})
        print("  ↑", rel)
    hub.write_hub_file(f"{BASE}/index.json", json.dumps(
        {"pushed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
         "files": index}, indent=1).encode())
    print(f"✓ durable index: {len(index)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
