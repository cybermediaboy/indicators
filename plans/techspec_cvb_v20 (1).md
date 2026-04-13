# CVB v21 — Technical Specification
**Combined Vector Bands · SetupsLib · kNNMC Engine**
Version: 2026-04-13 · Status: Post-refactoring (patch v20→v21 applied)

**v21 Critical Fix**: Label cleanup now nullifies `rec.setup_label := na` **before** `label.delete()` to prevent dangling references. Phase 3 recreation detects evicted labels via `na(rec.setup_label) and not na(rec.label_y)`.

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    INDICATOR (CVB v20)                   │
│                                                          │
│  ┌──────────────┐   ┌──────────────┐  ┌──────────────┐  │
│  │  SetupsDB    │   │  kNNLib      │  │  MCLib       │  │
│  │  (SetupConfig│   │  (kNN search │  │  (Monte Carlo│  │
│  │   database)  │   │   + family)  │  │   paths)     │  │
│  └──────┬───────┘   └──────┬───────┘  └──────┬───────┘  │
│         │                  │                  │          │
│         ▼                  ▼                  ▼          │
│  ┌──────────────────────────────────────────────────┐    │
│  │                  SetupsLib                        │    │
│  │  OscContext · SetupSpec · SetupEvent              │    │
│  │  LevelTracker · ValidationState                   │    │
│  │  Exit logic · BT simulation                       │    │
│  └──────────────────────────────────────────────────┘    │
│         │                                                 │
│         ▼                                                 │
│  ┌──────────────────────────────────────────────────┐    │
│  │              INDICATOR LAYER                      │    │
│  │  ActivePosition · HistoricalSetup                 │    │
│  │  LabelManager · ValidationState (global FSM)      │    │
│  │  BT Phase 1/2/3 state machine                     │    │
│  └──────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

---

## 2. UDT Catalogue — Consolidated

### 2.1 OscContext  *(SetupsLib — authoritative, replaces SetupContext)*

**Single source of truth** for oscillator state. `SetupContext` is deprecated.

```pine
export type OscContext
    array<float> values   // 6 slots: VEC MR TE CORR LTF PRED
    array<float> p25      // 25th percentile per slot
    array<float> p75      // 75th percentile per slot
    array<float> plo      // low extreme (p2 / p20 depending on slot)
    array<float> phi      // high extreme (p98 / p80 depending on slot)
```

**Slot constants** (global scope, no magic numbers):
```pine
export const int SLOT_VEC  = 0
export const int SLOT_MR   = 1
export const int SLOT_TE   = 2
export const int SLOT_CORR = 3
export const int SLOT_LTF  = 4
export const int SLOT_PRED = 5
```

**Constructor**: `fbuildosccontext(vecosc, mrosc, teosc, corrosc, ltfcorr, predslope, vecp25, vecp75, ...)` → `OscContext`

**Migration note**: All calls to `fcheckshowstoppers(spec, SetupContext)` must be replaced with `fevalshowstoppers(mask, OscContext)`. `SetupContext` type removed in SetupsLib v25.

---

### 2.2 SetupConfig  *(setupsDBGem — setup database)*

Setup contract returned by `setupsDBGem.evaluate_all()`. Converted to `SetupSpec` via `SetupsLib.f_config_to_spec()`.

```pine
export type SetupConfig
    string id
    string name
    string dir
    float tp_pct
    float sl_pct
    int hold_bars
    float wr
    float sharpe
    bool is_active
    float edgeratio
    string thesis
    int showstopper_mask
    int code
    int mask
    int mc_family
    string tooltip
    int thesisflags = 0              // v21: 0=none, 1=anti-impulse, 2=coupling-required
    float impulse_penalty_scale = 1.0  // v21: Impulse penalty multiplier
```

**v21 Update**: Added `thesisflags` and `impulse_penalty_scale` fields. All 11 setups now populate these correctly:
- **thesisflags=1** (anti-impulse): S3, S_Trap, S8, S11, L_Exp, L6, L_Basic (MR/FV mean-revert setups)
- **thesisflags=2** (coupling-required): S_Inn, S4, N_TE_S, N_TE_L (BASKET/TE/BURST momentum setups)

---

### 2.3 SetupSpec  *(SetupsLib)*

Static metadata for a setup type. Immutable once constructed.

