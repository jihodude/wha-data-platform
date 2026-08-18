"""crystal_banding.py — sort Crystal rows into Target / Non-Target.

THE ONE PLACE SData TOUCHES THE PIVOT, and it is deliberately narrow: Crystal
supplies every NUMBER on the report; SData supplies only an ATTRIBUTE that
decides which of two columns a row lands in. No figure here ever reaches a
cell.

WHY IT CANNOT BE CRYSTAL-ONLY (measured 2026-07-27, not assumed). Size lives
in the penetration Detail exports — real room counts for lodging, FTE bands
for restaurants — but keyed by SLX account ID, while every member export is
keyed by 7-digit member ID. Joining the two by NAME was tried and reconciles
only where the penetration universe reaches:

    Hotel 406/488 (83%) · Restaurant 534/773 (69%) · Corporate 17/565 (3%)
    Recreational / Catering / Concession / Non-Profit / Individual 0/147 (0%)

The zeros are not a bad join. Those business types are not in the penetration
reports at all (they cover restaurants over 10 FTE and lodging), so 565
Corporate members have no size anywhere in the report layer. No arrangement of
Crystal reports can band the whole membership.

THE BRIDGE. Crystal rows have no member-id we can join on — cMemberGens.
Membernum is empty database-wide — so rows are matched to their SLX account by
NAME within their own territory, which resolved 174/174 in the territory it was
measured on. See the comment on the bridge below for the evidence.

WHAT THIS MODULE DOES NOT DECIDE. The Target rule itself is already ratified
and implemented in `target.py` (hotels by rooms, everyone else by FTE band,
Allied → Non-Target). This module reuses `build_target_map` verbatim; it adds
only the member-ID bridge Crystal rows need, and the gates.

THE GATES (Jiho's rule: an SData-crafted figure that overlaps a Crystal figure
must reconcile exactly). `check_against_penetration` compares our Target
actives to the count the penetration report prints for itself. A mismatch
raises, because a banding drift would quietly move members between two columns
that both look plausible.
"""
import warnings
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from reports.membership_performance_tracker.logic import target as target_logic

# THE BRIDGE IS THE ACCOUNT NAME, and that is not a compromise — it is the
# only key that exists. Measured 2026-07-27:
#   * cMemberGens.Membernum is EMPTY database-wide (0 rows where it is
#     non-null), and our own cached drops detail carries 0 member ids in
#     2,628 rows. There is no member-id column in SLX to join on.
#   * Crystal's "Member Name" is ACCOUNT.ACCOUNT — literally the same column
#     SData returns as AccountName — so an exact name match inside a
#     territory resolved 174/174 (100%) of NorthCentral's retention members.
# Names are matched WITHIN a territory, never globally, so two same-named
# businesses in different territories cannot collide.


class BandingMismatch(RuntimeError):
    """Our banding disagrees with a Crystal report's own printed counts."""


@dataclass(frozen=True)
class BandedTotals:
    target: int = 0
    non_target: int = 0
    unknown: int = 0

    @property
    def total(self) -> int:
        return self.target + self.non_target + self.unknown


def normalize_name(name: str) -> str:
    """Fold the punctuation and spacing differences that mean nothing.

    Crystal and SData return the same underlying string, but comparing raw
    text still trips over "&" vs "and", stray commas and double spaces.
    """
    text = str(name or "").lower().replace("&", "and")
    for ch in "'’\"":
        text = text.replace(ch, "")      # deleted: Smitty's == Smittys
    for ch in ",.-/()":
        text = text.replace(ch, " ")     # spaced: separators, not letters
    return " ".join(text.split())


def build_name_bridge(client, account_manager_id: str) -> Dict[str, str]:
    """{normalized account name: account_id} for ONE territory.

    Per-territory on purpose: a global name index would let two same-named
    businesses in different territories claim each other's band.
    """
    records = client._fetch_all(
        "accounts",
        where=f"AccountManager.Id eq '{account_manager_id}'",
        select="Id,AccountName,Type,SubType",
        page_size=200,
    )
    bridge: Dict[str, str] = {}
    for r in records:
        name = normalize_name(r.get("AccountName"))
        account_id = r.get("$key") or r.get("Id")
        if name and account_id:
            bridge.setdefault(name, account_id)   # first wins; never overwritten
    return bridge


