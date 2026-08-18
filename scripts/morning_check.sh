#!/bin/bash
# morning_check.sh — ONE command for the 7/14 pre-meeting hour. READ-ONLY.
# Runs all three evidence checks + the classifier, tolerates partial failure,
# and prints a plain-language decision summary at the end.
#
#   cd wha-data-platform && bash scripts/morning_check.sh
#
# Total ~15 min. Start it, go get coffee / skim the brief, read the summary.

cd "$(dirname "$0")/.." || exit 1
export PYTHONPATH="$PWD"
LOG="/tmp/morning_check_$(date +%H%M).log"
echo "=== MORNING CHECK $(date '+%H:%M:%S') — log: $LOG ===" | tee "$LOG"

run () {
  echo "" | tee -a "$LOG"
  echo "──────────────────────────────────────────────" | tee -a "$LOG"
  echo "▶ $1  ($2)" | tee -a "$LOG"
  echo "──────────────────────────────────────────────" | tee -a "$LOG"
  python3 -u "scripts/$1" 2>&1 | grep -vE "NotOpenSSLWarning|warnings.warn" | tee -a "$LOG"
  if [ "${PIPESTATUS[0]}" -ne 0 ]; then
    echo "⚠ $1 FAILED — keep going; partial evidence still counts." | tee -a "$LOG"
  fi
}

run fetch_hotel_rooms_check.py  "~2 min — where do the hotel room counts live?"
run fetch_rest_fte_check.py     "~8 min — where do the restaurant FTE bands live?"
run billables_rule_check.py     "~6 min — does the bill-month rule hit 2,132/161/34?"

echo "" | tee -a "$LOG"
echo "──────────────────────────────────────────────" | tee -a "$LOG"
echo "▶ classify_truth_attrs.py (offline, instant)"    | tee -a "$LOG"
echo "──────────────────────────────────────────────" | tee -a "$LOG"
python3 scripts/classify_truth_attrs.py 2>&1 | tail -25 | tee -a "$LOG"

cat <<'SUMMARY' | tee -a "$LOG"

══════════════════════════════════════════════════════════
HOW TO READ THE RESULTS (30 seconds)
══════════════════════════════════════════════════════════
1) ROOMS + FTE checks:
   • Mostly ">= 41" / "target_ok"  → the values EXIST per-account; our
     per-territory join was losing them. The prefer-non-null fix applied
     7/13 PM likely already covers it → the pull will capture them.
   • Mostly "rooms_null"/"fte_empty" or "no_*_row" → the CRM report reads
     a DIFFERENT field/table → ask Jennifer Q8; targeted fix after.

2) BILLABLES check:
   • Totals ≈ 2,132 / 161 / 34  → the bill-month rule is CONFIRMED and
     you can say in the meeting: "my billables now count exactly what
     your report counts — verified this morning."
   • Off by a lot → say "close, final alignment in progress" instead.

3) OPTIONAL — launch the corrected June pull so it runs DURING the
   meeting (~60 min; lands with billables rule + NRA bucket + 41-room
   line + join fix). Only if the checks above look good:

     MPR_PERIOD=2026-06 PYTHONPATH=$PWD nohup python3 \
       reports/membership_performance_tracker/runner.py \
       > /tmp/june_repull.log 2>&1 &

   Check later:  tail -5 /tmp/june_repull.log
══════════════════════════════════════════════════════════
SUMMARY
echo "done $(date '+%H:%M:%S')"