```pine
export type SetupSpec
    string id
    string name
    string dir               // "LONG" | "SHORT"
    Family family
    float  wr                // historical win rate 0-100
    float  sharpe
    float  tppct
    float  slpct
    int    avgbars
    string tooltip
    int    timestop
    float  edgeratio
    string thesis            // "MOMENTUM" | "MR" | "DECOUPLE" | "RECOUPLE" | "FV" | "BASKET" | "TE" | "BURST"
    int    thesisflags       // 0=none, 1=anti-impulse (MR/FV), 2=coupling-required (BASKET/TE/BURST)
    int    showstoppermask   // bitmask of SS_* constants
    float  impulsepenaltyscale  // Impulse penalty multiplier (default 1.0)
    int    code              // numeric ID for kNN feature packing
    int    mask              // family bitmask
```

**v21 Update**: `thesisflags` and `impulse_penalty_scale` now populated from `SetupConfig` via `f_config_to_spec()`. Previously hardcoded to 0/1.0, causing `f_score_confidence()` penalty to never apply.

---

### 2.3 SetupEvent  *(SetupsLib)*

Immutable signal record. Created per bar per fired setup. Never modified after push.

```pine
export type SetupEvent
    string id
    string tooltip
    string sizeinfo
    float  confidence        // 0.0–1.0 post-penalty score
    int    showstopperhits   // 0 = clean, >0 = degraded
```

---

### 2.4 LevelTracker  *(SetupsLib)*

One TP/SL line with sweep-aware lifecycle. **Rendering layer only** — no setup logic inside.

```pine
export type LevelTracker
    line   ln
    float  price
    int    start_bar
    int    sweep_dir         // 1=sweep on high>price, -1=sweep on low<price, 0=fixed
    int    default_len
    int    max_scan
    bool   done
```

**Lifecycle**: created by `f_create_level()` → updated each bar by `f_update_levels()` → frozen by `f_freeze_levels()` on position close. Lines are never deleted mid-trade; `done=true` stops updates. The global array `var array<LevelTracker> level_trackers` holds all lines; `ActivePosition.levels_idx + levels_cnt` is the slice reference.

**Constraint**: `LevelTracker` must NOT be embedded in `SetupEvent` or `HistoricalSetup`. It is created only when a position opens, while `SetupEvent` fires for every candidate including filtered ones.

---

### 2.5 ValidationState  *(SetupsLib — singleton FSM)*

State machine for the instant validator. Holds **active** + **one pending** slot.

```pine
export type ValidationState
    // Active slot
    string validating_setup_id   // na = idle
    int    setup_trigger_bar
    float  setup_entry_price
    string setup_direction
    label  validating_label      // ref to existing HistoricalSetup.setup_label
    string validating_tooltip
    int    validation_phase      // 0=idle, 1=kNN, 2=MC, 3=done
    // Pending slot (queued while active runs)
    string pending_setup_id
    int    pending_trigger_bar
    float  pending_entry_price
    string pending_direction
    label  pending_label
    string pending_tooltip
    int    pending_phase
    // MC viz — SEPARATE from position tracking
    float  current_mae_p10
    float  current_mfe_p90
    float  current_mae_alt
    float  current_mfe_alt
    string selected_validation_direction
    float  mae_viz_price
    float  mfe_viz_price
```

**Design rules**:
- `validating_label` and `pending_label` are **references** to labels already created by `f_add_setup_label()`. They are not new objects.
- `mae_viz_price` / `mfe_viz_price` are MC cone anchor prices for visualization only — they do NOT duplicate `ActivePosition.tp1/sl`.
- `validation_phase = 0` means validator is idle and can accept new setup immediately.
- When active slot completes, pending slot promotes atomically via `f_start_or_queue_validation()`.

---

### 2.6 ActivePosition  *(Indicator — local type)*

Live open trade state. One instance per open position.

```pine
type ActivePosition
    string setup_id
    string dir               // "LONG" | "SHORT"
    int    entry_bar
    float  entry_price
    float  tp1
    float  tp2
    float  sl
    float  mc_p10            // MC MAE stop
    float  mc_p50            // MC MFE target
    float  rrr
    bool   is_active
    label  setup_label       // ref to label created at entry
    string tooltip
    int    levels_idx        // start index in global level_trackers[]
    int    levels_cnt        // count (always 3: TP1, TP2, SL)
    int    exit_code         // -1=active, 0=hardSL, 1=trailSL, 2=signalReverse, 3=BE, 4=TP1
```

**Invariant**: `levels_cnt` is always 3 after `f_create_tpsl_levels()`. `levels_idx = -1` until lines are created.

---

### 2.7 HistoricalSetup  *(Indicator — local type)*

Persistent record of every fired setup for BT Phase 1–3 and kNN.

