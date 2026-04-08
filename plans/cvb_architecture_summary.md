# CVB (Combined Vector Bands) v19 Architecture Summary

## Overview
**CVB v19** is a sophisticated Pine Script trading indicator (4316 lines) that combines machine learning techniques with traditional technical analysis for cryptocurrency trading signals.

---

## Core Architecture

### 1. **kNN+MC Engine** (`kNNLib.pine`)
- **Lloyd-Max TurboQuant Encoding**: 24-bit packed vector (6 features × 4 bits each)
- **Hierarchical Tournament Selection**: 4-tier priority system (T1-T4)
  - T1: Same family + oracle trigger
  - T2: Same setup + same family
  - T3: Same family
  - T4: Catch-all (6x larger pool)
- **Hamming Screening**: Filters neighbors by feature distance (>1 level difference)
- **Decluster Gap**: Minimum bar spacing between accepted neighbors
- **Antithetic Variates**: Paired MC paths for variance reduction

### 2. **Monte Carlo Simulation** (`MCLib.pine`)
- **Welford Algorithm**: Online mean/variance calculation (numerically stable)
- **kNN Path Resampling**: Bootstrap from historical kNN neighbors
- **Chunked Execution**: Progressive cone building across ticks
- **Adaptive Horizon**: Direction-aware truncation based on MFE/MAE × directional consensus
- **Percentile Output**: P10/P50/P90 projection bands

### 3. **Causality Analysis** (`CausalityLib`)
- **Transfer Entropy (TE)**: Measures information flow from basket to asset
  - 3D contingency table: P(Y_future | Y_past, X_past)
  - Discretization via fixed boundaries
  - Laplace smoothing (α=0.001)
- **Shannon Entropy**: Regime detection (trend vs chaos)
- **Granger Causality**: Legacy support

### 4. **Basket System** (`BasketLib.pine`)
- **Auto Scan**: Ranks 10 candidates by correlation score
  - 70% raw + 30% EMA-smoothed correlation
  - Filters self-references and negative correlations
- **Preset Baskets**:
  - Basket B (Memes): DOGE, SHIB, BONK, SOL
  - Basket C (DeFi + New L1): ETH, SOL, APT, BNB
  - Basket D (Universal 5): ETH, SOL, DOGE, APT, BNB
  - Basket E (TON Niches): ETH, BTC, TON, AVAX
- **Basket Fit**: Average correlation as quality metric (0-100%)

### 5. **Setup Database** (`SetupsLib.pine`)
- **5 Family Classifications**:
  - 0: Continuation (CONT)
  - 1: Mean Reversion (MR)
  - 2: Transition (TRAN)
  - 3: Velocity (VEL)
  - 4: Uncertain (UNC)
- **Setup Types**:
  - **L1-L9**: Long setups
  - **S1-S12**: Short setups
  - **V1-V4**: Velocity setups
  - **Numeric**: 81, 73, 75, 64 (specialized setups)
- **Showstopper Masks**: Block setups when conditions violated
- **Edge Ratios**: Win rate adjustment per setup

### 6. **Technical Utilities** (`TAUtilityLib`)
- **Kalman Filters**: State-space modeling with adaptive Q/R
- **SubPane Architecture**: Managed oscillator layout
- **Oscillator System**: 6 oscillators (MR, TE, VEC, CORR, LTF, BURST)
- **Percentile Normalization**: IQR-based adaptive thresholds
- **Fractal Detection**: Liquidity sweep tracking

---

## Key Components in Main Indicator

### A. **Input Parameters** (~100+ inputs)
1. **Display Controls**: Simple mode, table visibility, signal types
2. **Basket Settings**: Preset selection, weighting mode, auto-scan
3. **Model Settings**: Basis length, Z-score lookback, vector sensitivity
4. **Kirschenbaum Learning**: SGD adaptive sensitivity, VWAP rejection
5. **Survival Zones**: Z1/Z2/Z3 probability thresholds
6. **Correlation Filter**: Decoupling detection, thresholds
7. **CLD**: Fall-rise/rise-fall pattern detection
8. **LTF Tracking**: Lower timeframe correlation
9. **MC Settings**: Horizon, runs, noise scale, chunking
10. **Backtest**: Validation parameters

### B. **Core Calculations**

#### 1. **Basket Vector (PVB-style)**
```pine
v_i = z_score_correlation(asset_i, basket_i, len_z)
basket_vec_z = average(v_i) excluding self-references
```

#### 2. **Survival Bands**
```pine
shift_z = basket_vec_z × sens_final
Z1/Z2/Z3 bands via BandsLib.f_calc_survival_bands()
```

#### 3. **Mean Reversion Orthogonalization**
- **Level 1**: Pairwise phase-aware spread (residual = z0 - ρ·z_peer)
- **Level 2**: Exponential accumulators (λ=0.80)
- **Level 3**: Gram-Schmidt orthogonalization (Cholesky)
- **Level 4**: Raw aggregate (no correlation normalization)

#### 4. **Transfer Entropy**
- Windowed TE calculation (100 bars, 3 bins)
- Pit detection: Sharp TE drops (manipulation warning)
- Regime-switched normalization

#### 5. **kNN Tournament**
- 7 orthogonal features:
  1. VectorOsc (F1)
  2. BasketCorr (F2)
  3. InnovZ (F3)
  4. TE_Osc (F4)
  5. OrthoZcvb (F5)
  6. PhiDiv (F6)
  7. BurstScore (F7)
- Lloyd-Max quantization → 24-bit packed vector
- Hierarchical 4-tier selection with decluster gating

#### 6. **Monte Cone**
- Welford kNN bootstrap (5000 runs, antithetic)
- Adaptive horizon selection
- P10/P50/P90 percentile projection
- Chunked execution (50 runs/tick)

