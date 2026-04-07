# CVB v19 — Wiki & Codemap

## Architecture Overview

**Combined Vector Bands v19** is a Pine Script v6 overlay indicator (~4284 lines) that fuses multi-asset basket analysis, statistical learning (kNN), and Monte Carlo forward projection into a single trading system. It delegates reusable logic to 7 published TradingView libraries.

### Lib/Indicator Separation Convention

| Layer | Where | What belongs here |
|---|---|---|
| **Libraries** | Published TradingView libs (`cybermediaboy/*`) | Reusable math, types, pure functions. No `input.*`, no `plot()`, no `var` state. |
| **Indicator** | `Combined Vector Bands v19 kNN+ConeFilter.pine` | All inputs, state management (`var`/`varip`), data fetching (`request.security`), detection logic, plotting, tables. |

**Rule**: If a function has no side effects and could be used by another indicator → library. If it reads inputs, manages state, or calls `plot()` → indicator.

---

## Library Map

### TAUtilityLib/52 (2555 lines, 142 exports)
**Role**: Swiss-army-knife utility library. Math, smoothing, normalization, visual infrastructure.

| Category | Key Exports |
|---|---|
| **Types** | `FractalData`, `CorrelationLine`, `KalmanState`, `SubPane`, `OscMeta`, `OscState`, `TPSLDrawings` |
| **Kalman Filters** | `f_kalman()`, `f_kalman_control()`, `f_kalman_update()`, `f_kalman_robust()`, `f_te_enhanced_kalman_update()` |
| **Smoothing/MA** | `f_kama()`, `f_dynamic_ema()`, `f_dynamic_sma()`, `supersmoother()`, `butter_smooth()`, `dema()` |
| **Z-Scores** | `f_zscore_standard()` → `[ma, z, dev]`, `f_zscore()`, `f_corr_weighted_zscore()` |
| **Normalization** | `f_iqr_normalize()`, `f_percentile_rank_fisher()`, `f_norm_system()` (5-layer regime-switched), `f_winsorize()` |
| **SubPane System** | `f_layout_subpanes()`, `f_register_osc()`, `f_process_oscs()`, `f_manage_labels()`, `f_apply_softclip()`, `f_update_osc_ob_os_lines()` |
| **Clipping** | `f_tanh()`, `f_sigmoid_norm()`, `f_clamp()`, `f_apply_softclip("tanh"/"sigmoid"/"clamp"/"none")` |
| **Basket/Symbol** | `f_symbol_base()`, `f_is_active_symbol()`, `f_status_icon()`, `f_symbol_activity_1m()` |
| **Bands** | `f_calc_survival_bands()`, `f_detect_squeeze()`, `f_detect_confluence()` |
| **Statistics** | `cov()`, `f_pearson_tail()`, `f_spearman()`, `f_kendall()`, `f_norm_cdf()` |
| **Delta/Volume** | `f_calc_delta()`, `f_calc_buy_sell()` |
| **Helpers** | `f_push_limited()`, `f_tail()`, `f_safeArrayGet*()`, `f_getOr*()`, array map functions |

### CausalityLib/14 (~400 lines, 16 exports)
**Role**: Transfer Entropy (TE) and Granger causality between asset and basket.

| Export | Purpose |
|---|---|
| `f_calculate_te_score()` | Single-pair TE with discretization |
| `f_compute_te_wrapper()` | Multi-basket TE ensemble (up to 5 tickers, self-exclusion) |
| `f_compute_te_ensemble()` | Smoothed TE ensemble with gating |
| `f_calculate_granger_score()` | Granger causality via lagged correlation |
| `f_pcmci_filter_score()` | Spurious causality filter (partial correlation with 4 mediators) |
| `f_kalman_hedge_ratio()` | Kalman beta tracker for LTF correlation |
| `f_discretize()`, `f_shannon_entropy()` | Binning and entropy primitives |

### SetupsLib/13 (832 lines, 58 exports)
**Role**: Setup database, family classification, TP/SL management, validation state.

