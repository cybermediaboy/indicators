# Eugene's Pine Script Principles

> **Axiom #0 — Single Point of Truth (SPoT):** Every architectural decision lives in exactly one place. This file is that place for principles. If any other doc conflicts with an entry here, this file wins.

**Version:** 2026-04-28 | **Gap IDs covered:** G1-G98 | **Indicators surveyed:** 5

---

## §1 — Buffer & Limit Architecture (G1-G6)

### G1 — The Limits Reference Card

Before writing any indicator, internalize all Pine Script hard limits. Hitting any of these mid-build costs a full refactor.

| Limit | Value | Scope |
|-------|-------|-------|
| `max_bars_back` ceiling | 5000 bars | `[]` history reference on any series |
| Default history buffer | 902 bars | `line.get_x1()`, `label.get_x()` age checks via `bar_index` offset |
| Label cap | 500 | Total label objects on chart simultaneously |
| Line cap | 500 | Total line objects on chart simultaneously |
| Array element cap | 100,000 | `array.new*` + push operations |
| Map pairs cap | 50,000 | `map.new*` entries |
| `xloc.bar_index` past | 10,000 bars | Historical line/label placement |
| `xloc.bar_index` future | 500 bars | Forward label/line placement |
| Local scope count | 550 (v5) / unlimited (v6, Feb 2025) | Inline branch scopes |
| Main body lines | ~2000 | Total lines before extraction required |
| Token limit (AST) | 80,000 nodes | Compile-time AST budget |
| `request.security()` calls | 40 | Per-script external data calls |
| Tuple-packed series per call | ~7 | Practical max per `request.security()` call |
| Total accessible series via tuples | ~280 | 40 calls × 7 values |
| `var` declarations | < 500 hard / < 300 practical | Per-script persistent variables |

**G1 related entries:** G6 (heavy-bar gating), G28 (LTF memory), G49 (UDT token cost), G87 (request budget table)

---

### G2 — max_bars_back Declaration

Never set `max_bars_back` on the `indicator()` call globally. Declare it per-series only where needed:
```pine
max_bars_back(mySeriesVar, 500)
```
Global `max_bars_back=N` on the indicator line causes "Too large total max_bars_back" on multi-symbol indicators.

---

### G3 — Label/Line GC (Garbage Collection)

Label and line objects persist until explicitly deleted. Pattern:
```pine
// Create
var label lbl = na
// On update bar:
if not na(lbl)
    label.delete(lbl)
lbl := label.new(...)
```
Never accumulate unbounded. Cap arrays of label refs at 500.

---

### G4 — Array Bounds Guard

Always guard before `array.get()` or `array.set()`:
```pine
if index >= 0 and index < array.size(arr)
    val := array.get(arr, index)
```
Violation causes `RE10045` at runtime with no compile-time warning.

---

### G5 — Parallel Array Constraint

Pine Script has no `array<array<float>>`. Use parallel arrays of equal length:
```pine
var array<float> xs = array.new<float>(0)
var array<float> ys = array.new<float>(0)
// xs[i] and ys[i] are paired
```

---

### G6 — Heavy-Bar Method Fallback

Gate expensive computations to recent bars only. Provide a cheap fallback for history:
```pine
bool in_window = bar_index >= last_bar_index - 500
float result = in_window ? f_expensive(src) : f_cheap(src)
```
Frequency: **5×** across production indicators. Canonical Tier 1 pattern.

---

## §2 — Library Architecture (G7-G14)

### G7 — Library Role Separation

Each library has a strictly bounded role. Cross-contamination requires a migration cycle.

| Library | Role | Must NOT contain |
|---------|------|------------------|
| `MCLib` | Monte Carlo path simulation, percentile bands | Indicator-specific signal logic |
| `MLLib` | KNN classifier, feature normalization | Monte Carlo paths |
| `CausalityLib` | Granger causality, copula, cross-correlation | Rendering, label management |
| `TAUtilityLib` | Label/line rendering, logger, utility UDTs | Statistical computation |

Frequency: **3×** (CMD-Unified, CVB v20, IHD-Osc). Tier 1.

---

### G8 — Library Export Convention

All public functions and types must be prefixed with `export`. UDTs shared across files require `export type` (v6 mandatory):
```pine
export type BandResult
    float upper
    float lower
    float mid
```

---

### G9 — Library Self-Containment

Libraries must not depend on other libraries in this repo. Copy required helper functions directly into the library that needs them. Eliminates circular-dependency and uncommitted-lib compile failures.

---

### G10 — Logger Architecture (TAUtilityLib)

