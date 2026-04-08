# CVB v19 — Debug & Measurement Consistency Fix: Technical Specification

**Version target:** Combined Vector Bands v19 kNN+ConeFilter.pine  
**Scope:** Debug bitfield export, backtest engine, position exit simulation, cooldown logic, version parity  
**Purpose:** Eliminate all known sources of measurement inconsistency before re-calibrating setup conditions, TP/SL values, and performance metrics

---

## Overview

Eight discrete classes of bugs currently prevent the CSV simulation and the in-chart BT engine from measuring the same population of trades with the same exit logic. Until these are fixed, any WR / RR / Sharpe number computed from the CSV exports is not comparable to what the live indicator would actually produce. The fixes below address each class in dependency order — structural changes to the debug bitfield first, exit simulation second, kNN/MC correctness third, then smaller consistency items last.

---

## Fix 1 — `actualfire` plot: replace `setupdebugcode` as the CSV signal source

### Problem

`setupdebugcode` is computed from the raw per-setup boolean flags (`setups1`, `setups6`, `setupl5`, etc.) with only `setupmingap` debounce applied. It does **not** reflect three additional suppression layers that the real engine applies:

- `fsetupcooldownok()` — per-setup debounce guard inside `fregistereventauto()`
- `allowlong` / `allowshort` — global `isfallingknife` block
- `isstale` (barindex − lasttriggerbar < 3) — cross-setup staleness guard inside `ffiresetupbyid()`
- `coneconflict` — MC cone direction veto inside `ffiresetupbyid()`

As a result `setupdebugcode` fires on roughly 2× as many bars as the engine actually opens a position, and the CSV simulation inherits this inflation.

### Fix

Remove `setupdebugcode` from the CSV export pipeline. Introduce a new persistent series `actualfiresignal` that is set to the numeric `setupcode` of the setup that actually fired on a given bar, and reset to 0 on every other bar. Set it inside `ffiresetupbyid()` at the moment a setup passes all gates and calls `ffiresetup()`:

```pine
// At the point ffiresetup() is called inside ffiresetupbyid():
actualfiresignal := SetupsLib.fsetupidtocode(firesetupid)
```

Reset at bar start:
```pine
actualfiresignal := 0
```

Replace the `setupdebugmerged` component in `debugcombined` with `actualfiresignal`:

```pine
float debugcombined = actualfiresignal + clddebugbitfield * 100000.0
plot(debugcombined, "Debug Combined", color=color.new(color.yellow, 0), display=display.datawindow)
```

This ensures the `Debug Combined` data-window column reflects only confirmed entries, making CSV-exported N identical to BT engine N by construction.

---

## Fix 2 — add numeric setups 81 / 73 / 75 / 64 to `actualfiresignal` (and old `setupdebugcode` path)

### Problem

The four numeric-ID setups (`81` CORRBOTTOM_MRCONFIRM, `73` CORRPEAK_MRCONFIRM, `75` BEARDIV_OVERSOLD, `64` CLD_FALL-RISE) are registered via `fregistereventauto()` with string IDs `"81"`, `"73"`, `"75"`, `"64"`. They reach `ffiresetupbyid()` through the engine event loop identically to S/L/V setups. Because Fix 1 routes `actualfiresignal` through `ffiresetupbyid()`, these four setups are automatically covered once Fix 1 is implemented — no separate handling is needed.

However, if the old `setupdebugcode` path is kept for any reason (e.g., legacy comparison), the `else if` chain in the debug section must place the numeric-ID blocks **before** the V-setup chain, because `"81"` etc. are checked against `SetupsLib.fsetupidtocode()` which returns non-zero only for mapped IDs. The current ordering causes them to be shadowed. Reorder to: numeric IDs → V-setups → L-setups → S-setups.

---

## Fix 3 — cooldown reference: `lastpredshortbar` / `lastpredlongbar` updated only at fire, not at arm

### Problem