```pine
type HistoricalSetup
    int    bar_idx
    string setup_id
    string direction
    float  entry_price
    float  tp_pct
    float  sl_pct
    int    max_hold
    // Feature snapshot (F1–F7) for kNN
    float  f1_snap … f7_snap
    int    packed_snap
    SetupsLib.Family family_snap
    int    hist_avail         // kNN history depth at signal bar
    int    coupling_regime_snap // 0=Coupled, 1=Weak, 2=Decoupled
    float  basket_fit_norm_snap
    float  rho_snap
    int    setup_code
    float  entry_ctx          // packed context bitfield
    // MC/kNN results (filled by BT phases)
    string mc_oracle_dir
    float  actual_pnl
    float  actual_mae
    float  actual_mfe
    string exit_reason
    float  mc_pct_agree
    float  mc_dir_pct
    bool   mc_confirmed
    float  mc_confidence
    int    knn_cands
    // Label management (v21: recreation parameters for Phase 3)
    label  setup_label        // Pine label object; na after aggressive cleanup or eviction
    float  label_y            // Y-coordinate for label recreation (close price at signal)
    string label_text         // Label text for recreation (setup_id)
    color  label_color        // Label color for recreation (based on direction)
```

---

## 3. Label Management System

### 3.1 Label Lifecycle

```
Bar fires setup
      │
      ▼
f_add_setup_label()
  Creates label.new()
  Pushes to setup_labels[] (global array<label>)
  Assigns to HistoricalSetup.setup_label
  Returns label ref → also stored in ValidationState.validating_label
      │
      ▼
Position opens (ActivePosition created)
  ActivePosition.setup_label = same label ref
  SetupsLib.f_update_exit_label() colors label on exit
      │
      ▼
BT Phase 1 (kNN+MC backtest)
  rec.mc_confirmed / rec.actual_pnl filled
  Labels colored immediately after mc_confirmed set (v21)
      │
      ▼
BT Phase 3 (label repaint, realtime only - v21)
  Recreate evicted labels: if na(rec.setup_label) and not na(rec.label_y)
  label.setcolor() / label.settext() on rec.setup_label
      │
      ▼
Aggressive cleanup (when array.size(setup_labels) > 450 AND bt_done)
  Nullify rec.setup_label := na BEFORE delete
  label.delete(old_lbl)
  setup_labels array shrinks
```

### 3.2 Label Array Management Rules

```pine
// Global — declared once
var array<label> setup_labels = array.new<label>(0)

// f_add_setup_label — called at signal bar only
// Returns the created label
f_add_setup_label(float label_y, string text, color col, string tooltip) =>
    label new_lbl = label.new(bar_index, label_y, text, ...)
    array.push(setup_labels, new_lbl)
    new_lbl

// Aggressive cleanup — only when BT Phase 4 complete
bool bt_in_progress = bt_phase > 0 and bt_phase < 4
bool phase3_painting = bt_phase == 3 and bt_phase3_idx < array.size(bt_setups)
bool bt_done = bt_phase == 4
if array.size(setup_labels) > 450 and bt_done and not bt_in_progress and not phase3_painting
    for i = 0 to math.min(50, array.size(setup_labels) - 450)
        old_lbl = array.shift(setup_labels)
        if not na(old_lbl)
            // Nullify matching HistoricalSetup refs BEFORE delete (prevents dangling handles)
            for j = 0 to array.size(bt_setups) - 1
                HistoricalSetup rec = array.get(bt_setups, j)
                if rec.setup_label == old_lbl
                    rec.setup_label := na
                    array.set(bt_setups, j, rec)
                    break
            // Delete label (now safe - no dangling references)
            label.delete(old_lbl)
```

**Rules**:
1. Never call `label.delete()` during Phase 3 iteration — it invalidates refs being iterated.
2. Nullify `rec.setup_label := na` **before** `label.delete()` to prevent dangling references.
3. Phase 3 recreation detects evicted labels via `na(rec.setup_label) and not na(rec.label_y)`.
4. `setup_labels[]` is the **sole owner** of label objects. `ActivePosition.setup_label` and `ValidationState.validating_label` are **borrowed references** only.

### 3.3 Phase 3 Chunked Label Repaint

**v21 Update**: Phase 3 now runs **only on realtime ticks** (`barstate.isrealtime`), not `barstate.islast`. Pine reverts object changes on historical bars, causing labels to unpaint. Labels are colored immediately in Phase 1 after `mc_confirmed` is set.