Three flush modes — never mix them:
- `BUFFERED`: auto-flush at ~4000 chars or ≥2500 lines. No `barstate.islast`.
- `PER_BAR`: flush on `barstate.isconfirmed`.
- `EXPLICIT`: manual `flush()` at natural boundaries.

`barstate.islast` is **not** a flush trigger. Anti-pattern: wiring `if barstate.islast then logger.flush()` as primary mechanism.

---

### G11 — UDT Instance Token Cost

Each UDT instance = 1 `var` slot. But each field access `obj.field` = 3 AST tokens vs 1 for a flat variable. In hot paths (loops, heavy formulas), extract fields to locals first:
```pine
// Hot path — extract once
float b0 = band.b0
float b1 = band.b1
float pred = b0 + b1 * x  // 2 tokens, not 6
```
See G49 for token budget details.

---

### G12 — Library Update Protocol

Never edit a library file directly in production. Follow the 4-stage protocol in `LIBRARY_UPDATE_INSTRUCTIONS.md`:
1. Branch / isolate change
2. Update library
3. Verify all consumers compile
4. Migrate consumers with updated import

---

### G13 — Export Type Migration

When adding a new field to an exported UDT, all consumers that unpack that type must be updated in the same migration cycle. Stale consumers cause "type mismatch" errors that are non-obvious.

---

### G14 — Library Version Pinning

Use explicit version numbers in library imports:
```pine
import cybermediaboy/TAUtilityLib/4 as TAUtil
```
Never import without version. Unpinned imports break silently when the library is updated.

---

## §3 — Variable & Scope Rules (G15-G27)

### G15 — Declaration Before Use (Single-Pass Compiler)

Pine Script is single-pass top-to-bottom. Every variable must be declared before any code that references it. No forward declarations exist.

```pine
// WRONG
if condition
    result := myVar  // Error: undeclared
float myVar = 0.0   // declared after use

// CORRECT
float myVar = 0.0
if condition
    result := myVar
```
Frequency: **4×**. Tier 1.

---

### G16 — `var` Persistence Semantics

`var` = persists across bars (initialized once on bar 0).  
Without `var` = recalculated every bar from scratch.  
Mixing up the two causes accumulator drift or stale-value bugs.

```pine
var float cumulative = 0.0  // persists — accumulator
float snapshot = close      // recalculated each bar
```

---

### G17 — No Global Mutation Inside Functions

Functions must not modify global `var` variables directly. Return a tuple; unpack at global scope with `:=`:
```pine
// WRONG
f_update() =>
    globalVar := globalVar + 1  // mutation of global — undefined behavior

// CORRECT
f_update(float current) =>
    current + 1
globalVar := f_update(globalVar)
```

---

### G18 — Plot Scope (Never Inside `if`)

`plot()`, `plotshape()`, `plotchar()`, `hline()`, `bgcolor()` must be at global scope. Use ternary to suppress:
```pine
// WRONG
if showLine
    plot(value)  // compile error

// CORRECT
plot(showLine ? value : na)
```
Frequency: **4×**. Tier 1.

---

### G19 — `hline()` Constant Price Only

`hline()` requires `input float` (compile-time constant). Cannot accept a `series float`.
```pine
hline(0.0)           // OK
hline(input.float(0.0, "Level"))  // OK
hline(ta.sma(close, 20))          // COMPILE ERROR
```
To draw a dynamic horizontal line, use `line.new()` with `extend.right`.

---

### G20 — Tuple Unpacking Syntax

No type annotations inside tuple brackets. Declare first, then unpack:
```pine
// WRONG
[float a, float b] = f_returns_tuple()  // syntax error

// CORRECT
float a = na
float b = na
[a, b] := f_returns_tuple()
```

---

### G21 — Variable Declared in `if` Block Used in `plot()`

