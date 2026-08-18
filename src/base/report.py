"""
report.py — the plug-in contract every report implements.

A report is a self-contained module under reports/<name>/ that READS from the
shared platform (src/: slx, hub, config) and produces an output file. It never
modifies src/. The app discovers reports via this protocol.

Keep this tiny and stable — it's a contract many reports depend on.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Protocol, runtime_checkable


@dataclass
class ReportResult:
    """What a report run returns."""
    output_path: Path                       # the generated file
    period: str                             # "2026-03"
    warnings: list = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class BaseReport(Protocol):
    """Implement this in reports/<name>/ to be runnable by the platform.

    Reports get their data from a DataHub (read-only): `hub.load_data(period)`.
    They MUST NOT write to src/ or to another report's folder.
    """

    def name(self) -> str:
        """Stable identifier, e.g. 'membership_performance_tracker'."""
        ...

    def run(self, hub: Any, params: Dict[str, Any]) -> ReportResult:
        """Produce the report for params['period']; return a ReportResult."""
        ...