```pine
// BT PHASE 3 — Realtime-only label repaint (v21 fix)
if bt_phase >= 3 and barstate.isrealtime
    int bt_size = array.size(bt_setups)
    int painted_cnt = 0
    
    // Render loop: recreate ONLY mc_confirmed labels (save label budget - Pine limit 500 total)
    // Non-confirmed labels are gray/transparent anyway - not worth recreating
    int recreated_cnt = 0
    int max_recreate = 200  // Reserve budget for mc_confirmed labels only (~120 expected)
    
    if bt_size > 0
        // Recreate mc_confirmed setups only (always recreate, regardless of visibility)
        for j = bt_size - 1 to 0
            if recreated_cnt >= max_recreate
                break
            HistoricalSetup rec = array.get(bt_setups, j)
            if na(rec.setup_label) and not na(rec.label_y) and rec.mc_confirmed
                label new_lbl = label.new(rec.bar_idx, rec.label_y, rec.label_text, 
                     style=label.style_label_up, color=rec.label_color, textcolor=color.white, size=size.tiny)
                rec.setup_label := new_lbl
                array.set(bt_setups, j, rec)
                recreated_cnt += 1
    
    // Transition to Phase 4 only on realtime ticks (not islastconfirmedhistory)
    if barstate.isrealtime
        bt_phase := 4
```

**Critical changes (v21)**:
1. **Phase 3 trigger**: `barstate.isrealtime` only (removed `barstate.islast`)
2. **Immediate coloring**: Labels colored in Phase 1 after `mc_confirmed` set (lines 2796-2804)
3. **Recreation optimization**: Only `mc_confirmed` labels recreated (max ~120), skip non-confirmed
4. **Label eviction**: `HistoricalSetup` stores `label_y`, `label_text`, `label_color` for recreation after Pine evicts labels
5. **Phase 4 transition**: Only on realtime ticks to ensure all labels painted before done

---

## 4. BT State Machine

```
btphase 0  idle
  → triggers when barstate.islastconfirmedhistory
  → Phase 1 starts: btchunkidx = 0

btphase 1  kNN+MC validation (chunked per tick)
  budget: btheavybudget validations/tick
  for each HistoricalSetup in btsetups[btchunkidx..]:
    - guard: rec.histavail >= btminhistory
    - kNN: fhierarchicaltournamentbacktestsignaware(...)
    - MC:  fsimulatebtposition(...)
    - fill: rec.mcconfirmed, rec.actualpnl, rec.mcdirpct, rec.knncands
  → when btchunkidx >= btsetups.size: btphase = 2

btphase 2  summary aggregation (single tick)
  fill: btallwins, btrawtotal, btfilttotal, Welford stats
  → btphase = 3

btphase 3  label repaint (chunked, see §3.3)
  → btphase = 4

btphase 4  done
  table updates continue on each tick from aggregated vars
```

---

## 5. Exit Code Enum

| Code | Name | Condition |
|------|------|-----------|
| -1 | Active | position open |
| 0 | HardSL | pnl < -1.8% |
| 1 | TrailSL | low/high crosses trail_sl_target |
| 2 | SignalReverse | indicator-specific reversal (CVB: pred_ma flip, others: basket decouple, EMA cross, etc.) |
| 3 | Breakeven | bars_held > 5 and pnl <= 0 |
| 4 | TP1 | high/low reaches tp1 |

**v21 Update**: Exit code 2 renamed `PredFlip` → `SignalReverse` (generic). Indicator passes `signal_reverse_check` bool to `f_evaluate_exit()`.

Exit evaluation: `f_evaluate_exit(dir, pnl, max_pnl, bars_held, hi, lo, tp1, trail_sl_in, trail_sl_target, signal_reverse_check)` → returns `[exit_code, new_trail_sl]`. Label text/color via `f_update_exit_label()` / `f_get_exit_info()`. `f_exit_logic()` is **deprecated** (removed in v7).

---

## 6. OscContext Migration from SetupContext

### Deprecated `fcheckshowstoppers(SetupSpec, SetupContext)`:
```pine
// OLD — remove
blocked, hits, reason = SetupsLib.fcheckshowstoppers(spec, setupCtx)
```

### Replacement using `fevalshowstoppers(int, OscContext)`:
```pine
// NEW
bool blocked = SetupsLib.fevalshowstoppers(spec.showstoppermask, oscCtx)
```

### `SetupContext` → `OscContext` field mapping:
| SetupContext field | OscContext access |
|---|---|
| `vecosc` | `array.get(ctx.values, SLOT_VEC)` |
| `mrosc` | `array.get(ctx.values, SLOT_MR)` |
| `teosc` | `array.get(ctx.values, SLOT_TE)` |
| `corrosc` | `array.get(ctx.values, SLOT_CORR)` |
| `ltfcorr` | `array.get(ctx.values, SLOT_LTF)` |
| `predslope` | `array.get(ctx.values, SLOT_PRED)` |
| `vecp25/p75` | `array.get(ctx.p25/p75, SLOT_VEC)` |
| `mrp2/p98` | `array.get(ctx.plo/phi, SLOT_MR)` |
| `corrp20/p80` | `array.get(ctx.plo/phi, SLOT_CORR)` |