def band_member(name: str, bridge: Dict[str, str],
                target_map: Dict[str, str]) -> str:
    """Target / Non-Target / Unknown for a Crystal row, keyed by member name.

    Unknown is a real answer, not a failure: a member we cannot resolve, or
    whose size attributes are blank, must be visible as unbanded rather than
    quietly counted as Non-Target.
    """
    account_id = bridge.get(normalize_name(name))
    if not account_id:
        return target_logic.UNKNOWN
    return target_logic.classify(target_map, account_id)


def band_rows(rows: Iterable, bridge: Dict[str, str], target_map: Dict[str, str],
              *, id_attr: str = "name") -> Dict[str, List]:
    """Split parsed Crystal rows into {'Target': [...], 'Non-Target': [...], 'Unknown': [...]}."""
    out: Dict[str, List] = {target_logic.TARGET: [], target_logic.NON_TARGET: [],
                            target_logic.UNKNOWN: []}
    for row in rows:
        out[band_member(getattr(row, id_attr, ""), bridge, target_map)].append(row)
    return out


def totals(banded: Dict[str, List]) -> BandedTotals:
    return BandedTotals(
        target=len(banded.get(target_logic.TARGET, [])),
        non_target=len(banded.get(target_logic.NON_TARGET, [])),
        unknown=len(banded.get(target_logic.UNKNOWN, [])),
    )


def check_against_penetration(our_target_actives: Dict[str, int],
                              penetration_rows: Iterable,
                              *, tolerance: int = 0) -> None:
    """Gate: our Target actives must equal the penetration report's own counts.

    This is the cross-source rule — an SData-derived split that overlaps a
    Crystal figure has to reconcile with it. It already held exactly on
    2026-07-19 (TKP 56/56, NorthCentral 52/52), so any drift is new and worth
    failing a run over: banding errors move members between two columns that
    both look perfectly reasonable on the page.
    """
    theirs: Dict[str, int] = {}
    for row in penetration_rows:
        if getattr(row, "status", "") == "Active":
            theirs[row.territory] = theirs.get(row.territory, 0) + 1

    problems = []
    for territory, their_count in sorted(theirs.items()):
        ours = our_target_actives.get(territory)
        if ours is None:
            problems.append(f"{territory}: we produced no Target count; the report prints {their_count}")
        elif abs(ours - their_count) > tolerance:
            problems.append(f"{territory}: ours {ours} vs the report's {their_count}")
    if problems:
        raise BandingMismatch(
            "Target banding disagrees with the penetration report's own actives — "
            + "; ".join(problems[:6]))


def warn_on_unknowns(banded: Dict[str, List], label: str,
                     *, threshold: float = 0.02) -> None:
    """Announce unbanded members instead of absorbing them.

    A handful of Unknowns is normal (blank size attributes). A wave of them
    means the bridge or the target map broke, and since Unknown rows are
    excluded from both bands the report would simply come up short with no
    error anywhere.
    """
    counts = totals(banded)
    if counts.total and counts.unknown / counts.total > threshold:
        warnings.warn(
            f"[banding] {label}: {counts.unknown}/{counts.total} members could not be "
            f"banded ({counts.unknown / counts.total:.0%}). They are counted in NEITHER "
            f"band — check the member-id bridge and the target map before trusting "
            f"this run.")


def normalize_territory(territory: str) -> str:
    """Fold the spelling differences that mean nothing between the two sources.

    SData's drops detail writes "East King", "North King", "South King" and
    "Retro Program"; the Crystal exports and every scoreboard field write
    "EastKing", "NorthKing", "SouthKing". The (territory, name) pair key — the
    ONLY guard against two same-named members in different territories taking
    each other's band and flip date — therefore never matched for those, and
    177 of 331 live rows fell through to global first-match name matching.

    Found 2026-08-11 via Bob's Burgers & Brew: two distinct WRA members share
    that name in NorthCentral, and first-wins gave both rows the wrong member's
    flip date, publishing $2,775 in January instead of July.

    Spaces, slashes and hyphens are dropped so "Spokane/NE" also folds onto
    "SpokaneNE" and "Majors/NRA" onto "MajorsNRA".
    """
    text = str(territory or "").lower()
    for ch in (" ", "/", "-", "_"):
        text = text.replace(ch, "")
    return text