### C. **Setup Detection**
- **19 Setup Types**: L1-L9, S1-S12, V1-V4
- **Correlation Setups**: 81 (CORR_BOTTOM+MR), 73 (CORR_PEAK+MR), 75 (BEAR_DIV), 64 (CLD)
- **Regime Event Detector**:
  - Event 1: Trend Continuation Bounce
  - Event 2: Mean Reversion Setup (L6 multi-scale)
  - Event 3: Trend Change (CUSUM + innovation biased)
- **CLD Patterns**:
  - Green Diamond: Fall-rise continuation (97%)
  - Red Cross: Rise-fall exhaustion (76%)

### D. **Visualization**
- **Survival Zones**: Z1/Z2/Z3 bands with dynamic coloring
- **Innovation Bands**: Fast MA envelope (KAMA/ALMA/Kalman)
- **MC Cone**: P10/P50/P90 projection
- **Oscillators**: 6 UDT-based subpanes (MR, TE, VEC, CORR, LTF, BURST)
- **Info Tables**: kNN+MC debug, backtest summary, basket status

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INPUT LAYER                                   │
│  Basket Symbols → Auto Scan → Correlation Scores → Top 4 Selected   │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│                      FEATURE ENGINEERING                              │
│  • Basket Vector (v1-v4)                                              │
│  • Orthogonal MR (Level 1-4)                                          │
│  • Transfer Entropy (TE)                                                │
│  • 7 kNN Features (F1-F7)                                             │
│  • Lloyd-Max Quantization → 24-bit Packed Vector                     │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│                      kNN TOURNAMENT                                   │
│  Current State → Hamming Screen → 4-Tier Selection → k Neighbors   │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    MONTE CARLO SIMULATION                             │
│  kNN Neighbors → Bootstrap Paths → Welford Stats → P10/P50/P90     │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    SETUP DETECTION & SIGNALS                          │
│  Regime Events → Setup Conditions → Showstopper Check → Fire Setup │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    VISUALIZATION & TABLES                             │
│  Survival Bands | MC Cone | Oscillators | Info Tables              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Performance Optimizations

1. **Library Architecture**: All heavy logic in libraries (reduced global vars)
2. **Chunked MC**: 50 runs/tick for progressive cone building
3. **Percentile Caching**: Recalculate every N bars (not per-bar)
4. **Ring Buffers**: Fixed-size feature history (max_heavy_bars)
5. **Inline Calculations**: No array allocation in hot paths
6. **Bit-Packing**: 24-vector encoding for kNN state
7. **Welford Algorithm**: O(1) online statistics

---

## Backtest System

- **Historical Validation**: Retroactive kNN+MC on all setups
- **Budget-Based Chunking**: 20 heavy validations/tick
- **Forward Bias Prevention**: knn_limit = offset - horizon - 1
- **Directional Agreement**: MC must agree with setup direction
- **Metrics**: Win rate, Avg PnL, Sharpe, MFE:MAE ratio

---

## Key Metrics & Performance

### Setup Performance (from code comments)
- **S1**: 65% WR (CORR_BOTTOM + MR_CONFIRM)
- **S6**: 65% WR (MR < -0.5 + MR turning)
- **L1**: 64% WR (TE > threshold + CFV rising)
- **L2**: 52% WR (Pure trend, independent bullish momentum)
- **V1**: 81% WR (Trend bounce at survival band)
- **V2**: 73% WR (Strict MR, snap-back to equilibrium)

### System Metrics
- **Load Time**: 15-32 seconds (configurable)
- **kNN Confidence**: Distance-based (0-100%)
- **Basket Fit**: 0-100% correlation quality
- **TE Window**: 100 bars, 3 bins
- **MC Runs**: 5000 (live), 200 (backtest)

---

## Technical Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **kNN** | Lloyd-Max quantization | State matching |
| **MC** | Welford + Bootstrap | Forward projection |
| **TE** | Transfer entropy | Causality detection |
| **Kalman** | State-space model | Adaptive filtering |
| **Orthogonalization** | Gram-Schmidt | MR decoupling |
| **UDT** | User-defined types | Structured data |

---

## Files Structure

```
fresh CVB indicator project/
├── Combined Vector Bands v19 kNN+ConeFilter.pine (4316 lines)
├── libs/
│   ├── BandsLib.pine (band calculations)
│   ├── BasketLib.pine (auto-scan, correlation)
│   ├── kNNLib.pine (tournament, quantization)
│   ├── MCLib.pine (Welford MC, bootstrap)
│   ├── SetupsLib.pine (setup DB, families)
│   ├── CausalityLib (TE, Shannon entropy)
│   ├── TAUtilityLib (Kalman, utilities, 2556 lines)
│   ├── chainaggrLib
│   └── MLLib.pine
├── history/
│   └── Debugging and Enhancing Pine Script Indicator.md
├── tv-dumps/ (CSV data files)
├── auto_dump.py
├── backtest_s9.py
├── decode_setup.py
├── requirements.txt
└── wiki-codemap.md
```

---

## Summary

CVB v19 is an institutional-grade trading indicator combining:
- **Machine Learning**: kNN state matching with TurboQuant encoding
- **Monte Carlo Simulation**: Welford-based forward projection
- **Causality Analysis**: Transfer entropy for information flow
- **Adaptive Systems**: SGD self-tuning, regime-switched normalization
- **Multi-Asset Correlation**: Auto-scan basket selection
- **Empirical Setups**: 19+ setup types with documented WR

The architecture prioritizes **performance** (chunked execution, library modularity) while maintaining **accuracy** (orthogonalization, directional agreement, forward bias prevention).