---

## 7. ValidationState Rules

1. **Idle check**: `vs.validation_phase == 0` before accepting new setup.
2. **Label ownership**: `validating_label` borrows from `setup_labels[]`. Never delete via ValidationState.
3. **MC viz decoupled**: `mae_viz_price`/`mfe_viz_price` are display-only; they do NOT govern exit logic.
4. **Promotion**: when active slot completes, call `f_start_or_queue_validation()` which atomically promotes pending → active.
5. **No duplication**: do NOT copy `entry_price`/`direction` from ValidationState into ActivePosition independently — use `vs.setup_entry_price` and `vs.setup_direction` as the canonical source at promotion time.

---

## 8. LevelTracker Rules

1. Created **only** when position opens (`f_create_tpsl_levels()`).
2. Global array `level_trackers` is append-only during trading; `ActivePosition.levels_idx` indexes into it.
3. `f_freeze_levels(levels_idx, levels_cnt)` called on position close.
4. Lines are not deleted — they persist on chart history (frozen, `done=true`).
5. Line count limit enforced by `max_tpsl_lines` input; oldest lines pruned when exceeded (iterate array, call `line.delete()` on oldest, remove from array).
6. **Zero-length line guard**: `line.new()` is not called when `sweep_dir == 0 and default_len == 0` — Pine does not render zero-length lines.

---

## 9. Known Bugs (Open)

| ID | Location | Description | Severity |
|----|----------|-------------|----------|
| Bug 12 | `f_update_exit_label` | Discards label width padding set by `f_add_setup_label` — cosmetic | Low |
| Bug 13 | `f_calc_tpsl` | When zone invalid, tp2/tp3 fall back to raw_tp (same as tp1) — overlapping lines cosmetic | Low |

---

## 10. Removed / Deprecated (v21 Refactoring)

### 10.1 Removed from MCLib
| Symbol | Removed in | Replacement |
|--------|-----------|-------------|
| `f_run_lite_antithetic_mc()` | v21 | `f_welford_knn_bootstrap()` (Welford-based) |
| `f_run_realtime_mc_chunk()` | v21 | `f_welford_knn_chunk()` (Welford-based) |
| `f_update_progressive_percentiles()` | v21 | Welford accumulators (O(1) progressive stats) |
| `f_get_mc_family()` | v21 | `SetupsLib.f_get_mc_family()` (SSoT) |

### 10.2 Deprecated in kNNLib (marked for removal in v4)
| Symbol | Status | Replacement |
|--------|--------|-------------|
| `f_knn_scan()` | DEPRECATED | `f_hierarchical_tournament_backtest/live()` |
| `f_knn_select()` | DEPRECATED | `f_hierarchical_tournament_*()` |
| `f_euclidean_distance()` (6-feature) | DEPRECATED | 7-feature hierarchical tournament |
| `f_find_k_nearest()` (6-feature) | DEPRECATED | `f_hierarchical_tournament_*()` |
| `f_calculate_confidence()` (6-feature) | DEPRECATED | Confidence computed in tournament |
| `f_median_distance()` (6-feature) | DEPRECATED | Not used in v20 tournament |

### 10.3 Deprecated in SetupsLib (marked for removal in v7)
| Symbol | Status | Replacement |
|--------|--------|-------------|
| `type SetupContext` | DEPRECATED | `OscContext` (array-based) |
| `f_check_showstoppers(SetupSpec, SetupContext)` | DEPRECATED | `f_eval_showstoppers(mask, OscContext)` |
| `f_find_setup_spec()` | DEPRECATED | `f_get_spec()` (returns SetupSpec object) |
| `f_exit_logic()` | DEPRECATED | `f_evaluate_exit()` + `f_exit_label_text()` + `f_exit_label_color()` |

### 10.4 Legacy (pre-v19)
| Symbol | Removed in | Replacement |
|--------|-----------|-------------|
| `f_get_mc_family_from_setup()` | v19 | `SetupsLib.f_classify_market_state()` |
| `f_setup_id_to_code()` | v19 | `SetupConfig.code` field |
| `f_setup_id_to_mask()` | v19 | `SetupConfig.mask` field |
| `btphase3_legacy` | v20 | Phase 3 chunked repaint via `btphase3idx` |

