#!/usr/bin/env python3
"""
new_report.py — scaffold a new report folder.

Usage:
    PYTHONPATH=$PWD python3 scripts/new_report.py <report_name>

Creates reports/<report_name>/ with the standard shape so a fresh session can
open it and know exactly what to build. See docs/CONTRIBUTING.md.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _files(name: str, title: str) -> dict:
    return {
        "AGENTS.md": f"""# AGENTS.md — {title}

A report in the WHA platform. Reads the shared SLX cache (read-only), produces an
output file. **Run all commands from the repo root.**

## Commands
```bash
PYTHONPATH=$PWD python3 -m pytest tests/   # from repo root
```

## Rules (see ../../AGENTS.md + docs/CONTRIBUTING.md)
- Get data via `hub.load_data(period)` — never call SLX or touch `src/`.
- Period is an input: `from src.config.period import parse_period`. FY = Oct→Sep.
- Pin definitions in SPEC.md before coding. A number is done when its gate passes.
- TDD: failing test first.

## Build order
Read SPEC.md → ROADMAP.md, implement `engine.py` (`name()`, `run(hub, params)` per
`src/base/report.py`), test, wire into the app.
""",
        "PRD.md": f"""# PRD — {title}

- **Audience:** <who reads this report>
- **Question it answers:** <what decision it supports>
- **Success criteria:** <what "correct + useful" means>
- **Non-goals:** <what this report deliberately does NOT do>
""",
        "SPEC.md": f"""# SPEC — {title}

> Pin every number from a PRIMARY source / stakeholder before coding.

## Metrics
| Metric | Definition | SLX source | Calculation |
|---|---|---|---|
| <name> | <what it means> | <entity/field> | <formula> |

## Output
<sheets, layout, key cells>

## Verification gates (a number is done only when its gate passes on a fresh run)
| Gate | Our output vs ground truth | Pass criteria |
|---|---|---|
| <gate> | <which truth file> | <tolerance> |
""",
        "ROADMAP.md": f"""# ROADMAP — {title}

Phased build. ✅ done · ⏳ partial · ☐ not started.

1. ☐ Data — confirm SLX fields + cache shape (DATA_ACCESS.md)
2. ☐ Logic — `engine.py` calculations (TDD)
3. ☐ Output — writer / template
4. ☐ Verify — run the SPEC gates against ground truth
5. ☐ Wire into the app
""",
        "memory.md": f"""# memory — {title}

Session memory for this report: key decisions, gotchas, terminology. Append as you go.
""",
        "engine.py": f'''"""
engine.py — {title} report logic.

Implements the BaseReport contract (src/base/report.py).
"""
from typing import Any, Dict

from src.base.report import ReportResult
from src.config.period import parse_period


class Report:
    def name(self) -> str:
        return "{name}"

    def run(self, hub: Any, params: Dict[str, Any]) -> ReportResult:
        period = parse_period(params["period"])
        data = hub.load_data(period.period)   # read-only cache
        # TODO: compute metrics from `data`, write the output file.
        raise NotImplementedError("build per SPEC.md / ROADMAP.md")
''',
        "tests/test_smoke.py": f'''"""Smoke test for {title}. Replace with real TDD tests."""
from reports.{name}.engine import Report


def test_report_has_name():
    assert Report().name() == "{name}"
''',
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python3 scripts/new_report.py <report_name>", file=sys.stderr)
        return 2
    name = sys.argv[1].strip().lower().replace("-", "_").replace(" ", "_")
    title = name.replace("_", " ").title()
    base = ROOT / "reports" / name
    if base.exists():
        print(f"refusing to overwrite existing {base}", file=sys.stderr)
        return 1

    (base / "tests").mkdir(parents=True)
    (base / "__init__.py").write_text("")
    (base / "tests" / "__init__.py").write_text("")
    for rel, content in _files(name, title).items():
        (base / rel).write_text(content)

    print(f"Scaffolded reports/{name}/")
    print("Next: fill SPEC.md (definitions + gates) first, then build per ROADMAP.md.")
    print("See docs/CONTRIBUTING.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