| Category | Key Exports |
|---|---|
| **Types** | `Family`, `SetupSpec`, `SetupSignal`, `SetupEvent`, `SetupContext`, `OscContext`, `ValidationState`, `LevelTracker` |
| **Database** | `f_build_setup_db_v19(families)` → enriched DB, `f_build_setup_db()` → simple DB |
| **Family** | `f_build_family_table()` → 5 families (Continuation, MR, Transition, Velocity, Uncertain) |
| **Lookup** | `f_setup_id_to_code()`, `f_setup_id_to_mask()`, `f_find_setup_spec()`, `f_get_spec()` |
| **Meta** | `f_get_edge_ratio_meta()`, `f_get_thesis_meta()`, `f_get_showstopper_mask_meta()` |
| **Registration** | `f_register_event_auto()` — fire condition → event with auto-spec lookup |
| **TP/SL** | `f_calc_tpsl()`, `f_create_tpsl_levels()`, `f_update_levels()`, `f_remove_levels()` |
| **Showstoppers** | `SS_*` constants (bitmask), `f_eval_showstoppers()`, `f_check_showstoppers()` |
| **Validation** | `f_seed_validation()`, `f_start_or_queue_validation()`, `f_exit_logic()` |

### kNNLib/15 (788 lines, 23 exports)
**Role**: k-Nearest Neighbors search with TurboQuant encoding and hierarchical tournament.

| Export | Purpose |
|---|---|
| `f_turboquant()` | Lloyd-Max quantization (3-bit index + 3-bit residual per feature) |
| `f_pack_vector()` / `f_pack_vector_7()` | Pack 6/7 quantized features into single int |
| `f_hamming_screen()` | Fast binary pre-filter on packed vectors |
| `f_find_k_nearest_7()` | Full 7-feature Euclidean kNN |
| `f_hierarchical_tournament_live()` | 3-tier kNN: Hamming screen → Euclidean → family decluster |
| `f_hierarchical_tournament_backtest()` | Same but for historical validation |
| `f_sign_aware_filter()` | Filters history buffer by correlation sign agreement |
| `f_calculate_confidence()` | Distance-weighted confidence from k-nearest neighbors |
| `f_normalize_*()` | Feature-specific normalization (burst, corr, TE, phi_div) |

### MCLib/10 (538 lines, 11 exports)
**Role**: Monte Carlo path simulation and percentile extraction.

| Export | Purpose |
|---|---|
| `f_mc_sim_step()` | Single-step path evolution with drift + vol + mean-reversion |
| `f_mc_extract_percentiles()` | P10/P50/P90 from simulation buffer |
| `f_mc_progressive_update()` | Chunked MC accumulation across ticks |
| `f_mc_backtest_sim()` | Historical setup validation via MC paths |
| `f_bt_summary()` | Backtest aggregation (WR, Sharpe, MAE, MFE) |

### BandsLib/4 (176 lines, 3 exports)
**Role**: Survival probability bands and squeeze detection.

| Export | Purpose |
|---|---|
| `f_calc_survival_bands()` | Probability-based deviation bands with vector shift |
| `f_detect_squeeze()` | Bandwidth percentile squeeze + breakout direction |

### BasketLib/3 (378 lines, 13 exports)
**Role**: Auto-scan basket composition and weighting.

| Export | Purpose |
|---|---|
| `f_auto_scan_basket()` | Rank candidate tickers by correlation, select top N |
| `f_apply_basket_weights()` | Correlation-power / equal / manual weighting |
| `f_calc_basket_z()` | Weighted basket Z-score from peer spreads |

---

## Indicator Section Map

### Lines 1–176: IMPORTS & INPUTS
- 7 library imports
- ~25 input groups (`grp_*`), ~80 `input.*` declarations
- Groups: Display, TP/SL, Basket, Performance, Model, KB/ML, Survival, Correlation, Fit, Innovation, Regime, Entropy, CLD, Debug, Signals, LTF, MC, Normalization, Setups, TE, kNN, Backtest, Confluence

### Lines 177–340: STATE MACHINE & TYPES
- **MC State Machine** (lines 177–231): `mc_phase` (0-4), chunk tracking, progressive buffers
- **Instant Validator** (lines 232–287): MAE/MFE visualization state
- **UDTs** (lines 293–340): `ConfluenceCluster`, `Position` (trade tracking with labels, TP/SL, PnL)