def normalize_wra(value) -> str:
    """WRA member numbers appear as '0056458' in SData's CustomerNo and
    sometimes unpadded in Crystal exports — compare without leading zeros."""
    return str(value or "").strip().lstrip("0")


def band_from_detail(drops_detail):
    """Build a Target/Non-Target callable from SData's own drops detail.

    Why this exists: the name-bridge bander (`build_name_bridge` +
    `build_target_map`) needs a live SLX client, so a `--from-cache` run could
    not band at all — every row read UNKNOWN, folded into Non-Target, and the
    report published "Target: 0" in silence (2026-07-28).

    SData's `drops_detail` already carries `is_target` per member, computed by
    the SAME target logic every other family uses, and it travels in the cache.
    So the band no longer depends on how the report is run.

    Measured against the live July export: 263 of 264 rows band from it (99.6%).
    The single miss is `Todd's Crab Cracker` — the ownerless account no
    territory-keyed query can reach (SOURCE-DATA-AUDIT 1.2).

    Matching is (territory, name) first, then name alone: Crystal and SData
    disagree about a member's territory more often than they agree (the pair
    resolves 43% on live data), but a name collision across territories is the
    riskier error, so the more specific key wins where it exists.

    Returns None when there is nothing to band from, so the overlay's GATE B
    keeps SData's split rather than publishing a fabricated one.
    """
    by_name, by_territory_name, by_wra = {}, {}, {}
    for row in drops_detail or []:
        flag = str(row.get("is_target") or "").strip().upper()
        if flag not in ("Y", "N"):
            continue          # never classified — not evidence of Non-Target
        band = target_logic.TARGET if flag == "Y" else target_logic.NON_TARGET
        # C3 (2026-08-12): the WRA number is the only key that separates two
        # same-named members in the SAME territory (Bob's Burgers & Brew ×2 in
        # NorthCentral — $2,775 published into the wrong month). Exact id
        # beats every name heuristic; absent on pre-C3 caches.
        wra = normalize_wra(row.get("wra"))
        if wra:
            by_wra.setdefault(wra, band)
        name = normalize_name(row.get("account_name"))
        if not name:
            continue
        by_name.setdefault(name, band)
        by_territory_name.setdefault(
            (normalize_territory(row.get("territory")), name), band)

    if not (by_name or by_wra):
        return None

    def band_row(row):
        mid = normalize_wra(getattr(row, "mid", ""))
        if mid and mid in by_wra:
            return by_wra[mid]
        name = normalize_name(getattr(row, "name", ""))
        territory = normalize_territory(getattr(row, "territory", ""))
        return (by_territory_name.get((territory, name))
                or by_name.get(name, target_logic.UNKNOWN))

    return band_row


def drop_dates_from_detail(drops_detail):
    """Flip-date lookup for Crystal drop rows, from SData's own drops detail.

    Same matching semantics as `band_from_detail` (which bands 263/264 live
    rows): (territory, name) first, then name alone. Exists for the event-axis
    filing (2026-07-31) — the export carries no year, the detail carries the
    real status-change date. member_id would be the cleaner key but is empty
    across the current detail (0 of 2,633 — noted in the audit).

    Returns a callable row → date-or-None; None when there is nothing to read.
    """
    from datetime import date as _d

    def _parse(s):
        try:
            y, m, dd = str(s)[:10].split("-")
            return _d(int(y), int(m), int(dd))
        except Exception:
            return None

    by_name, by_pair, by_wra = {}, {}, {}
    for row in drops_detail or []:
        when = _parse(row.get("drop_date"))
        if when is None:
            continue
        # C3: same WRA bridge as band_from_detail — the Bob's twins share
        # (territory, name), so only the id keeps their flip dates apart.
        wra = normalize_wra(row.get("wra"))
        if wra:
            by_wra.setdefault(wra, when)
        name = normalize_name(row.get("account_name"))
        if not name:
            continue
        by_name.setdefault(name, when)
        by_pair.setdefault((normalize_territory(row.get("territory")), name), when)

    if not (by_name or by_wra):
        return None

    def date_of(row):
        mid = normalize_wra(getattr(row, "mid", ""))
        if mid and mid in by_wra:
            return by_wra[mid]
        name = normalize_name(getattr(row, "name", ""))
        territory = normalize_territory(getattr(row, "territory", ""))
        return by_pair.get((territory, name)) or by_name.get(name)

    return date_of
