# Working conventions — how to change a metric, and how to write about one

Not business rules (those are [`_SHARED.md`](_SHARED.md)) — these are the rules
about *working here*, gathered from AGENTS.md, THE-PLAN Part 7 and recorded
feedback. They exist because breaking each one cost something.

---

## Before changing a number

1. **Definitions are sourced, not guessed.** *"Most past failures were wrong
   DEFINITIONS, not wrong code."* Pin a metric's meaning with a primary source
   or a stakeholder before implementing. — AGENTS.md hard rule 6
2. **Where a definition is genuinely ambiguous, ask the membership administrator ONCE — do not infer
   it from numbers.** — THE-PLAN Phase 1
3. **Update the definition record and log the decision *before* the code**, not
   after.
4. **Never add a "ratified divergence."** A gap means the logic is wrong, the
   source is wrong, or the report is wrong. Find out which. — THE-PLAN rule 2
5. **Validate one month end-to-end before building the next layer.** The pivot
   built four layers on an unvalidated premise and all four had to stop. — rule 3

## Before saying a number is right

6. **"Tests pass" ≠ "numbers right."** A number is correct when it matches
   ground truth on a fresh run, not when the suite is green. — AGENTS.md rule 3
7. **"Parses correctly" ≠ "is correct."** Reproducing a file's own printed total
   proves the parser works, nothing more. **Say which one you mean.** — rule 4
8. **A green pipeline is not a working product. Open the workbook.** If a month
   shows members joining and $0 revenue, the run failed regardless of exit code.
   — rule 5
9. **State coverage honestly, per metric.** *"Green" means green against what is
   listed* — one bill month is not a year, and one spot-check is not a family.
   The 2026-07-21 honesty finding: revenue's external verification had been
   **one cell**.

## Operating rules

10. **One SLX session at a time** (credential collision). A parallel dues session
    shares this repo.
11. **Stage explicit paths in git — never `git add -A`.** Violated twice on
    2026-07-28; it swept the dues session's uncommitted work into MPR commits.
12. **A launched job is not a result. Read the log, not the process list.**
13. **Docs are maintained in the same change that makes them stale.** *"A stale
    doc poisons every future session."* — AGENTS.md rule 7. This whole folder
    exists because that rule was not kept.

---

## How to write for each audience

*From recorded feedback — these are corrections, not preferences.*

### For Jiho — the plain-words story FIRST, then the options

> *"You are thinking out loud, you aren't communicating."*

He is a developer dropped into a hospitality-association domain. Jargon — *comp
codes*, *house accounts*, *bill month* — reads as noise until it is anchored to
**people and money**.

**The order that works:** the human story (a named member, what they paid, what
happened) → where the number appears in the output → what each choice changes →
**then** options, with a recommendation.

**Never bury a consequence.** Lead with it.

Measured: on 2026-07-14 a decision prompt was dismissed **twice** until the same
issue was retold as a ground-up story — then decided instantly.

### For the membership administrator / the team — no analyst jargon in anything user-visible

Sidebar labels, page headers, button text, workbook titles and column names use
**natural business terms**, even at the cost of a more generic name. Internal
Python identifiers stay as they are.

*(Example: "drilldown" was renamed in user-visible strings; the function keeps
its name.)*

### Whoever inherits this

The SOP is written *"so a person who did NOT build the system can run it."* That
is the standard for handover docs — and the reason a stale rule in the SOP is
worse than a stale rule anywhere else.

---

## What the record says about this project's failure mode

Three separate documents reached the same conclusion independently:

| Source | Wording |
|---|---|
| `stakeholder-questions-report-1.md` (June) | *"the June demo blew up mostly because numbers were computed against **assumed** definitions instead of confirmed ones"* |
| `THE-PLAN` Part 1 (July) | *"We were comparing a COMPUTATION against a PHOTOGRAPH"* — each family answered by a source that could not answer it faithfully |
| AGENTS.md rule 6 | *"Most past failures were wrong **definitions**, not wrong code"* |

**Not one of them is about code quality.** Every large failure here has been a
definition or a source-pairing problem — which is exactly why the catalog holds
definitions and sources, and why contradictions are kept rather than tidied away.
