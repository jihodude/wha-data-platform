"""
attribution.py — WHO gets credit for a sale (ratified 2026-07-15/16).

The seller lives in `AccountExtension.Originator` (UI: "Acct. Originator") —
verified 3/3 on cross-territory and admin-entered sales (Perch→gretchenf,
El Sombrero→tfarrell, My's Cove→gretchenf). CreateUser is the data-entry
CLERK, not the seller — never attribute by it. Jen's convention ("sellers
keep credit", 7/14): a sale shows in the SELLER's column even when the account
lives in another territory. Goals/%-to-goal key on these columns, so
territory-attribution would hand TMs credit for other people's work.
"""
from pathlib import Path
from typing import Dict, Iterable, Optional

from src.slx.client import fetch_by_id_batches

BATCH = 20

_seller_map_cache = None


def _load_seller_map() -> Dict[str, str]:
    """seller_user_to_territory from config/territory_map.yaml (7/16 fix:
    Originator holds PERSON user ids — tfarrell, gretchenf — a different id
    family from the territory SEAT users; pull #10 proved zero re-attribution
    without this map). Cached per process."""
    global _seller_map_cache
    if _seller_map_cache is None:
        import yaml
        cfg = Path(__file__).resolve().parents[3] / "config" / "territory_map.yaml"
        try:
            _seller_map_cache = (yaml.safe_load(cfg.read_text()) or {}).get(
                "seller_user_to_territory") or {}
        except Exception as e:
            # GOLD-PLATE (2026-07-17): seller_user_to_territory is REQUIRED for
            # correct seller-credit — a silent empty map mis-credits every
            # cross-territory sale to the account's own territory. Fail LOUD.
            raise RuntimeError(
                f"[attribution] seller-credit map load FAILED from {cfg}: {e} — "
                f"refusing to run with mis-credited attribution"
            ) from e
    return _seller_map_cache


def originator_territory_map(
    client,
    account_ids: Iterable[str],
    territory_user_map: Dict[str, str],
    fallback_territory: Optional[str] = None,
    request_delay: float = 0.15,
    seller_map: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """
    {account_id: seller's territory} via AccountExtension.Originator.

    Unmapped or missing originators fall back to `fallback_territory` (the
    account-manager's territory — the pre-7/16 behavior) and are surfaced
    LOUDLY so non-TM sellers never vanish silently.
    """
    ids = [a for a in account_ids if a]
    # Person-user (seller) ids + seat-user ids are disjoint families; the
    # lookup is their union so either id form resolves.
    lookup = {**(_load_seller_map() if seller_map is None else seller_map),
              **territory_user_map}
    out: Dict[str, str] = {}
    unmapped = []
    by_acct = {}
    for r in fetch_by_id_batches(
            client, "AccountExtension", ids, batch_size=BATCH,
            page_size=BATCH * 2, request_delay=request_delay):
        acct = r.get("Account")
        k = (acct or {}).get("$key") if isinstance(acct, dict) else None
        if k:
            by_acct[k] = (r.get("Originator") or "").strip()
    for a in ids:
        orig = by_acct.get(a, "")
        terr = lookup.get(orig)
        if terr:
            out[a] = terr
        else:
            out[a] = fallback_territory
            unmapped.append((a, orig or "<none>"))
    if unmapped:
        print(f"  [attribution] {len(unmapped)} enrollee(s) with non-TM/missing "
              f"Originator → credited to the account's own territory: "
              f"{unmapped[:5]}{'…' if len(unmapped) > 5 else ''}", flush=True)
    return out
