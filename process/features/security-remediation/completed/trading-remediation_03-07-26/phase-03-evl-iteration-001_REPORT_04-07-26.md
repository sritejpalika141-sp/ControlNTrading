---
name: report:phase-03-evl-iteration-001
description: "Phase 3 EVL cycle 1 — index.html tab-nav overflow gate failure"
date: 04-07-26
metadata:
  node_type: memory
  type: report
  feature: security-remediation
  phase: phase-03
---

# Phase 3 EVL Iteration 001

**Gate failed:** `index-mobile-usable` (plan's own exit-gate criterion: "No horizontal scroll / functional nav / usable tables on index.html at 375/390/768/1440px")

**Finding:** EVL's independent viewport re-check found `document.documentElement.scrollWidth` matches viewport width (looks clean), but `body.scrollWidth` is 500/522/827/1499px against viewports of 375/390/768/1440px — real overflow exists. Root cause: `#dashboardTabNav` (`.tab-nav`, styles.css:297, `display:flex; gap:4px`, no `overflow-x`/`flex-wrap`/shrink rule) overflows the viewport by ~136px at 375px. This predates Phase 3 and was not in Phase 3's edit set — but Phase 3's new `html{overflow-x:hidden}` rule (added to fix a different, unrelated overflow source) now silently clips this instead of leaving it as a scrollable (if ugly) page-level scrollbar. Net effect: some tabs (e.g. "History") became unreachable at mobile widths — a regression in usability terms, not a new bug introduced by edited code, but a masking side-effect of this phase's own fix.

**Fix:** Add `.tab-nav { overflow-x: auto; -webkit-overflow-scrolling: touch; }` to `styles.css` — same pattern already used for `.table-responsive`/`.symbol-tabs` elsewhere in this phase. Scoped to `styles.css`, already within Phase 3's declared Blast Radius. No `index.html` edit needed.

**Cycle:** 1 of 10 max (vc-autoresearch cap). Not a plateau, not a cap-hit — proceeding to fix + re-validate.

---

## Fix Applied + Re-validation (supplement, 04-07-26)

**Change:** `trading-app/static/styles.css` `.tab-nav` rule (line 297) — added:
```css
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
```
styles.css-only; matches the existing `.symbol-tabs`/`#signalsContainer.has-multiple-signals` overflow pattern in this file. No `index.html` / `admin.html` / `landing.html` edit. Within Phase 3 Blast Radius.

**Verification 1 — rule cleanliness:** `grep -n '\.tab-nav' styles.css` → single rule at line 297. No duplicate/conflicting `overflow-x` on `.tab-nav`.

**Verification 2 — live browser probe** (`npx --yes agent-browser`, `python3 -m http.server` rooted at `trading-app/`, index.html at 375/390/768/1440px):

| vw | `documentElement.scrollWidth` | tab-nav `overflow-x` | tab-nav scrollable | "Signal History" reachable |
|---|---|---|---|---|
| 375 | 375 (= vw, no page scroll) | auto | yes (sw 478 > cw 280) | yes (scroll tab-bar) |
| 390 | 390 (= vw) | auto | yes (sw 478 > cw 295) | yes |
| 768 | 768 (= vw) | auto | no (fits: cw 662) | yes |
| 1440 | 1440 (= vw) | auto | no (fits: cw 703) | yes |

Gate `index-mobile-usable` (functional nav / no horizontal page scroll) now PASSES: `documentElement.scrollWidth == innerWidth` at all 4 widths, and the tab-nav is horizontally scrollable at mobile widths so all 6 tabs including "Signal History" are reachable rather than clipped-and-hidden.

**Residual note (NOT this gate, NOT fixed — outside single-gate scope):** `body.scrollWidth` remains 500/522/827/1499. Off-canvas element attribution: `.settings-drawer` (right≈750, transform-hidden off-canvas) and hidden `.tooltip-text` (right≈500) — pre-existing, clipped by the phase's `html{overflow-x:hidden}`, produce NO visible horizontal scrollbar (`documentElement.scrollWidth` = vw). Recorded as a known-gap observation for orchestrator EVL classification; not in this supplement's assigned single-gate scope.

**Verification 3 — structural grep gates (no regression):** viewport-meta count index/admin/landing = 1/1/1; `table-responsive` in index.html = 1 (unchanged); `@media` in styles.css = 8 (unchanged — no media query added).

**Verification 4 — file scope:** `git diff --name-only trading-app/static/` this supplement = `styles.css` only. `landing.html` = zero changes. `admin.html` carries 22 pre-existing insertions from Phase 3's earlier execute pass (already `M` at session start) — NOT touched by this supplement.

**Result:** Gate failure resolved. EVL cycle 1 fix APPLIED.