Armed setups (S5, L2, V1, V2, V4) update `lastpredshortbar` or `lastpredlongbar` at the moment the setup is **armed** (before `predrounddelay` confirmation). `fsetupcooldownok()` uses these same variables as the reference point for its debounce window. This means the cooldown clock starts too early — if the armed setup is cancelled or the delay window expires without confirmation, a subsequent real signal on the same side will be incorrectly suppressed for up to `setupmingap` bars.

### Fix

In the arming block (where `armedsetupid := "S5"` etc. is written), do **not** update `lastpredshortbar` / `lastpredlongbar`. Move those updates exclusively into the fire-confirmation block:

```pine
// WRONG — current code (in arm block):
// lastpredshortbar := barindex  ← REMOVE THIS

// CORRECT — only in the fire block (after ffiresetupbyid returns non-na pos):
if not na(armedpos.entrybar)
    if armeddirection == "LONG"
        lastpredlongbar := barindex
    else
        lastpredshortbar := barindex
```

This makes cooldown semantics consistent: the window starts when a trade is actually opened, not when it is merely queued.

---

## Fix 4 — BT phase 1: simulate trailing SL, predflip, and breakeven exit

### Problem

This is the most consequential measurement error. BT phase 1 exits every trade using only fixed `tppct` / `slpct` against the close series with `holdlimit = tpslmaxhold`. The live engine uses four sequential exit conditions:

1. Hard stop: `pospnl < -1.8%`
2. Trailing SL to `predma` (activates when `maxpnl > 0.5%`)
3. Predflip: 3-bar `predma` slope reversal
4. Breakeven: `barsheld > 5 AND pospnl < 0`

The mismatch causes BT `actualpnl` to systematically overestimate losses (no breakeven cut), underestimate wins (predflip/trailing can capture more than `tppct`), and produce Sharpe numbers that do not correspond to anything the live indicator would deliver.

### Fix

Extend the inner price-scan loop in BT phase 1 to replicate all four conditions. The `arrclose` and `arrATR` ring buffers are already available. Add `arrpredma` as a parallel history ring buffer (same push pattern as `arrclose`) and include it in `fupgradefeaturebuffers()`:

```pine
// In ring buffer push section (global scope):
array.push(arrpredma, predma)
if array.size(arrpredma) > maxhistory
    array.shift(arrpredma)
```

In BT phase 1 inner loop, replace the simple TP/SL check with:

```pine
float ep       = rec.entryprice
bool  islong   = rec.direction == "LONG"
float hardsl   = islong ? ep * (1.0 - 1.8/100.0) : ep * (1.0 + 1.8/100.0)
float best     = 0.0
float trailsl  = na
float exitpnl  = na
string exitrsn = "MAXHOLD"

for h = 1 to holdlimit
    int   idx   = offset + h
    if idx >= csizebt
        break
    float px      = array.get(arrclose, idx)
    float pma     = array.get(arrpredma, idx)
    float pma3    = h >= 3 ? array.get(arrpredma, idx - 3) : pma
    float pma_p   = array.get(arrpredma, idx - 1)
    float pnl     = islong ? (px - ep) / ep * 100.0 : (ep - px) / ep * 100.0
    best          := math.max(best, pnl)

    // 1. Hard SL
    if islong ? px <= hardsl : px >= hardsl
        exitpnl := pnl
        exitrsn := "SL"
        break

    // 2. Trailing SL (activate after 0.5% max gain)
    if best >= 0.5
        float tlevel = pma
        trailsl      := na(trailsl) ? tlevel : (islong ? math.max(trailsl, tlevel) : math.min(trailsl, tlevel))
        if islong ? px <= trailsl : px >= trailsl
            exitpnl := pnl
            exitrsn := "TRAIL"
            break

    // 3. Predflip (3-bar slope reversal)
    bool rising  = pma > pma3
    bool rising1 = pma_p > array.get(arrpredma, math.max(0, idx - 4))
    bool flipbear = not rising and rising1
    bool flipbull = rising and not rising1
    if islong ? flipbear : flipbull
        exitpnl := pnl
        exitrsn := "PREDFLIP"
        break

    // 4. Breakeven (after 5 bars if still underwater)
    if h >= 5 and pnl < 0.0
        exitpnl := 0.0
        exitrsn := "BE"
        break

    // Legacy TP (lowest priority)
    if pnl >= rec.tppct
        exitpnl := pnl
        exitrsn := "TP"
        break
```

