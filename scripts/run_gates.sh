#!/bin/bash
# run_gates.sh — the full accuracy gate battery, one command. Run after any pull.
# (Layer-2 seed: this becomes the automated post-pull verification ritual.)
cd "$(dirname "$0")/.." || exit 1
echo "════ GATE: PENETRATION vs CRM ════"
python3 scripts/final_verdict.py 2>&1 | grep -vE "NotOpenSSL|warn"
echo "════ GATE: RETENTION (current cohort) vs AdjustedRetention export ════"
python3 scripts/retention_gate.py 2>&1 | grep -vE "NotOpenSSL|warn"
echo "════ GATE: DROPS vs DroppedMembersHospitality export ════"
python3 scripts/drops_gate.py 2>&1 | grep -vE "NotOpenSSL|warn"
echo "════ WIRING: sheet formulas point at the right territory/month ════"
python3 scripts/wiring_check.py 2>&1 | grep -vE "NotOpenSSL|warn"
echo "════ CONSISTENCY: cache ↔ rendered sheet ════"
python3 scripts/consistency_check.py 2>&1 | grep -vE "NotOpenSSL|warn"
echo "════ RECALC: zero formula errors ════"
python3 scripts/recalc_scan.py 2>&1 | grep -vE "NotOpenSSL|warn"
echo "════ NOTE ════"
echo "New-sales gate: compare cache revenue Jun vs the NewMemberSales PDF (paid drift expected)."
echo "References dated 7/13-7/14 — refresh CRM exports monthly before judging."
