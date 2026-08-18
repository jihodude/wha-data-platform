"""Ruling 2026-08-06 (Jiho, dress rehearsal): "a fee should be excluded
from retention or any other metric — they did not pay their actual dues,
so it's not retained." Three consequences, each anchored to a live case:

1. ARTIFACT: fee == gross == dues_level means the $key-collapse landed the
   whole payment on a fee line of the DUES BILL ITSELF (Wapato Point,
   Kemper, Slumber Spokane — SLX shows one genuine WRA dues invoice each).
   The fee attribution is ignored: dollars restored, member stays counted.
2. GENUINE FEE-ONLY: a paid invoice that is entirely fee and NOT the dues
   bill (Smokin' Pete's $20 vs level $730) retains nothing and the member
   is NOT counted — fee money is not renewal money.
3. EPSILON: 710 − 473.33 − 236.67 leaves 2.84e-14, which "> 0" read as
   paid (Notable Restaurant Group — a write-off cycle counted retained).
   Cent-tolerance everywhere: count and dollars must tell one story.
"""
from reports.membership_performance_tracker.logic.retention import (
    _member_retained, retained_dollars_as_of)


def _inv(total, fee, balance=0.0, level=None, adj=0.0):
    return {"balance": balance, "invoice_total": total,
            "invoice_date": "/Date(1764547200000)/", "invoice_number": "X1",
            "adjustments": adj, "dues_level": level, "fee": fee}


def test_fee_swallowing_the_dues_bill_is_an_artifact():
    rows = [_inv(800.0, 800.0, level=800.0)]          # Wapato Point, literal
    ask, ret = retained_dollars_as_of(rows, None, None)
    assert (ask, ret) == (800.0, 800.0)
    assert _member_retained(rows) is True


def test_genuine_fee_only_payment_is_not_retention():
    rows = [_inv(20.0, 20.0, level=730.0)]            # Smokin' Pete's, literal
    ask, ret = retained_dollars_as_of(rows, None, None)
    assert ret == 0.0
    assert _member_retained(rows) is False


def test_float_crumb_is_not_a_payment():
    # Notable Restaurant Group, literal: billed 710, AD -473.33, owes 236.67
    rows = [_inv(710.0, None, balance=236.67, level=730.0, adj=-473.33)]
    assert _member_retained(rows) is False
    _ask, ret = retained_dollars_as_of(rows, None, None)
    assert ret == 0.0


def test_embedded_fee_bill_unchanged():
    # BGP class: fee rides INSIDE a bigger dues bill — normal fees-out.
    rows = [_inv(2695.0, 260.0, level=2435.0)]
    ask, ret = retained_dollars_as_of(rows, None, None)
    assert (ask, ret) == (2435.0, 2435.0)
    assert _member_retained(rows) is True
