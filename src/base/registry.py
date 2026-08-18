"""
registry.py — report-node discovery (reconstruction P6).

The console and scheduler resolve report runners through here instead of
hardcoding paths. A report node is any directory under reports/ containing an
__init__.py; it is runnable when it has a runner.py.

Keep this dumb and filesystem-based: no imports of report code at discovery
time (importing a report module can drag in heavy deps or side effects — the
console only needs paths to hand to subprocess).
"""
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"


@dataclass(frozen=True)
class ReportNode:
    name: str                  # directory name, e.g. "membership_performance_tracker"
    dir: Path
    runner: Optional[Path]     # reports/<name>/runner.py if present, else None
    has_engine: bool           # reports/<name>/engine.py present (BaseReport impl)


def available_reports() -> List[ReportNode]:
    """Every report node under reports/, sorted by name."""
    nodes = []
    if not REPORTS_DIR.exists():
        return nodes
    for d in sorted(REPORTS_DIR.iterdir()):
        if not d.is_dir() or not (d / "__init__.py").exists():
            continue
        runner = d / "runner.py"
        nodes.append(ReportNode(
            name=d.name,
            dir=d,
            runner=runner if runner.exists() else None,
            has_engine=(d / "engine.py").exists(),
        ))
    return nodes


def runner_path(name: str) -> Path:
    """Path to a report's runner.py; KeyError if the node or runner is absent."""
    for node in available_reports():
        if node.name == name:
            if node.runner is None:
                raise KeyError(f"report '{name}' has no runner.py yet")
            return node.runner
    raise KeyError(f"no report node named '{name}' under {REPORTS_DIR}")
