"""Amount Billed ($) on a drop = the last thing we actually billed them.

Live evidence, 2026-07-30 (all four verified against SLX directly):

  · Larry Gargett (A6UJ9A000RPQ): dues bill +690 on 2023-11-01, CREDIT NOTE
    −690 on 2024-01-22. `_most_recent` had no sign filter, so the credit —
    being dated later — always won, and the published Data - Drops sheet
    showed a member whose drop LOST us −$690.
  · 59'er Diner: +340 and −340 on the SAME DAY (2013-06-24). The winner
    depended on server row order — nondeterministic output.
  · Sun Mountain Lodge (A6UJ9A002QMM): five clean dues invoices ending at
    $2,034 — but published at $15.50, because `_dues_level` ran FIRST and its
    product 'WHA Lodging Dues (51+)' has products.Price = 15.5, a PER-ROOM
    RATE. The "Price = the UI Dues Level" rule was verified on a restaurant
    (El Sombrero, flat 1070) and over-generalized: the catalog holds rate
    products (15.5, 5.5, 3.0, 2.5 — all lodging/alliance) alongside true flat
    levels as low as $155 ('Educational Dues Full') and $160 ('100,000 or
    less Dues'), so no price threshold can separate them. Only a real bill
    can.

Hence the rule under test: the last POSITIVE WRA dues invoice is the amount
billed; the product price speaks only when the member was never invoiced —
which is exactly the parent-billed-children case the old dues-level-first
ordering existed to protect (they have no invoices of their own, so they
still fall through to the product).
"""
from reports.membership_performance_tracker.logic.drops import (
    _amount_billed, _get_last_invoice_amount)


class _StubClient:
    """Answers dlInvoiceHistoryHeader with canned rows; products with a price."""

    def __init__(self, invoices=(), price=None):
        self._invoices = list(invoices)
        self._product_price_cache = {"PROD1": price}

    def _fetch_all(self, entity, **kw):
        if entity == "dlInvoiceHistoryHeader":
            return list(self._invoices)
        raise AssertionError(f"unexpected entity {entity}")


def _inv(net, date):
    return {"Net_invoice": net, "Invoice_Date": date}


D_2023 = "/Date(1698796800000)/"   # 2023-11-01
D_2024 = "/Date(1705881600000)/"   # 2024-01-22
D_TIE = "/Date(1372032000000)/"    # 2013-06-24


def test_credit_note_is_not_a_bill():
    """Gargett: the later credit note must lose to the actual bill."""
    client = _StubClient([_inv(690.0, D_2023), _inv(-690.0, D_2024)])
    assert _get_last_invoice_amount(client, "A") == 690.0


def test_same_day_reversal_is_deterministic():
    """59'er Diner: +340/−340 on one day must yield 340 in either row order."""
    a = _StubClient([_inv(340.0, D_TIE), _inv(-340.0, D_TIE)])
    b = _StubClient([_inv(-340.0, D_TIE), _inv(340.0, D_TIE)])
    assert _get_last_invoice_amount(a, "A") == 340.0
    assert _get_last_invoice_amount(b, "A") == 340.0


def test_all_credits_means_no_bill_found():
    client = _StubClient([_inv(-70.0, D_2024)])
    assert _get_last_invoice_amount(client, "A") is None


def test_actual_bill_beats_the_product_price():
    """Sun Mountain: $2,034 last bill wins over the 15.5 per-room rate."""
    client = _StubClient([_inv(2034.0, D_2023)], price=15.5)
    assert _amount_billed(client, "A", {"$key": "PROD1"}) == 2034.0


def test_never_invoiced_falls_back_to_dues_level():
    """Parent-billed children: no invoices of their own → the product speaks."""
    client = _StubClient([], price=1070.0)
    assert _amount_billed(client, "A", {"$key": "PROD1"}) == 1070.0


def test_nothing_known_stays_unknown():
    client = _StubClient([])
    assert _amount_billed(client, "A", None) is None
