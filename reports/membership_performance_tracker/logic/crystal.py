"""crystal.py — the MPR's Crystal-export ingestion layer.

THE PIVOT (2026-07-27, Jiho): the MPR's numbers ARE the numbers the org's own
Crystal reports print. Jennifer built her editions from these reports; the
contract is to do that automatically. So this module fetches the scheduled
exports and the parsers transcribe them — no composition, no divergence
registry, no "our number is defensibly better" conversations.

HOW EXPORTS REACH US: every Crystal report run in the CRM is archived as an
SLX attachment, readable over the same basic-auth SData surface as everything
else, at the SYSTEM contract:

    GET /sdata/slx/system/-/attachments?where=fileName like 'Prefix%'
    GET /sdata/slx/system/-/attachments('<key>')/file      → the bytes

Proven for the MPR 2026-07-27: DroppedMembersByType fetched by API came back
byte-identical to the copy downloaded by hand.

WHAT IS NOT AUTOMATED: firing the reports. Programmatic execution
(/sdata/$app/scheduling/-/ + CrystalReportsJob) accepts jobs but every run
dies at "Initialization" — the Job Service host lacks working Crystal
components (an IT/vendor fix, not ours). Schedules created in the CRM's own
wizard DO run server-side, so a human sets the schedules once and this module
picks up whatever they produce.

DELIBERATELY INDEPENDENT of reports/dues_analysis/logic/slx_reports.py, which
solves the same problem for that report. Jiho's direction: develop the two
independently, merge into the shared platform once both are validated. Do not
cross-import; when they merge, this file and that one collapse into one
src/slx module.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from urllib.parse import quote

# Cache-facing key → (catalog name as it appears in the CRM, filename prefix).
# The catalog name is what a human schedules; the prefix is what SLX stamps
# onto the archived export. Both are recorded so a missing report can be
# reported in the words the person setting up the schedule will see.
REPORTS: Dict[str, tuple] = {
    "new_member_sales":  ("New Member Sales Report", "NewMemberSalesReport"),
    "billables":         ("Billables By Territory Summary By Bm", "BillablesByTerritorySummaryByBm"),
    "retention":         ("Adjusted Retention SW Multiple Bill Months Exportable",
                          "AdjustedRetentionSwMultipleBillMonthsExportable"),
    "drops_hospitality": ("Dropped Members - Hospitality", "DroppedMembersHospitality"),
    "drops_by_type":     ("Dropped Members By Type", "DroppedMembersByType"),
    "drops_allied":      ("Dropped Allied Report", "DroppedAlliedReport"),
    # Exact tokens matter here: staff also run the non-Detail variants
    # (Hannah's PenetrationRestaurantCountbyLocation), which carry different
    # columns. Matching loosely would swap one for the other silently.
    "pen_restaurant":    ("Penetration Restaurant Count By Location - Detail",
                          "PenetrationRestaurantCountByLocationDetail"),
    "pen_lodging":       ("Penetration Lodging County By Location - Detail",
                          "PenetrationLodgingCountyByLocationDetail"),
    "pen_rooms":         ("Penetration Lodging Count of Rooms", "PenetrationLodgingCountofRooms"),
    # The billables source of record: its statewide total (2,143 on 2026-07-27)
    # is EXACTLY Jennifer's published June hospitality billables figure, and its
    # FTE bands give the Target/Non-Target split directly.
    "billables_fte":     ("Active Billables By Ac And Fte", "ActiveBillablesByAcAndFte"),
}

ATTACHMENT_ENTITY = "attachments"
ATTACHMENT_SELECT = "fileName,description,fileSize,createDate,fileExists,documentType"

# Machine-readable formats only, best first. A PDF of the same report is
# useless to the parsers however new it is (the rooms report's only archived
# runs were PDFs — that is why format matters when scheduling).
PARSABLE_EXTS = ("xls", "csv", "xlsx")

# SLX stamps exports two ways, both live-observed:
#   interactive (person clicks Export): <Report>_<user>_2026_07_26_0921.xls
#   scheduled   (Crystal job runs):     <Report>_<user>_202608_01_0930.xls
# The scheduled form drops the separator after the year. A pattern that only
# matched the interactive form would ignore every scheduled run and keep
# serving an old file forever, silently. Never narrow this.
_STAMP_RE = re.compile(
    r"^(?P<report>[A-Za-z0-9]+)_(?P<user>[^_]+)_"
    r"(?P<y>\d{4})_?(?P<m>\d{2})_(?P<d>\d{2})_(?P<hm>\d{4})\.(?P<ext>\w+)$")

# One bounded page: we want the newest run, never the multi-thousand-row
# history. It also dodges a live failure — the attachments entity rejects the
# Id-cursor pagination the platform client uses everywhere else.
EXPORT_PAGE = 50

ARCHIVE_ROOT = Path("data/raw/crystal")


class MissingExports(RuntimeError):
    """Raised when a required report has no usable run for the period.

    `missing` maps report key → a reason that distinguishes the two failures,
    because the human fix differs: NOT FOUND means no schedule was ever
    created; STALE means a schedule existed and stopped firing (the more
    dangerous case — an old export sits in the archive forever and would be
    served silently). Both name the CRM report so the message reads as a
    to-do list for whoever owns the schedules.
    """

    def __init__(self, missing: Dict[str, str], period: str):
        self.missing = missing
        self.period = period
        listed = "\n  ".join(f"{k}: {why}" for k, why in sorted(missing.items()))
        super().__init__(
            f"{period}: {len(missing)} required Crystal export(s) unusable. Schedule or "
            f"re-run them in the CRM (Excel format; run-to date far-future and later in "
            f"the day than the fire time):\n  {listed}")


@dataclass(frozen=True)
class ReportExport:
    key: str
    file_name: str
    run_date: date
    user: str
    ext: str
    size: int


def system_view(client):
    """The same authenticated client retargeted at the SYSTEM contract.

    Attachments live at /sdata/slx/system/-/; the dynamic feed the platform
    client defaults to returns 404 for them. A shallow copy keeps the session
    and leaves the caller's client untouched.
    """
    import copy

    base = getattr(client, "base_url", "") or ""
    if "/system/-/" in base:
        return client
    view = copy.copy(client)
    view.base_url = re.sub(r"/(dynamic|gcrm|metadata|proxy)/-/$", "/system/-/", base) or base
    return view


def parse_export_stamp(file_name: str):
    """(run_date, user, ext, report_token) from the SLX naming convention.

    The report token is the leading name-without-spaces; callers match it
    exactly so a narrower variant of the same report can never be mistaken
    for the full one.
    """
    m = _STAMP_RE.match(file_name or "")
    if not m:
        return None
    try:
        run_date = date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
    except ValueError:
        return None
    return run_date, m.group("user"), m.group("ext").lower(), m.group("report")


def list_exports(client, prefix: str, limit: int = EXPORT_PAGE):
    """Archived exports of one report, newest first. Purged rows are dropped."""
    params = (f"count={limit}"
              f"&where={quote(f'fileName like ' + chr(39) + prefix + '%' + chr(39), safe=chr(39) + '% ')}"
              f"&select={quote(ATTACHMENT_SELECT, safe=',')}"
              f"&orderby=createDate desc")
    rows = system_view(client)._get(ATTACHMENT_ENTITY, params).get("$resources", [])
    out = []
    for r in rows:
        name = r.get("fileName") or ""
        stamp = parse_export_stamp(name)
        if not stamp or r.get("fileExists") is False:
            continue
        run_date, user, ext, report_token = stamp
        # The report token must match EXACTLY, not merely start with the
        # prefix. Two reasons, both live: the server-side `where` filter can
        # be mis-escaped or ignored, and staff run narrower variants beside
        # the full report (DroppedMembersHospitalityBM8 next to
        # DroppedMembersHospitality). Either way a startswith() match feeds
        # one report's bytes to another report's parser — a plausible file
        # and a badly wrong number, with nothing raising.
        if report_token.lower() != prefix.lower():
            continue
        out.append(ReportExport(
            key=r.get("$key") or r.get("id") or "",
            file_name=r["fileName"],
            run_date=run_date,
            user=user,
            ext=ext,
            size=int(r.get("fileSize") or 0),
        ))
    out.sort(key=lambda e: (e.run_date, e.file_name), reverse=True)
    return out


def latest_export(client, prefix: str, *, exts: Sequence[str] = PARSABLE_EXTS,
                  since: Optional[date] = None) -> Optional[ReportExport]:
    """Newest parsable export, optionally no older than `since`.

    Pass the period's first day as `since` so a stale export can never be
    mistaken for this month's run.
    """
    for e in list_exports(client, prefix):
        if e.ext not in exts:
            continue
        if since and e.run_date < since:
            continue
        return e
    return None


def download_export(client, export: ReportExport) -> bytes:
    """The export's bytes, refusing a short read.

    A truncated workbook parses to fewer rows, which would undercount without
    any error — so a partial download must raise, never return.
    """
    data = system_view(client)._get_bytes(f"{ATTACHMENT_ENTITY}('{export.key}')/file")
    if export.size and len(data) < export.size:
        raise ValueError(
            f"{export.file_name}: truncated download — got {len(data)} bytes, attachment "
            f"size is {export.size}. Refusing to parse a partial export. Retry the fetch.")
    return data


def _period_start(period: str) -> date:
    year, month = (int(p) for p in period.split("-")[:2])
    return date(year, month, 1)


def archive_export(period: str, key: str, export: ReportExport, data: bytes,
                   root: Path = ARCHIVE_ROOT) -> Path:
    """Write the export verbatim under the period and record its provenance.

    The archived file is the receipt: it is the report the org would have
    opened. The manifest records what it is, when it ran and its hash, so a
    number can always be traced to a file rather than to an argument.
    """
    folder = Path(root) / period
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / export.file_name
    path.write_bytes(data)

    manifest_path = folder / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    manifest[key] = {
        "report": REPORTS.get(key, (key, ""))[0],
        "file_name": export.file_name,
        "run_date": export.run_date.isoformat(),
        "run_by": export.user,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return path


def fetch_period(client, period: str, *, root: Path = ARCHIVE_ROOT,
                 required: Optional[Sequence[str]] = None,
                 min_run_date: Optional[date] = None) -> Dict[str, Path]:
    """Fetch and archive every required export for a period.

    Always takes the NEWEST run and requires it to be recent enough:
    `min_run_date` defaults to the period's first day, and a caller on a
    nightly cadence passes the date it expects (e.g. this morning) so
    yesterday's file cannot pass as today's. Anything older fails the run and
    is reported as STALE, naming the last run that does exist.

    Returns {report key: archived path}.
    """
    keys = list(required) if required is not None else list(REPORTS)
    floor = min_run_date or _period_start(period)

    found, missing = {}, {}
    for key in keys:
        catalog_name, prefix = REPORTS[key]
        export = latest_export(client, prefix, since=floor)
        if export is None:
            # Separate "never scheduled" from "schedule stopped firing" by
            # looking at what IS archived, ignoring the freshness floor.
            newest_any = latest_export(client, prefix)
            if newest_any is None:
                missing[key] = (f"NOT FOUND — no parsable export of “{catalog_name}” exists. "
                                f"Create the schedule (Excel format).")
            else:
                missing[key] = (f"STALE — newest run of “{catalog_name}” is "
                                f"{newest_any.run_date.isoformat()}, need {floor.isoformat()} "
                                f"or later. The schedule likely stopped firing.")
            continue
        found[key] = export

    if missing:
        raise MissingExports(missing, period)

    out = {}
    for key, export in found.items():
        data = download_export(client, export)
        out[key] = archive_export(period, key, export, data, root=root)
    return out


# ---------------------------------------------------------------------------
# Reading a schedule's own date window
# ---------------------------------------------------------------------------
# The drops exports carry a bill month and NO date, so nothing in the file says
# which fiscal year a row belongs to. What DOES say it is the StatusDate range
# the schedule was created with — and that range is readable over the same API:
#
#   triggers('<key>') → parameters[ReportParameters][0].currentValues[0]
#                       .rangeDateValue = "2025-10-01T07:00:00Z;2030-12-31T…"
#
# So the annual "move the parameter every October" step does not have to live
# in someone's memory. The program reads what the CRM is actually scheduled to
# do and FLAGS a drops grid whose window spans more than the fiscal year being
# reported — see `check_drops_window`. It does not refuse to compile: that was
# the written intent, but it was never wired, and turning it on would hard-stop
# every build from Oct 1 2026 (the live windows begin 2025-10-01) with a remedy
# only a CRM admin can apply. Ruled to a flag 2026-08-11 (Jiho).
SCHEDULING_PATH = "/sdata/$app/scheduling/-/"
_RANGE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})T[^;]*;(\d{4})-(\d{2})-(\d{2})")


def scheduling_view(client):
    """The same authenticated client retargeted at the scheduling service."""
    import copy

    view = copy.copy(client)
    view.base_url = re.sub(r"/sdata/.*$", SCHEDULING_PATH, getattr(client, "base_url", "") or "")
    return view


def read_schedule_windows(client) -> Dict[str, tuple]:
    """{schedule name: (start_date, end_date)} for every live trigger with a range."""
    view = scheduling_view(client)
    out: Dict[str, tuple] = {}
    for row in view._get("triggers", "count=50").get("$resources", []):
        full = view._get(f"triggers('{row['$key']}')", "")
        params = {p.get("name"): p.get("value") for p in (full.get("parameters") or [])}
        name = str(params.get("ScheduleName") or "")
        raw = params.get("ReportParameters")
        if not name or not raw:
            continue
        m = _RANGE_RE.search(str(raw))
        if m:
            out[name] = (date(*(int(g) for g in m.groups()[:3])),
                         date(*(int(g) for g in m.groups()[3:])))
    return out


DROPS_SCHEDULE_NAMES = ("Dropped Members - Hospitality",
                        "Dropped Members By Type",
                        "Dropped Allied Report")

# Flag family for the window check. RULED 2026-08-11 (Jiho): this reports, it
# does not refuse. See `check_drops_window`.
DROPS_WINDOW_FLAG = "drops_schedule_window"


def check_drops_window(client, fy_start: int,
                       schedule_names: Sequence[str] = DROPS_SCHEDULE_NAMES
                       ) -> List[str]:
    """Every reason the drops schedules are not scoped to this fiscal year.

    Returns problems; NEVER raises. RULED 2026-08-11 (Jiho) after the overnight
    review found `assert_drops_window_matches_fy` had zero production callers
    while the comment above it claimed the program refuses to compile. Wiring
    the assert would hard-refuse every build from Oct 1 2026 — the live windows
    start 2025-10-01 — on a date after the handoff, with a remedy that needs CRM
    access. So the annual "move the StatusDate range every October" obligation
    goes on the flags tab, where the operator can see and act on it, and the
    report still compiles.

    Scope note: since the 7/31 event axis a DATED row carries its own year, and
    `crystal_feed._file_month` now rejects dates outside the reported FY on both
    edges. What a too-wide window still endangers is the DATELESS rows, which
    fall back to the bill month and genuinely cannot be told apart across years.
    """
    try:
        windows = read_schedule_windows(client)
    except Exception as exc:                       # the nightly must survive it
        return [f"drops schedule windows could not be read from the CRM "
                f"({type(exc).__name__}: {exc}) — the fiscal-year scope of the "
                f"drops exports is unverified for this run"]
    fy_begin = date(fy_start, 10, 1)
    problems = []
    for name in schedule_names:
        window = windows.get(name)
        if window is None:
            problems.append(f"{name}: no live schedule found")
        elif window[0] != fy_begin:
            problems.append(f"{name}: window starts {window[0]}, expected {fy_begin}")
    return problems


def assert_drops_window_matches_fy(client, fy_start: int,
                                   schedule_names: Sequence[str] = DROPS_SCHEDULE_NAMES
                                   ) -> None:
    """Refuse to compile drops when a schedule's window is not this fiscal year.

    A drops row cannot say which year it belongs to, so the window IS the year.
    Once the window starts before the fiscal year being reported, the export
    holds more than one year's drops and they cannot be told apart — the grid
    would silently stack two years in twelve cells.

    NOT WIRED INTO THE PIPELINE, deliberately (Jiho, 2026-08-11): the shipped
    behaviour is the reporting `check_drops_window` above. Kept for whoever
    later wants the hard gate; raising is a strictly stronger response to the
    same evidence.
    """
    problems = check_drops_window(client, fy_start, schedule_names)
    fy_begin = date(fy_start, 10, 1)
    if problems:
        raise MissingExports.__mro__[1](          # RuntimeError
            f"Drops schedules are not scoped to FY{fy_start}-{str(fy_start + 1)[2:]}: "
            + "; ".join(problems)
            + f". Set each report's StatusDate range to begin {fy_begin} — until then "
              f"the export spans more than one fiscal year and its rows carry no date "
              f"to separate them.")