Replace `rec.actualpnl := exitpnl`, `rec.actualmae := worst`, `rec.actualmfe := best`, `rec.exitreason := exitrsn` with values from this new loop. The `worst` variable for MAE must be tracked separately inside the same loop:

```pine
float worst = 0.0
// inside loop:
worst := math.min(worst, pnl)
```

---

## Fix 5 — replace `fhierarchicaltournamentbacktest` with `fhierarchicaltournamentbacktest_signal_aware` in all BT calls

### Problem

The old BT call (`fhierarchicaltournamentbacktest`, without `_signal_aware` suffix) does not apply the forward-bias check `maxid > offset`. This allows kNN to select neighbors that were indexed **after** the setup bar, introducing lookahead bias into the MC concordance estimate. Any CSV exports produced while the old call was active have contaminated `mcpctagree` values and must be treated as invalid for Sharpe/WR recalibration purposes.

### Fix

In BT phase 1, ensure the call reads:

```pine
[chosenids, chosendists, chosenw, dbgiter, dbghskip, dbgnskip, finalcount] = \
    kNNLib.fhierarchicaltournamentbacktest_signal_aware(
        rec.packedsnap, rec.f1snap, rec.f2snap, rec.f3snap,
        rec.f4snap, rec.f5snap, rec.f6snap, rec.f7snap,
        familyid, setupcode, arrpackedvec,
        f2history, f3history, f4history, f5history, f6history, f7history,
        arrsetupid, arrsetupfamily, arrpackedvec,
        knnlimit, knnk, 4, knndeclustergap, 50)
```

Confirm that the P0 forward-bias block is present and active:
```pine
if array.size(chosenids) > 0
    int maxid = array.get(chosenids, array.size(chosenids) - 1)
    bool forwardbiasdetected = maxid > offset
    // ... skip if detected
```

Invalidate (do not use for recalibration) any CSV files exported before this fix was merged.

---

## Fix 6 — export `mcvalidatordirectionmode` in MLEXPORT header

### Problem