### Lines 341–525: HELPER FUNCTIONS & SETUP DB
- `f_calculate_te_score()` — local TE wrapper
- `f_cld()` — Correlation Lifecycle Detector (linreg slope-flip pattern)
- `f_update_feature_buffers()` — ring buffer push for 7 kNN features
- `f_setup_cooldown_ok()` — debounce guard
- **Setup DB** init: `SetupsLib.f_build_setup_db_v19(families)` at line 481
- **Position state** vars: `var pos`, tracking vars for TP/SL/exit

### Lines 526–728: DATA FETCHING & RETURNS
- `request.security()` for 4 basket peers (close + volume)
- Auto-scan via `BasketLib.f_auto_scan_basket()`
- Return calculations: `r0` (base), `r1`–`r4` (peers), `simple_basket_return`
- Z-score computation: `z0`, `simple_basket_z`
- TE return arrays: `te_primary_returns`, `te_basket_returns_1`–`4`

### Lines 729–797: TRANSFER ENTROPY
- Scheduled execution (only in heavy zone, every bar)
- `CausalityLib.f_compute_te_wrapper()` → `te_osc`, `te_strength_smoothed`, `te_direction_smoothed`
- Debug label on last bar

### Lines 798–1000: MR ORTHOGONALIZATION & CORRELATION FILTER
- **3-Level MR**: Pairwise spreads → weighted aggregate → raw aggregate
- **Kalman Beta Tracker**: State-space `y = βx + ε` for HTF correlation
- **Soft Dampening**: Fisher-transform + sigmoid on correlation → `corr_damping`
- **Percentile Decoupling**: `is_decoupled` / `is_partial` / `is_attached`

### Lines 1000–1190: LTF CORRELATION TRACKING
- Auto LTF timeframe selection (1/3 to 1/8 of chart TF)
- `request.security_lower_tf()` for primary + basket close arrays
- **Kalman Beta Tracker** (LTF): Returns-based β with warmup gate
- `ltf_corr_ema` → `ltf_rho_z` (Z-scored for SubPane)
- Decoupling/recoupling event detection with hysteresis

### Lines 1190–1500: BASKET FIT, CLD, KB/SGD, PREDICTIVE MA, MR
- **Basket Fit**: Return correlation → fit score
- **CLD**: Correlation slope-flip pattern detection (continuation/exhaustion)
- **Kirschenbaum SGD**: Self-tuning vector sensitivity from pivot prediction error
- **VWAP Rejection SGD**: Learns from VWAP interaction pivots
- **Predictive MA**: HMA on vector-adjusted shadow price
- **MR Oscillator**: Kalman-smoothed peer-driven reversion target (PhiLatch, PhiTotal_orth)

### Lines 1500–1700: CONTEXT, BANDS, REGIME, OSCILLATORS
- **High Vector Context**: Exhaustion/continuation interpretation
- **Survival Bands**: 3-zone probability bands via `BandsLib`
- **3-State Kalman Fusion**: Baseline MA coloring (slope + momentum + vector)
- **Confluence Detector**: Level clustering
- **Shannon Entropy**: Background coloring for trend change
- **Regime Event Detector**: Bounce / MR Setup / Trend Change via innovation Z-score
- **Squeeze/Breakout**: Bandwidth percentile detection
- **Vector & Correlation Oscillators**: `vector_osc_z`, `rho_z_score`

### Lines 1700–1870: kNN+MC FEATURE ENGINE
- **7 Orthogonal Features**: VectorOsc, BasketCorr, InnovZ, TE_Osc, OrthoZcvb, PhiDiv, BurstScore
- Percentile-rank + Fisher normalization (`f_norm_stable`)
- Feature validation gate (TE warmup check)
- Ring buffer management with `f_update_feature_buffers()`
- Lloyd-Max TurboQuant encoding → `packed_vec`
- History arrays for path resampling

### Lines 1870–2100: MC VISUALIZATION & EXECUTION CONTEXT
- Cone display infrastructure (lines, fills, labels)
- Backtest state tracking (`bt_phase`, `bt_table_ready`)
- **Execution Context Normalization**: `is_right_edge`, `is_history_edge`, `is_hard_zone`, `calc_active`
- Pred MA rounding detection

