"""The run-order rule, stated in the output because it cannot be enforced.

Jen, 2026-07-30 (recorded):
  · retention must be run BEFORE ITD — "you can't run a retention report for
    bill month 2 right now and it will show you anything accurate. It will look
    100% because all the members are dropped";
  · billables and penetration run AFTER ITD (Sheryl runs it);
  · the whole sequence waits on Accounting's green light that payments are
    posted — "the second business day of the month… sometimes as late as the
    5th business day".

We cannot see the ITD date or Accounting's green light from SData, so this is
not enforceable. What IS enforceable is that the run never stays SILENT about
which assumption it is relying on — the failure mode Jiho named on the call
("that might break the numbers, 'cause right now it's just being ran every
first of the month").
"""
from datetime import date

from reports.membership_performance_tracker.logic.run_timing import timing_note


def test_close_run_before_accounting_is_likely_done_warns():
    """Running July's close on Aug 1 — Accounting posts through business day
    2-5, so payments may be missing and retention will read LOW."""
    note = timing_note(period="2026-07", today=date(2026, 8, 1))
    assert note["risk"] == "accounting-may-be-incomplete"
    assert "retention" in note["message"].lower()


def test_close_run_inside_the_normal_window_is_clean():
    """Aug 6 — past the 5th business day; the normal, expected run."""
    note = timing_note(period="2026-07", today=date(2026, 8, 6))
    assert note["risk"] is None


def test_running_a_month_long_after_close_warns_about_itd():
    """Re-running a closed month later is exactly Jen's 100% warning: ITD has
    since inactivated the non-payers."""
    note = timing_note(period="2026-03", today=date(2026, 7, 30))
    assert note["risk"] == "itd-has-run-retention-inflated"
    assert "100" in note["message"] or "ITD" in note["message"]


def test_reporting_the_month_currently_in_progress_is_provisional():
    """July reported during July — the cycle has not closed."""
    note = timing_note(period="2026-07", today=date(2026, 7, 30))
    assert note["risk"] == "period-still-open"


def test_billable_members_with_no_invoice_are_flagged():
    """Jen, 2026-07-30 [46:23], on an RRO conversion leaving an ACTIVE duplicate
    with no invoice: *"Unless it's a baby underneath the corporate, it should
    not. **That is a no-no. I'd like to see that.**"*

    She names the mechanism herself [45:51]: an RRO conversion "usually also
    creates an inactive… so there's an RRO for Joe's Hotel and then there's an
    active membership for Joe's Hotel." Live example: the two Four Points
    Bellingham records. Shannon's step 10 lists it in the exceptions queue.

    A member carrying a dues product but holding no invoice all year is either
    that duplicate, or the Four Points class (billed by Jen, invoiced by
    nobody). Either way a human must see it.
    """
    from reports.membership_performance_tracker.logic.run_timing import (
        billables_without_invoices)

    carriers = {"A1": "Snohomish", "A2": "Snohomish", "A3": "Pierce"}
    invoiced = {"A1", "A3"}
    names = {"A2": "Four Points by Sheraton Bellingham"}

    flags = billables_without_invoices(carriers, invoiced, names)

    assert len(flags) == 1
    assert flags[0]["name"] == "Four Points by Sheraton Bellingham"
    assert flags[0]["territory"] == "Snohomish"
    assert "no invoice" in flags[0]["why"].lower()