The BT phase 1 validator switches between two fundamentally different concordance measurement strategies based on `mcvalidatordirectionmode`: "Setup Direction" (paths evaluated against the setup's own declared direction) vs. "Best MC Direction" (both long and short paths scored, strongest wins). The current MLEXPORT header does not include this parameter. Post-hoc analysis cannot determine which mode was active when a given CSV was produced, making cross-file comparison ambiguous.

### Fix

Add `mcvalidatordirectionmode` to the MLEXPORT header line and to each data row:

```pine
// Header:
log.info("MLEXPORTHEAD" + "baridx,setupid,direction,f1,f2,f3,f4,f5,f6,f7," +
    "actualpnl,actualmae,actualmfe,exitreason,mcconfirmed,mcconfidence," +
    "mc_dir_mode,mc_dir_pct")

// Row:
string row = "MLEXPORTROW" + str.tostring(s.baridx) + "," + s.setupid + "," +
    s.direction + "," + ... + "," +
    (mcvalidatordirectionmode ? "setup" : "best") + "," +
    str.tostring(nz(s.mcdirpct), "##.##")
log.info(row)
```

---

## Fix 7 — guard against multi-fire race condition in `arrsetupid`

### Problem

`ffiresetupbyid()` writes `array.set(arrsetupid, setupidcount - 1, firesetupcode)` using the current size of `arrsetupid` minus one. If `engineeventcount > 1` and two events both pass all gates on the same bar, the second call will overwrite the last element with a different setupcode, dropping the first setup's ID from the kNN history ring buffer. This silently corrupts the neighbor pool for all future setups that fired on the same bar.

### Fix

Add a within-bar counter `firedthisbar` (reset at bar start to 0, incremented on each confirmed fire). On each fire, push to `arrsetupid` rather than overwriting, and apply the ring-buffer size cap after the push:

```pine
// At bar start (global scope):
int firedthisbar = 0

// Inside ffiresetupbyid, after ffiresetup() confirms entry:
firedthisbar += 1
array.push(arrsetupid, firesetupcode)
if array.size(arrsetupid) > maxhistory
    array.shift(arrsetupid)
```

Ensure `arrpackedvec`, `f1history`…`f7history` are pushed with the same guard so all parallel arrays remain the same length. This change also makes the push logic in `ffiresetupbyid` consistent with how `arrclose` and `arrATR` are managed globally.

---

## Fix 8 — version flag in MLEXPORT: tag all rows with `velrecouple_abs_fix`

### Problem

`velrecoupleraw` used `ltfcorrema > ltfrecoupleadaptive + 0.10` (directional, no `math.abs`) in the version that produced the CRV/UNI CSV files. The current version corrects this to `math.abs(ltfcorrema) > ltfrecoupleadaptive + 0.10`. Setups that depend on `velrecouple` (L3, V4, and the arming gate for V4) will have different trigger populations between old and new-version exports. Mixing them in a single analysis sample produces spurious feature distributions in kNN training.

### Fix

Add a compile-time boolean constant at indicator top:

```pine
bool VEL_RECOUPLE_ABS_FIX = true  // false in old exports, true from this version
```

Include it in the MLEXPORT header and mark all new exports accordingly. Do not include old-version CSV files (where this column is absent or false) in the recalibration dataset for L3 or V4.

---

## Implementation Order & Dependencies

The fixes above have the following dependency chain. Implement in this sequence to avoid regressions:

| Step | Fix | Depends on | Risk |
|------|-----|------------|------|
| 1 | Fix 3 — cooldown at fire, not arm | none | Low |
| 2 | Fix 7 — `arrsetupid` push guard | none | Low |
| 3 | Fix 8 — version flag + MLEXPORT tag | none | Trivial |
| 4 | Fix 1 — `actualfiresignal` replaces `setupdebugcode` in Debug Combined | Fix 3 (cooldown must be correct first) | Medium |
| 5 | Fix 2 — numeric setups in old debug path | Fix 4 implicit | Low |
| 6 | Fix 4 — `arrpredma` buffer + BT exit rewrite | Fix 7 (array size parity) | High |
| 7 | Fix 5 — `signal_aware` kNN call verification | Fix 4 (run after BT loop is correct) | Medium |
| 8 | Fix 6 — MLEXPORT header extension | Fix 4, Fix 5 | Trivial |

After all eight fixes are merged, regenerate all CSV exports from scratch on the same CRV and UNI date ranges. Only then re-run the WR / RR / Sharpe / yield analysis.

---

## Validation Checklist (post-implementation)

- [ ] `Debug Combined` data-window value is 0 on bars where no setup fires, and equals `setupcode * 1 + clddebugbitfield * 100000` on bars where a setup actually fires
- [ ] CSV row count for any given asset/timeframe window matches BT engine `btrawtal` counter (±0)
- [ ] Numeric setups 81/73/75/64 appear in CSV exports
- [ ] `lastpredshortbar` / `lastpredlongbar` do not advance on arm cancellation (verify by logging bar delta between arm and fire)
- [ ] BT `actualpnl` distribution includes "BE" and "TRAIL" exit reasons; "TP" exits are a minority
- [ ] No `maxid > offset` forward-bias violations logged (P0 block silent)
- [ ] MLEXPORT CSV header includes `mc_dir_mode` and `vel_fix` columns
- [ ] `arrsetupid`, `arrpackedvec`, and all `f*history` arrays remain equal length after 1000+ bars
- [ ] L3 and V4 setup trigger frequency visually matches between old and new version on the same chart window (confirms `velrecouple` fix is consistent)