### Lines 2100–2220: NORMALIZATION & SETUP INFRASTRUCTURE
- **5-Layer Normalization**: `TAUtilityLib.f_norm_system()` — coupling regime → IQR normalize → hybrid TE threshold → LTF adaptive thresholds → vol-homoscedastic MR
- Percentile cache with scan interval
- Setup debounce and cooldown functions
- Label management helpers (`f_arm_setup`, `f_fire_armed_setup`)

### Lines 2220–2830: MC STATE MACHINE & BACKTEST
- **kNN Phase** (phase 1): `kNNLib.f_hierarchical_tournament_live()` on realtime ticks
- **MC Phase** (phase 2): Chunked simulation via `MCLib.f_mc_sim_step()`
- **Percentiles Phase** (phase 3): Extract P10/P50/P90 from buffers
- **Done Phase** (phase 4): Cone rendering, setup validation
- **Backtest Validator**: Historical setup scanning with MC-based MAE/MFE

### Lines 2830–3120: EMPIRICAL SETUP DETECTION
- **Short Setups**: S1, S5–S11 (TE, LTF, MR, VelDiv, CLD, PredRound, LTF+MR+Coupled)
- **Long Setups**: L1–L8 (TE+CFV, VelRecouple, MRStrict, PredRound)
- **V Setups**: V1–V4 (Bounce, MR, Transition, VelRecouple)
- **Numeric Setups**: 81, 73, 75, 64 (correlation + MR combos, CLD)
- **Engine Events**: `SetupsLib.f_register_event_auto()` for all setups
- Event processing: priority selection, label creation, position management

### Lines 3120–3600: POSITION MANAGEMENT & SIGNAL RENDERING
- Position lifecycle: entry → hold → exit (TP/SL/MaxHold/PredFlip)
- TP/SL level visualization via `SetupsLib.f_create_tpsl_levels()`
- **Signal Logic**: Breakout markers, MR diamonds, velocity coupling circles
- **Plotting**: Innovation bands, survival zones, predictive MA, baseline MA, cyclic FV
- **Background Coloring**: Entropy-based regime + entropy collapse

### Lines 3600–3710: OSCILLATOR SUBPANE SYSTEM
- SubPane registration (2 panes: MAIN, CORR)
- 6 oscillators registered via `TAUtilityLib.f_register_osc()`:
  - **Pane 0 (MAIN)**: MR, TE
  - **Pane 0 (MAIN)**: BURST (moved from pane 1)
  - **Pane 1 (CORR)**: VEC, CORR, LTF
- Centralized compression via `osc_compression` input
- `f_process_oscs()` → visual values → `plot()` calls

### Lines 3710–3950: DEBUG & DIAGNOSTICS
- TE Pit detection (drop + recovery labels)
- Innovation Z pivot detection with percentile filter
- Debug bitfield encoding (setup code + CLD patterns → single `data_window` plot)
- MC visualization (MAE/MFE micro squares)

### Lines 3950–4284: INFO TABLE, kNN DIAGNOSTICS, TAIL
- **MC Cone State Machine** (realtime tick processing)
- **Info Table**: 9-row summary (Basket, Vector, MR, TE, Vol, Corr, LTF, Load, Position)
- **kNN Feature/State/Confidence Tables** (conditional display)
- kNN diagnostic superpack (data_window plot)

---

## Data Flow Summary

```
Basket Peers (4 assets via request.security)
    │
    ├─→ Returns (r0..r4) ─→ Z-Scores (z0, basket_z) ─→ MR Orthogonalization
    │                                                      ├─→ MR Oscillator → Setups
    │                                                      └─→ PhiLatch/PhiTotal → kNN F6
    │
    ├─→ Correlation (rho) ─→ Soft Dampening ─→ corr_damping ─→ Bands shift
    │                        └─→ rho_z_score ─→ SubPane CORR
    │
    ├─→ Vector Pressure ─→ basket_vec_z ─→ Survival Bands ─→ Zone fills
    │                      └─→ vector_osc_z ─→ SubPane VEC, kNN F1
    │
    ├─→ TE Returns ─→ CausalityLib.f_compute_te_wrapper() ─→ te_osc
    │                                                         ├─→ SubPane TE
    │                                                         └─→ kNN F4
    │
    └─→ LTF Arrays ─→ Kalman Beta ─→ ltf_corr_ema ─→ ltf_rho_z ─→ SubPane LTF
                                                       └─→ Decoupling events → Setups

Innovation Z-Score (from Kalman innovations)
    ├─→ Regime Event Detector (Bounce/MR/TrendChange)
    ├─→ kNN F3
    └─→ BurstScore (F7) ─→ SubPane BURST

kNN Features (F1-F7) ─→ TurboQuant ─→ Hierarchical Tournament ─→ mc_family
                                                                    │
MC Simulation ─→ P10/P50/P90 Cone ─→ Setup Validation (MAE/MFE/RR)
                                       └─→ Label coloring (green/red/gray)
```