`plot()` executes at global scope every bar. Variables declared inside conditional blocks are invisible to it:
```pine
// WRONG
if condition
    float myVal = calculate()  // local scope only
plot(myVal)  // Error: undeclared

// CORRECT
float myVal = 0.0  // declare at script level
if condition
    myVal := calculate()  // assign with :=
plot(myVal)  // visible
```
Frequency: **2×** (batch #27, traj 1.1). Tier 1.

---

### G22 — `varip` Counter Drift

`varip` variables update intra-bar on every tick. On chart reload or timeframe change, `varip` counters reset while `var` counters persist, causing divergence. Use on-demand aggregation instead of `varip` tick-counters for anything that must survive a reload.

---

### G23 — On-Demand Aggregation Pattern

Instead of incrementing a `varip` counter every tick, compute the aggregate lazily on demand:
```pine
// WRONG: varip drifts on reload
varip int tick_count = 0
tick_count += 1

// CORRECT: compute when needed
int bars_since = ta.barssince(condition)
```
Frequency: **2×**. Tier 1.

---

### G24 — Label Create-or-Update (RTL Pattern)

For right-to-last-bar labels that must persist and update:
```pine
var label lbl = na
if barstate.islast
    if na(lbl)
        lbl := label.new(bar_index, high, text, ...)
    else
        label.set_text(lbl, text)
        label.set_x(lbl, bar_index)
```
Never create a new label every bar — exhausts the 500-label cap in ~500 bars.
Frequency: **3×**. Tier 1.

---

### G25 — Single-Render-State UDT Fields

UDT fields that hold render state (label refs, line refs) must use the `*_final` suffix convention to signal they are only valid after the render pass:
```pine
type SetupState
    float signal
    label label_final  // only valid after f_render()
```

---

### G26 — `export type` for Cross-File UDTs (v6)

In Pine Script v6, UDTs shared across script + library boundaries require `export type`. Without it, the consumer sees `unknown type` errors even if the function signature is otherwise correct.

---

### G27 — No Nested Arrays

Pine Script v5/v6 does not support `array<array<T>>`. Use parallel flat arrays or a flat array with manual stride:
```pine
// Simulating 3-column matrix with stride 3
var array<float> mat = array.new<float>(rows * 3, 0.0)
// Access row r, col c:
array.get(mat, r * 3 + c)
```

---

## §4 — Type System Rules (G28-G36)

### G28 — `series int` vs `input int` for Plot Parameters

`linewidth` and `style` in `plot()` require `input int` (compile-time constant). Conditional expressions return `series int`. Fix: wrap with `math.max(1, ...)`:
```pine
// WRONG
linewidth=condition ? 2 : 1  // series int — compile error

// CORRECT
linewidth=math.max(1, condition ? 2 : 1)  // input int compatible
```
Frequency: **4×** (CVB v1, IHD-Osc, batch #2.1, traj #1.1). Tier 1.

---

### G29 — Consistent Return Types Across `if` Branches

All `if` branches in a function must return the same type. Wrap literal returns with `float()`:
```pine
// WRONG
f_calc() =>
    if condition
        0.0          // literal float
    else
        ta.sma(close, 20)  // series float — type mismatch

// CORRECT
f_calc() =>
    if condition
        float(0.0)   // explicit series float
    else
        ta.sma(close, 20)
```

---

### G30 — `nz()` Cannot Wrap Bool

`nz()` is for numeric types only. Never pass a `bool` to it:
```pine
// WRONG
int count = nz(myBool)  // compile error

// CORRECT
int count = myBool ? 1 : 0
// or
int count = na(myBool) ? 0 : myBool ? 1 : 0
```

---

### G31 — `ta.linreg` / `ta.ema` Require Simple Int Length

Both functions require a `simple int` length — not a conditional or series value. Pre-calculate both variants and use ternary on the result:
```pine
// WRONG
float result = ta.ema(src, condition ? len1 : len2)  // series int — error

// CORRECT
float r1 = ta.ema(src, len1)
float r2 = ta.ema(src, len2)
float result = condition ? r1 : r2
```

---

### G32 — `ta.correlation` Requires `int` Length

`ta.correlation(x, y, length)` — length must be `int`, not `float`. Even `float(100)` fails:
```pine
// WRONG
float len = 100.0
ta.correlation(a, b, len)  // type error

// CORRECT
int len = 100
ta.correlation(a, b, len)
```

---

### G33 — `array.sort` Named Arguments

Pine v5/v6 `array.sort` requires named arguments to avoid type inference ambiguity:
```pine
// WRONG (positional — may fail)
array.sort(myArr, order.ascending)

// CORRECT
array.sort(id=myArr, order=order.ascending)
```

---

### G34 — `ta.covariance` Does Not Exist

Pine Script v5/v6 has no `ta.covariance()`. Calculate manually:
```pine
float EXY = ta.sma(x * y, length)
float EX  = ta.sma(x, length)
float EY  = ta.sma(y, length)
float cov = EXY - EX * EY
```

---

### G35 — `math.clamp()` Does Not Exist

```pine
// WRONG
math.clamp(value, lo, hi)  // function doesn't exist

// CORRECT
math.max(lo, math.min(value, hi))
```

---

### G36 — `math.random()` Does Not Exist

Use a deterministic pseudo-random substitute:
```pine
float pseudo_rand = math.sin(bar_index * 12.9898 + time * 78.233) * 43758.5453
float rand_0_1 = pseudo_rand - math.floor(pseudo_rand)
```

---

## §5 — Syntax & Structure Rules (G37-G47)

### G37 — No Comma-Separated Statements

Each statement must be on its own line. Comma-separated statements are a syntax error:
```pine
// WRONG
array.push(a, v1), array.push(b, v2)  // syntax error

// CORRECT
array.push(a, v1)
array.push(b, v2)
```

---

### G38 — No Comma-Separated Void Function Calls

Void functions (like `array.pop()`) cannot be chained with comma. Each void call is a separate statement.

---

### G39 — For Loop Step Must Be > 0

Pine Script `for` loops only support positive step. For descending iteration, reverse bounds:
```pine
// WRONG
for i = maxVal to minVal by -1  // runtime error: step must be > 0

// CORRECT
for i = minVal to maxVal  // iterate ascending, invert logic inside
```

---

### G40 — Multi-Line Ternary

Multi-line ternary operators require explicit continuation or single-line format:
```pine
// WRONG (inline comment breaks continuation)
bool x = condition1 ? val1  // comment here breaks it
                    : val2

// CORRECT (no comment mid-ternary)
bool x = condition1 ? val1 : val2
```

---

### G41 — `plotshape` First Argument: `false` Not `na` for Bool Series

When passing a `bool` series to `plotshape`, use the bool directly (or `false` to hide). Using `na` where a `bool` is expected causes type errors:
```pine
plotshape(myBoolSeries, ...)           // correct
plotshape(showPlot ? myBool : false, ...)  // correct hide pattern
```

---

### G42 — N×M Oscillator Mode Dispatch

For indicators with N oscillator modes and M rendering modes, use a string-dispatch pattern rather than branchy if/else trees. A `switch` block or a map of mode → function reference keeps scope count manageable.

---

### G43 — Hypothesis-Mode Dispatch

For indicators with multiple operating hypotheses (e.g. "Catch-up" vs "Gravity Reversion"), wire the dispatch via `input.string()` with `options=[...]`. Centralizes the branch at the input level, not scattered throughout the calculation.

---

### G44 — Periodic Rescan Idiom

For tasks that must re-execute periodically without blocking every bar:
```pine
var int last_scan = 0
bool do_scan = bar_index - last_scan >= SCAN_INTERVAL
if do_scan
    // heavy work
    last_scan := bar_index
```

---

### G45 — Rolling Percentile Adaptive Threshold

Use `ta.percentile_nearest_rank()` for dynamic thresholds that adapt to regime:
```pine
float thr_p90 = ta.percentile_nearest_rank(signal, lookback, 90)
float thr_p20 = ta.percentile_nearest_rank(signal, lookback, 20)
bool strong_signal = signal > thr_p90
bool weak_signal = signal < thr_p20
```

---

### G46 — RTH Session State Machine

For CME/equity session-aware logic, maintain a session state variable updated on `timeframe.change("D")`:
```pine
var bool in_rth = false
bool new_day = timeframe.change("D")
if new_day
    in_rth := (hour(time, "America/New_York") >= 9 and hour(time, "America/New_York") < 16)
```

---

### G47 — Sub-Pane Plot Gating

For indicators with optional sub-panes, gate all `plot()` calls with visibility booleans. Never add/remove `plot()` calls based on user input — Pine requires a fixed number of plot calls per script execution:
```pine
plot(show_osc ? oscillator_val : na, "Oscillator")
```

---

## §6 — Performance & Dimensional Sanity (G48-G60)

### G48 — Normalize to ATR Before Squaring Price

When squaring price-based values (kinetic energy, momentum²), normalize to ATR first to prevent dimensional explosion:
```pine
// WRONG: price² → millions, bands invisible
float ke = velocity * velocity

// CORRECT: normalize first
float atr = ta.atr(14)
float vel_norm = velocity / math.max(atr, 1e-6)
float ke_norm = vel_norm * vel_norm * atr  // back in price space
```
Frequency: **2×** (batch #6.1, traj). Tier 1.

---

### G49 — UDT Dot-Notation Token Cost

Each `obj.field` access = 3 AST tokens. Each flat variable = 1 token. In hot paths:
```pine
// Token-heavy (15 tokens for 5 accesses in formula)
float pred = b.b0 + b.b1*x + b.b2*x2 + b.b3*x3 + b.b4*x4

// Token-efficient (5 extractions + 5 flat refs = 10 tokens total)
float b0=b.b0, b1=b.b1, b2=b.b2, b3=b.b3, b4=b.b4
float pred = b0 + b1*x + b2*x2 + b3*x3 + b4*x4
```

---

### G50 — Kalman P11 Dimensional Collapse

`sqrt(P11)` produces normalized uncertainty (0.1–1.5 range). Adding it directly to BTC price (~73,000) gives invisible 0.5-wide bands. Must scale by ATR:
```pine
float kf_std = math.sqrt(math.max(kf_p11, 0.0))
float price_scale = math.max(ta.atr(100), 1e-6)
float uncertainty = kf_std * price_scale  // now in price units
```

---

### G51 — Z-Score-Space Kalman

Run the Kalman filter in normalized Z-score space ([-3, 3]) rather than price space. Project back to price via `ma + kf_pos * dev`. Domain-invariant: works on any asset at any price scale.
```pine
float kf_fv_price = ma0 + kf_pos * dev0
float kf_upper    = kf_fv_price + kf_std * dev0
```

---

### G52 — Dead Code Token Waste

Unused function definitions still consume tokens. Audit before hitting the 80k limit:
```pine
// Remove any function that has zero call sites in the script
// Search: define the function name, count occurrences — if count == 1 (definition only), delete
```

---

### G53 — `fixnan()` for Weekend/Gap NA Propagation

EMA/SMA chains on markets with gaps (traditional assets, weekends on some feeds) propagate `na` through all downstream calculations. Guard:
```pine
float clean = fixnan(ta.ema(src, len))  // replaces na with last valid value
```

---

### G54 — Synthetic Log Ratio Initialization

Accumulator variables initialized to `0` cause `exp(0) = 1`, breaking scale in ratio calculations. Initialize to the actual first-bar value:
```pine
var float log_ratio = na
if na(log_ratio)
    log_ratio := math.log(close / basket_ref)  // actual first-bar value
else
    log_ratio += delta
```

---

### G55 — Max Lookback Cap for Lower Timeframes

Dynamically computed lookbacks (`days × bars_per_day`) can exceed the 5000-bar history limit on low timeframes (5m: 288 bars/day → 20 days = 5760 > 5000):
```pine
int MAX_LOOKBACK = 4900  // safety margin
int lookback = math.min(MAX_LOOKBACK, math.max(20, math.round(days * bars_per_day)))
```

---

### G56 — Replay Mode Compatibility

`last_bar_index` does not update correctly in TradingView replay mode. Use `barstate.islast` as the primary guard:
```pine
bool in_calc_window = barstate.islast or (last_bar_index - bar_index < 2000)
```

---

### G57 — `barstate.islastconfirmedhistory` for Early Checks

For checks needed before user-defined flags are declared, use the built-in namespace which is always available:
```pine
// Use instead of a user-defined isHistoryEdge that may not be declared yet
if array.size(buffer) > 3000 or barstate.islastconfirmedhistory
    // flush or trim
```

---

### G58 — `location.absolute` Only for Overlay Indicators

`location.absolute` in `plotshape` expects a price series and only works correctly when `overlay=true`. For indicator panes, use `location.bottom` or `location.top`:
```pine
plotshape(cond, location=location.bottom, ...)  // correct for pane indicator
```

---

### G59 — `syminfo.timezone` ≠ User Local Time

`syminfo.timezone` returns the exchange timezone, not the user's local timezone. For session-based time checks, use a named timezone string:
```pine
hour(time, "America/New_York")  // explicit, not syminfo.timezone
```

---

### G60 — `ignore_invalid_symbol=true` in `request.security()`

Always set `ignore_invalid_symbol=true` when the ticker comes from `input.string()` (user-editable):
```pine
request.security(userTicker, timeframe.period, close, ignore_invalid_symbol=true)
```
Without it, an invalid user-entered ticker hard-crashes the entire indicator.

---

## §7 — Domain Init & Lifecycle (G61-G70)

### G61 — Domain Init Pattern (Kalman/EMA Seeded State)

For stateful filters, use `na` as sentinel and initialize from real data on first valid bar:
```pine
var float kf_pos = na
if na(kf_pos)
    kf_pos := target_z  // seed from actual data, not 0.0
```
Avoiding `0.0` initialization prevents transient convergence artifacts on first bars.

---

### G62 — Label Lifecycle: Ref + Reset + Delete + Nullify

Complete lifecycle for a managed label:
```pine
var label lbl = na
// On condition:
if not na(lbl)
    label.delete(lbl)
    lbl := na          // nullify — prevents double-delete
lbl := label.new(...)  // create new
```

---

### G63 — Matrix Init in `barstate.isfirst` Block

Matrix variables must be initialized in the `barstate.isfirst` block, not at declaration time, to avoid "matrix cannot be initialized outside of a function" errors:
```pine
var matrix<float> m = na
if barstate.isfirst
    m := matrix.new<float>(rows, cols, 0.0)
```

---

### G64 — Separate Scalar / Tuple Return Variants

If a function sometimes needs to return a scalar and sometimes a tuple, create two separate functions. Pine cannot return inconsistent arity:
```pine
f_kalman_pos()    => float         // scalar variant
f_kalman_state()  => [float, float]  // tuple variant
```

---

### G65 — `request.security_lower_tf` Single-Ticker Mode

`request.security_lower_tf` cannot accept a `series string` ticker. Use a fixed ticker or separate calls per ticker:
```pine
// WRONG
request.security_lower_tf(dynamicTicker, "1", close)

// CORRECT
request.security_lower_tf(syminfo.tickerid, "1", close)
```

---

### G66 — `var array<T>` in Nested Blocks Within Functions

Arrays declared with standard `array.new<T>` inside functions may not be accessible in nested conditional blocks within loops. Use `var array<T>` + `array.clear()`:
```pine
var array<float> scratch = array.new<float>(0)
// In function body:
array.clear(scratch)  // reset instead of redeclare
```

---

### G67 — Progressive Array Initialization (MC)

Arrays declared with `array.new<float>(0)` remain empty until populated. Accessing before population causes `RE10045`. Either initialize with default values or guard:
```pine
// Initialize with defaults
var array<float> mc = array.new<float>(100, 0.0)
// OR guard access
if array.size(mc) > 0
    float val = array.get(mc, 0)
```

---

### G68 — Forward Declaration + Redeclaration = "Already Defined"

Declaring a variable as a forward placeholder and then re-declaring it later causes "already defined" error. Keep only one declaration:
```pine
// WRONG
var float ortho = 0.0  // forward declaration
// ... 50 lines later ...
var float ortho = 0.0  // Error: already defined

// CORRECT: one declaration, := for updates
var float ortho = 0.0
// ... later ...
ortho := new_value
```

---

### G69 — `input.options` Cannot Accept Array Variable

`input.string(options=[...])` requires a literal array in the function call. Cannot pass an `array<string>` variable:
```pine
// WRONG
array<string> opts = array.from("A", "B")
input.string("A", options=opts)  // error

// CORRECT
input.string("A", options=["A", "B"])  // literal only
```

---

### G70 — No Nested `request.security()`

`request.security()` calls cannot be nested. Fetch data in separate top-level calls:
```pine
// WRONG
float val = request.security(sym, tf, request.security(sym2, tf, close))

// CORRECT
float inner = request.security(sym2, tf, close)
float outer = request.security(sym, tf, inner)
```

---

## §8 — Visualization Rules (G71-G80)

### G71 — Bandwidth Color-Transition State Machine

For expansion/contraction visual feedback, use a persistent state accumulator with clamped increment:
```pine
var float effect_state = 0.0  // -1.0 = full contraction, 1.0 = full expansion
if is_expanding
    effect_state := math.min(1.0, effect_state + fade_rate)
else if is_contracting
    effect_state := math.max(-1.0, effect_state - fade_rate)
color active = effect_state >= 0
    ? color.from_gradient(effect_state, 0.0, 1.0, base_color, exp_color)
    : color.from_gradient(effect_state, -1.0, 0.0, contr_color, base_color)
```

---

### G72 — Hierarchical Plot Gating

Gate plots at two levels — category enable + individual enable — to manage visual clutter:
```pine
plot(show_derived and show_oi_delta ? oi_delta_hist : na, "OI Delta")
```

---

### G73 — Confidence → Transparency Mapping

Map signal confidence (0.0–1.0) to color transparency for progressive visual strength:
```pine
int alpha = math.round(90 - 70 * confidence)  // 90 = invisible, 20 = opaque
alpha := math.max(0, math.min(100, alpha))
color sig_color = color.new(color.lime, alpha)
```

---

### G74 — 4-Quadrant Fill Gating

For band fill opacity driven by signal-confidence quadrant:
```pine
bool strong_bull = slope_up and mr_bull
bool weak_bull   = slope_up and not mr_bull
int fill_alpha = strong_bull ? strong_fill_transparency : fill_transparency
color fill_col = slope_up
    ? color.new(color.lime, fill_alpha)
    : color.new(color.gray, 95)
```

---

### G75 — Adaptive R from Agreement EMA

For Kalman filters, modulate measurement noise R from a directional agreement EMA:
```pine
float agreement = ta.ema(basket_dir == price_dir ? 1.0 : 0.0, agree_len)
float R = R_max - (R_max - R_min) * math.max(0.0, math.min(1.0, (agreement - 0.5) / 0.5))
```

---

### G76 — `plotchar` Single Character Only

`plotchar()` `char` parameter accepts exactly one character, not a string:
```pine
plotchar(cond, char="▲")  // OK (single char)
plotchar(cond, char="UP") // Error: only single char allowed
```

---

### G77 — `barcolor()` Has No `force_overlay` Parameter

Remove `force_overlay` from `barcolor()` calls — the parameter does not exist:
```pine
barcolor(my_color)  // correct
barcolor(my_color, force_overlay=true)  // compile error
```

---

### G78 — `plotshape` with `location.absolute` Needs Series Price

When using `location.absolute`, pass a `series float` price series (not `na`) as the `style` source. For indicator-pane use `location.bottom` instead.

---

### G79 — `math.is_finite()` Does Not Exist

```pine
// WRONG
math.is_finite(x)

// CORRECT
not na(x) and math.abs(x) < 1e300
```

---

### G80 — `bgcolor()` Has No `force_overlay` or `transp` Alias

```pine
bgcolor(color.new(color.red, 90))  // correct: alpha in color.new()
bgcolor(color.red, transp=90)      // old v4 syntax — error in v5/v6
```

---

## §9 — Data Access & Request Rules (G81-G93)

### G81 — `request.security()` Budget Accounting

Budget: 40 calls × ~7 tuple-packed values = ~280 accessible series.

Standard allocation for a CME BTC intraday indicator:
| Calls | Symbol | Values |
|-------|--------|--------|
| 1–2 | CME:BTC1! | O,H,L,C,V,OI,hlc3 (7) |
| 3–4 | BINANCE:BTCUSDT | O,H,L,C,V,hlc3,hl2 (7) |
| 5–6 | COINBASE:BTCUSD | O,H,L,C,V,hlc3,hl2 (7) |
| 7–8 | BYBIT:BTCUSDTPERP | C,V (2) |
| 9 | BINANCE:BTCUSDT.P_OI | close (1) |
| 10 | BYBIT:BTCUSDT.P_OI | close (1) |
| 11 | DERIBIT:DVOL | close (1) |
| 12 | BINANCE:BTCUSDT_PREMIUM | close (1) |
| 13–14 | BTCUSDLONGS / SHORTS | close (1 each) |
| 15–16 | `request.footprint()` | buy/sell vol (6) |

Total: ~16 calls / ~34 series. Leaves ~24 calls / ~246 values for expansion.

---

### G82 — Tier-Fallback Dispatch for Plan-Restricted Features

For Premium-gated features (e.g. `request.footprint()`), provide graceful 3-tier fallback:
```pine
// Tier 1: Premium — true buy/sell delta
// Tier 2: Any plan — BVC (Gaussian CDF) 89–94% accuracy
// Tier 3: Any plan — CLV (close location value) 70–80% accuracy
bool use_footprint = input.bool(false, "Use Footprint (Premium+)")
float delta = use_footprint ? fp.delta() : delta_bvc
```

---

### G83 — Live-Only Realtime Data Integration

`syminfo.bid` / `syminfo.ask` are realtime-only on `1T` timeframe — no historical data. Implement as live-overlay label only, never wire into historical regression:
```pine
if barstate.islast and not na(spread_usd)
    label.new(bar_index, high, "Spread: $" + str.tostring(spread_usd, "#.##"), ...)
// DO NOT: plot(spread_usd) — would be na on all historical bars
```

---

### G84 — `request.footprint()` (v6 Jan 2026, Premium+)

Added January 2026. Returns true buy/sell volume by price level:
```pine
var fp_data = request.footprint(100)  // 100 ticks per row
float delta = fp_data.delta()         // buy_vol - sell_vol
float poc   = fp_data.poc()           // point of control
float vah   = fp_data.vah()           // value area high
float val   = fp_data.val()           // value area low
```
Requires Premium or Ultimate plan. Degrade to BVC (G82) without it.

---

### G85 — Weighted Composite with IC-Tuning Convention

Document composite weights as starting points with explicit IC-tuning note:
```pine
// Weights: starting points. Optimize via forward-return IC analysis.
float composite = 0.30 * basis_z
              + 0.25 * oi_dir_z
              + 0.25 * cb_prem_z
              + 0.20 * (-iv_rv_z)  // negative: fear is contrarian short-term
```

---

### G86 — Signal Card Schema (Per-Indicator Header)

Document each output signal with a signal card in the indicator header comment:
```pine
// Signal Cards:
// inv_z   | Basis: price impact residual via BVC regression | IC≈0.028 h=1 | Role: core invisible flow
// inst_z  | Basis: CME basis + OI + CB premium + DVOL       | IC≈0.062 h=8 | Role: institutional positioning
// dvol_regime | Basis: DVOL pctile + IV-RV spread           | IC: N/A      | Role: regime gate
```

---

### G87 — v6-Only Features Cookbook

Features exclusive to Pine Script v6 (do not use in v5 code):
- `request.footprint()` — true buy/sell volume by price level (Premium+, Jan 2026)
- `export type` — cross-file UDT sharing (required)
- Maps (`map.new<K,V>()`) — key-value storage
- Enums — `enum Regime { HIGH_VOL, LOW_VOL, TRENDING, RANGING }`
- `runtime.log()` — non-chart debug output
- Dynamic requests in `for` loops — each unique `(symbol, TF)` = 1 call
- `request.security_lower_tf()` — intrabar LTF data with array return
- Unlimited local scope count (was 550 in v5)

---

### G88 — Compiler Error Parsing Schema (Automation)

TV Pine Editor console error format:
```
"HH:MM:SS AM/PM Error at LINE:COL MESSAGE"
```
Parse to structured JSON for AI-coder pipelines:
```python
{ "line": 4, "col": 11, "message": "Undeclared identifier 'foo'", "type": "compiler" }
```

---

### G89 — Runtime Error 3-Source Detection Matrix

Single-source detection misses ~30% of TV runtime errors. Check all three:
1. Legend status buttons: `button[title*="Runtime error"]`
2. Data problem icons: `span[class*="dataProblem"]`
3. Toast notifications: `[data-name*="toast"][data-name*="warning"]`

---

### G90 — `domcontentloaded` Over `networkidle` for TV Automation

TradingView never reaches `networkidle` due to persistent WebSocket connections. Use:
```python
page.wait_for_load_state("domcontentloaded", timeout=30000)
page.wait_for_timeout(5000)  # settle time for chart render
```

---

### G91 — Clipboard Paste Over `keyboard.type()` for TV Automation

`keyboard.type()` sends ~300,000 keystroke events for a large indicator (10+ minutes). Use clipboard:
```python
page.evaluate(f"navigator.clipboard.writeText({json.dumps(pine_code)})")
page.keyboard.press("Meta+v")
# Result: 2-3 seconds vs 10+ minutes
```

---

## §10 — Naming & Convention Rules (G92-G98)

### G92 — Function Naming Convention

```
f_<verb><Noun>()    — regular function
f_render<Widget>()  — rendering function (must only call plot/label/line)
f_calc<Signal>()    — pure calculation, no side effects
f_update<State>()   — state mutation, returns new value
```

---

### G93 — Variable Naming Convention

```
snake_case           — all variables
ALL_CAPS             — constants (compile-time)
grp_<name>           — input group strings
GRP_<NAME>           — input group constants
_final suffix        — render-state fields in UDTs (only valid post-render)
_z suffix            — z-scored signals
_pct suffix          — percentage values
_n suffix            — normalized [0,1] values
```

---

### G94 — Gap ID Inline Comment Convention

When applying a fix from the error cookbook, add the Gap ID as an inline comment:
```pine
linewidth=math.max(1, condition ? 2 : 1)  // G28: series int → input int via math.max
```
This creates a traceable link between production code and documentation.

---

### G95 — Edition Naming Convention

Edition identifiers follow the pattern:
```
<IndicatorShortName> v<N> <descriptor>
```
Examples: `CVB v20 setupsDB`, `CVB v19 kNN+ConeFilter`  
The descriptor is 1-3 words summarizing the edition's primary new feature.

---

### G96 — Dual Compilation Mode Workflow

For AI-coder pipelines, use two-phase validation:
- **`compile` mode** (~30s): compiler errors only
- **`full` mode** (~2-3min): compile + 8s chart load + runtime scan

Never ship without passing both phases.

---

### G97 — `var` Count Audit Procedure

Before submitting a large indicator:
1. `grep -c "^var " indicator.pine` — count `var` declarations
2. Target: < 300. Hard limit: < 500.
3. If > 300: extract to functions (removes local `var` from main body count), convert non-persistent `var` to plain declarations.

---

### G98 — Reserved Keywords as Variable Names

Never use Pine reserved keywords as variable names:
```
var, float, int, bool, color, string, line, label, table,
array, matrix, map, box, chart, strategy, indicator, library
```
Reserved keyword as variable name produces cryptic "unexpected token" errors.

---

*Generated 2026-04-28 from 5 production indicators + 3 error batches + trajectory 3c7c97da*  
*G1-G98 complete. Tier 1: G1,G6,G7,G15,G18,G21,G23,G24,G28,G29,G31,G32,G33,G48,G50,G51,G55,G56,G61,G62,G63,G66,G67,G68,G74,G75,G81,G82,G83,G84,G85,G86,G88,G89,G91,G94,G96,G97*
