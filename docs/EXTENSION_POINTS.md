# Extension Points

Documented hooks where future devs can plug additional data sources or
behavior into the pipeline **without editing the engine**. Each entry lists
the contract, the merge rules, and a worked example.

Editing the engine is reserved for the main session. Extension points are how
report-folder sessions and external-data integrations stay decoupled from it.

---

## Penetration data — `PenetrationOverride`

**Location:** `src/logic/penetration_override.py`
**Used by:** `engine.ScoreboardEngine._query_penetration`
**Replaces:** the legacy CSV (`src/parsers/penetration.py`) and admin-xlsx
penetration-sheet ingestion paths, both removed.

### What it does

The default source of restaurant / lodging penetration counts is SLX, computed
by `billables.compute_penetration_by_segment`. An override can substitute
per-(territory, segment) counts AFTER the SLX pass, and the chosen source is
recorded in `data.penetration_source[territory][segment]` as either `"slx"` or
`"override:<adapter_name>"`.

### Contract

```python
from typing import Protocol, Optional

class PenetrationOverride(Protocol):
    def name(self) -> str: ...
    def overrides_for(self, territory: str) -> Optional[dict]: ...
```

`overrides_for(territory)` returns one of:

* `None` — defer to SLX entirely for this territory
* A partial dict — return only the segment you have data for; unspecified
  segments fall through to SLX
* A full dict — replace both segments

```python
# Full dict shape — same as compute_penetration_by_segment per-territory output
{
    "restaurant": {"active": 358, "market": 454},
    "lodging":    {"active": 22,  "market": 95},
}
```

### Merge rules (pinned by `tests/test_penetration_override.py`)

1. `None` override → every cell sourced `"slx"`, values unchanged
2. Override returns `None` for a territory → fall through to SLX
3. Override returns a segment dict → substitute that segment, mark source
4. Override returns `None` for a segment within a territory dict → that
   segment falls through to SLX (no half-substitutions)

### Wiring

```python
from src.logic.engine import ScoreboardEngine

engine = ScoreboardEngine(...)
data = engine.run(
    territory_map=territory_map,
    fiscal_year="2025-26",
    penetration_override=my_adapter,   # ← new parameter, defaults to None
)

# Per-territory provenance for the v4 mapper / audit:
data.penetration_source["Pierce"]  # → {"restaurant": "override:hannah_csv", "lodging": "slx"}
```

### Worked example — the previous analyst CSV adapter

The legacy ingestion path read the previous analyst's published penetration CSV
(`Penetration Report - Hospitality 3.3.csv`) directly into the model. To
re-enable that workflow without resurrecting the dead parser, ship an
adapter:

```python
# src/logic/overrides/hannah_csv.py
from pathlib import Path
from typing import Optional, Dict
import pandas as pd

class HannahCsvOverride:
    """
    Read the previous analyst's CSV and substitute her per-territory restaurant + lodging
    counts. The CSV stores active counts and the final %, but NOT the
    underlying market — we reconstruct market = round(active / pct) per row.
    """

    def __init__(self, csv_path: Path, territory_aliases: dict):
        self._table = self._parse(csv_path, territory_aliases)

    def name(self) -> str:
        return "hannah_csv"

    def overrides_for(self, territory: str) -> Optional[dict]:
        return self._table.get(territory)

    def _parse(self, csv_path: Path, aliases: dict) -> Dict[str, dict]:
        # Parse the CSV (Restaurants section rows 4-15, Lodging rows 21-32);
        # reconstruct market from active and pct; alias raw territory names
        # to canonical via territory_map.yaml.
        df = pd.read_csv(csv_path, header=None)
        out = {}
        # ... section-walking logic similar to the old src/parsers/penetration.py
        return out
```

Then register at engine call time:

```python
from src.logic.overrides.hannah_csv import HannahCsvOverride

override = HannahCsvOverride(Path("data/raw/Penetration_3.3.csv"), aliases)
data = engine.run(..., penetration_override=override)
```

### When NOT to write an override

* For per-territory **policy decisions** (e.g. "include Unknown-FTE accounts in
  the numerator") — those are calc choices that belong in
  `_count_target_locations` / `compute_penetration_by_segment`, not in an
  override. Adapters bring data, not policy.
* For temporary one-off corrections — use admin inputs for those (other
  fields), don't ship code.
* For changes that need to apply across ALL territories uniformly — that's an
  engine change, lift it to the main session.

### Sub-session guardrail

If you're working from `reports/<your_report>/`, you **may** write an override
adapter in your report folder and pass it through your runner. You **may not**
edit `src/logic/penetration_override.py`, `engine._query_penetration`, or the
model fields without raising the change with the main session.