---

## Setup Catalog (as of v19)

| ID | Name | Dir | WR% | Family | Gate Summary |
|---|---|---|---|---|---|
| S1 | TE0.8+LTFlow | SHORT | 64.5 | Velocity | TE high + LTF decoupled |
| S5 | LTFlow | SHORT | 60.2 | Velocity | LTF decoupled standalone |
| S6 | MRStrict-0.5 | SHORT | 65.0 | MR | MR < -0.5 + z0 extreme |
| S7 | TE+VecDiv | SHORT | 61.0 | Velocity | TE high + vector bearish + trend up + coupled |
| S8 | SReentry+VecDiv | SHORT | 69.2 | Velocity | Post-pred-short + vector bearish + trend up |
| S9 | CFV+TE+LTFlo | SHORT | 73.0 | Velocity | CFV falling + TE high + LTF decoupled |
| S10 | PredMA+VelDec | SHORT | 61.5 | Velocity | Pred round short + trend fading |
| S11 | LTF+MR+Coupled | SHORT | 70.4 | MR | LTF decoupled + MR > 0.3 + HTF coupled |
| L1 | TE0.8+CFVrise | LONG | – | Transition | TE high + CFV rising |
| L5 | MRStrict+0.5 | LONG | 68.0 | MR | MR > 0.5 + z0 extreme |
| L6 | LReentry+VecDiv | LONG | 70.0 | Transition | Post-pred-long + TE high + LTF recoupled |
| L7 | CFV+TE+LTFhi | LONG | 72.5 | Transition | CFV rising + TE high + LTF coupled |
| L8 | PredMA+VelRec | LONG | 60.0 | Transition | Pred round long + trend rising |
| V1 | BounceFire | LONG | 81.0 | Uncertain | Regime bounce event |
| V2 | MRSetup | SHORT | 73.0 | MR | Regime MR event |
| V3 | Transition | LONG | 75.0 | Transition | Regime trend change event |
| V4 | VelRecouple | LONG | 64.0 | Transition | Velocity recoupling event |
| 81 | CORR⊥+MR | LONG | 81.0 | Uncertain | Correlation bottom + MR confirm |
| 73 | CORR↑+MR | SHORT | 73.0 | Velocity | Correlation peak + MR confirm |
| 75 | BearDiv⊥OS | SHORT | 75.0 | Velocity | Bear divergence in oversold |
| 64 | CLD↗ | LONG | 64.0 | Continuation | CLD fall-rise-up pattern |

---

## Conventions

1. **Input groups**: All inputs use `grp_*` string constants for grouping
2. **Heavy calc guard**: `is_hard_zone` / `calc_active` gates expensive computation to recent `max_heavy_bars`
3. **var vs non-var**: `var` = persistent state across bars; plain `float` = recalculated each bar
4. **varip**: Used only for MC state machine (tick-level state in realtime)
5. **Carry-forward**: Intermittent data (LTF Kalman) uses `if not na(raw) → ema := raw` pattern
6. **SubPane architecture**: `SubPane` → `OscMeta` → `OscState` UDTs manage oscillator visual layout
7. **Centralized compression**: `osc_compression` input controls `f_apply_softclip` method for all oscillators
8. **Debug bitfield**: Setup codes + CLD patterns packed into single `data_window` plot (no extra visual plots)
9. **No globals in functions**: Functions return tuples; caller unpacks with `=` and assigns globals with `:=`
10. **Plot in global scope only**: Conditional visibility via `condition ? value : na`, never `plot()` inside `if`
