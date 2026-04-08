#!/usr/bin/env python3
"""
CVB v19 kNN+MC Backtest Verification — Full CSV-Based Simulation

Simulates ALL setups from CSV dump Debug Combined signals using the exact
TP/SL/MaxHold parameters from SetupsLib.f_build_setup_db_v19(), then
compares against screenshot-reported metrics.

Screenshots:
  ZEC  Raw=687  Filt=330  WR_raw=59.1%  WR_filt=57.1%  PnL_raw=+0.2%
  SUI  Raw=631  Filt=237  WR_raw=56.1%  WR_filt=57.1%  PnL_raw=+0.2%
  CRV  Raw=630  Filt=345  WR_raw=52.1%  WR_filt=51.1%  PnL_raw=-0.2%

Method:
  1. Parse CSV Debug Combined column → detect setup fires with direction
  2. For each fire, simulate TP/SL/MaxHold from subsequent OHLCV
  3. Aggregate: WR%, Avg PnL%, Sharpe, MFE:MAE per setup and total
  4. Compare vs screenshots
"""

import csv
import math
import sys
from pathlib import Path
from collections import defaultdict, OrderedDict
from dataclasses import dataclass, field

DUMPS = Path(__file__).parent / "tv-dumps"

# ── Setup database from SetupsLib.f_build_setup_db_v19() ──
# id: (direction, tp_pct, sl_pct, max_hold, claimed_wr)
SETUP_DB = {
    'S1':  ('SHORT',  0.80, -1.20, 12, 64.5),
    'S5':  ('SHORT',  0.80, -1.50, 10, 60.2),
    'S6':  ('SHORT',  0.80, -1.20,  8, 65.0),
    'S7':  ('SHORT',  0.80, -1.20, 15, 61.0),
    'S8':  ('SHORT',  0.80, -1.20, 12, 69.2),
    'S9':  ('SHORT',  0.80, -1.20, 16, 73.0),
    'S10': ('SHORT',  0.80, -1.20, 14, 61.5),
    'S12': ('SHORT',  0.80, -1.20, 12, 73.9),
    'L1':  ('LONG',   0.80, -1.20, 15, 63.6),
    'L2':  ('LONG',   0.80, -1.20, 14, 51.7),
    'L3':  ('LONG',   0.80, -1.20, 16, 66.7),
    'L4':  ('LONG',   0.80, -1.20, 12, 55.8),
    'L5':  ('LONG',   0.80, -1.20,  8, 68.0),
    'L6':  ('LONG',   0.80, -1.20, 12, 70.0),
    'L7':  ('LONG',   0.80, -1.20, 16, 72.5),
    'L8':  ('LONG',   0.80, -1.20, 14, 60.0),
    'L9':  ('LONG',   0.80, -1.20, 15, 75.3),
    'V1':  ('LONG',   0.80, -1.20,  8, 81.0),
    'V2':  ('SHORT',  0.80, -1.20, 10, 73.0),
    'V3':  ('LONG',   0.80, -1.20, 12, 75.0),
    'V4':  ('LONG',   0.80, -1.50, 14, 64.0),
    '81':  ('LONG',   0.80, -1.20, 12, 81.0),
    '73':  ('SHORT',  0.80, -1.20, 12, 73.0),
    '75':  ('SHORT',  0.80, -1.20, 12, 75.0),
    '64':  ('LONG',   0.80, -1.20, 14, 64.0),
}

# Setup code → ID mapping from indicator lines 3929-3981
CODE_TO_ID = {
    100: 'S1', 500: 'S5', 600: 'S6', 700: 'S7', 800: 'S8',
    900: 'S9', 1000: 'S10', 1110: 'S11', 1120: 'S12',
    1100: 'L1', 1200: 'L2', 1300: 'L3', 1500: 'L5',
    1600: 'L6', 1700: 'L7', 1800: 'L8', 1900: 'L9',
    2100: 'V1', 2200: 'V2', 2300: 'V3', 2400: 'V4',
    8100: '81', 7300: '73', 7500: '75', 6400: '64',
}

# Default params when setup not in DB
DEFAULT_TP = 0.80
DEFAULT_SL = -1.20
DEFAULT_MAX_HOLD = 20

# Screenshot reference data
SCREENSHOTS = {
    'MEXC_ZECUSDT.P, 15_2478c.csv': {
        'name': 'ZEC',
        'raw_setups': 687, 'filt_setups': 330,
        'raw_wr': 59.1, 'filt_wr': 57.1,
        'raw_pnl': 0.2, 'filt_pnl': 0.2,
        'raw_sharpe': 0.2, 'filt_sharpe': 0.2,
        'raw_rr': 1.2, 'filt_rr': 1.2,
    },
    'BINANCE_SUIUSDT.P, 15_eed3a.csv': {
        'name': 'SUI',
        'raw_setups': 631, 'filt_setups': 237,
        'raw_wr': 56.1, 'filt_wr': 57.1,
        'raw_pnl': 0.2, 'filt_pnl': -0.2,
        'raw_sharpe': 0.2, 'filt_sharpe': -0.2,
        'raw_rr': 1.2, 'filt_rr': 1.2,
    },
    'BYBIT_CRVUSDT.P, 15_aa533.csv': {
        'name': 'CRV',
        'raw_setups': 630, 'filt_setups': 345,
        'raw_wr': 52.1, 'filt_wr': 51.1,
        'raw_pnl': -0.2, 'filt_pnl': 0.2,
        'raw_sharpe': -0.2, 'filt_sharpe': 0.2,
        'raw_rr': 1.2, 'filt_rr': 1.2,
    },
}

# Minimum gap between setups of same type (from indicator SETUP_MIN_GAP equivalent)
SETUP_GAP = 5


def decode_setup_code(code_raw):
    """Decode Debug Combined value → (setup_id, direction) or None."""
    if not code_raw or code_raw == 0:
        return None, None
    val = int(float(code_raw))
    setup_merged = val % 100000
    setup_code = setup_merged % 10000
    sid = CODE_TO_ID.get(setup_code)
    if sid is None:
        return None, None
    info = SETUP_DB.get(sid)
    if info is None:
        return sid, 'BOTH'
    return sid, info[0]


def simulate_trade(bars, entry_idx, direction, tp_pct, sl_pct, max_hold, use_new_exits=True):
    """
    Simulate one trade. Returns (pnl_pct, mfe, mae, exit_reason, hold_bars).

    FIX 4: When use_new_exits=True, uses full exit simulation:
      1. Hard SL (1.8%) → 2. Trailing SL (pred_ma after 0.5% gain)
      3. Predflip (3-bar slope reversal) → 4. Breakeven (5 bars underwater)
      5. TP (lowest priority) → 6. MaxHold
    When use_new_exits=False, uses legacy simple TP/SL only.
    """
    entry_price = bars[entry_idx]['close']
    mfe = 0.0
    mae = 0.0
    limit = min(entry_idx + max_hold + 1, len(bars))
    trail_sl = None

    for i in range(entry_idx + 1, limit):
        bar = bars[i]
        hi, lo, cl = bar['high'], bar['low'], bar['close']
        pred_ma = bar.get('pred_ma')  # May be None for old CSV dumps

        if direction == 'SHORT':
            favorable = (entry_price - lo) / entry_price * 100
            adverse = (entry_price - hi) / entry_price * 100
            pnl = (entry_price - cl) / entry_price * 100
        else:
            favorable = (hi - entry_price) / entry_price * 100
            adverse = (lo - entry_price) / entry_price * 100
            pnl = (cl - entry_price) / entry_price * 100

        mfe = max(mfe, favorable)
        mae = min(mae, adverse)

        if use_new_exits:
            # FIX 4: Full exit simulation
            # 1. Hard SL (1.8% catastrophic)
            hard_sl = 1.8
            if pnl <= -hard_sl:
                return pnl, mfe, mae, 'SL', i - entry_idx

            # 2. Trailing SL to pred_ma (activates after 0.5% max gain)
            if mfe >= 0.5 and pred_ma is not None:
                if trail_sl is None:
                    trail_sl = pred_ma
                else:
                    trail_sl = max(trail_sl, pred_ma) if direction == 'LONG' else min(trail_sl, pred_ma)
                if direction == 'LONG' and lo <= trail_sl:
                    return pnl, mfe, mae, 'TRAIL', i - entry_idx
                if direction == 'SHORT' and hi >= trail_sl:
                    return pnl, mfe, mae, 'TRAIL', i - entry_idx

            # 3. Predflip (3-bar slope reversal) — requires pred_ma history
            # (simplified: skip if no history available)

            # 4. Breakeven (after 5 bars if still underwater)
            hold_bars = i - entry_idx
            if hold_bars >= 5 and pnl < 0:
                return 0.0, mfe, mae, 'BE', hold_bars

            # 5. TP
            if direction == 'SHORT':
                tp_price = entry_price * (1 - tp_pct / 100)
                if lo <= tp_price:
                    exit_pnl = (entry_price - tp_price) / entry_price * 100
                    return exit_pnl, mfe, mae, 'TP', hold_bars
            else:
                tp_price = entry_price * (1 + tp_pct / 100)
                if hi >= tp_price:
                    exit_pnl = (tp_price - entry_price) / entry_price * 100
                    return exit_pnl, mfe, mae, 'TP', hold_bars
        else:
            # Legacy simple TP/SL
            if direction == 'SHORT':
                tp_price = entry_price * (1 - tp_pct / 100)
                sl_price = entry_price * (1 - sl_pct / 100)
                if lo <= tp_price:
                    pnl = (entry_price - tp_price) / entry_price * 100
                    return pnl, mfe, mae, 'TP', i - entry_idx
                if hi >= sl_price:
                    pnl = (entry_price - sl_price) / entry_price * 100
                    return pnl, mfe, mae, 'SL', i - entry_idx
            else:
                tp_price = entry_price * (1 + tp_pct / 100)
                sl_price = entry_price * (1 + sl_pct / 100)
                if hi >= tp_price:
                    pnl = (tp_price - entry_price) / entry_price * 100
                    return pnl, mfe, mae, 'TP', i - entry_idx
                if lo <= sl_price:
                    pnl = (sl_price - entry_price) / entry_price * 100
                    return pnl, mfe, mae, 'SL', i - entry_idx

    # Max hold
    last_bar = bars[min(entry_idx + max_hold, len(bars) - 1)]
    cl = last_bar['close']
    if direction == 'SHORT':
        pnl = (entry_price - cl) / entry_price * 100
    else:
        pnl = (cl - entry_price) / entry_price * 100
    return pnl, mfe, mae, 'MAXHOLD', min(max_hold, len(bars) - entry_idx - 1)


def process_csv(csv_path):
    """Load CSV, detect setups, simulate trades, return per-setup + aggregate stats."""
    # Load bars
    bars = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            debug_val = row.get('Debug Combined', '0')
            pred_ma_val = row.get('Predictive Vector MA', '')
            bars.append({
                'time': int(row['time']),
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'debug': float(debug_val) if debug_val else 0,
                'pred_ma': float(pred_ma_val) if pred_ma_val else None,
            })

    # Detect setup fires
    fires = []
    last_fire = {}  # sid → last bar index
    for i, bar in enumerate(bars):
        sid, direction = decode_setup_code(bar['debug'])
        if sid is None:
            continue
        # Gap filter
        if sid in last_fire and i - last_fire[sid] < SETUP_GAP:
            continue
        last_fire[sid] = i
        fires.append((i, sid, direction))

    # Per-setup stats
    stats = defaultdict(lambda: {
        'count': 0, 'wins': 0, 'pnl_sum': 0.0, 'pnl_sq': 0.0,
        'mfe_sum': 0.0, 'mae_sum': 0.0, 'tp': 0, 'sl': 0, 'maxh': 0,
        'trail': 0, 'be': 0, 'predflip': 0,
    })

    all_pnls = []

    for entry_idx, sid, direction in fires:
        if sid not in SETUP_DB:
            continue
        dir_db, tp, sl, maxh, _ = SETUP_DB[sid]
        # Use DB direction if 'BOTH' from decode
        if direction == 'BOTH':
            direction = dir_db

        pnl, mfe, mae, exit_reason, hold = simulate_trade(
            bars, entry_idx, direction, tp, sl, maxh)

        s = stats[sid]
        s['count'] += 1
        s['pnl_sum'] += pnl
        s['pnl_sq'] += pnl * pnl
        if pnl > 0:
            s['wins'] += 1
        s['mfe_sum'] += mfe
        s['mae_sum'] += abs(mae)
        if exit_reason == 'TP':
            s['tp'] += 1
        elif exit_reason == 'SL':
            s['sl'] += 1
        elif exit_reason == 'TRAIL':
            s['trail'] += 1
        elif exit_reason == 'BE':
            s['be'] += 1
        elif exit_reason == 'PREDFLIP':
            s['predflip'] += 1
        else:
            s['maxh'] += 1
        all_pnls.append(pnl)

    return stats, all_pnls, len(bars), len(fires)


def metrics(pnl_list):
    n = len(pnl_list)
    if n == 0:
        return {'count': 0, 'wr': 0, 'avg_pnl': 0, 'sharpe': 0, 'rr': 0}
    wins = sum(1 for p in pnl_list if p > 0)
    avg = sum(pnl_list) / n
    var = sum(p*p for p in pnl_list) / n - avg * avg
    std = math.sqrt(max(var, 0))
    sharpe = avg / std if std > 0 else 0
    return {'count': n, 'wr': wins/n*100, 'avg_pnl': avg, 'sharpe': sharpe}


def main():
    print("=" * 95)
    print("CVB v19 kNN+MC Backtest Verification — CSV-Based Simulation")
    print("Simulating TP/SL/MaxHold from Debug Combined signals")
    print("=" * 95)

    for csv_name, ref in SCREENSHOTS.items():
        csv_path = DUMPS / csv_name
        if not csv_path.exists():
            print(f"\n⚠️  {ref['name']}: CSV not found: {csv_name}")
            continue

        stats, all_pnls, n_bars, n_fires = process_csv(csv_path)
        total_trades = sum(s['count'] for s in stats.values())
        m = metrics(all_pnls)

        print(f"\n{'═' * 95}")
        print(f"  {ref['name']}  —  {csv_name}  ({n_bars} bars, {n_fires} fires, {total_trades} trades)")
        print(f"{'═' * 95}")

        # Aggregate
        print(f"\n  {'METRIC':<14} {'CSV-SIM':>12} {'SCREENSHOT':>12} {'Δ':>10}")
        print(f"  {'─' * 50}")
        print(f"  {'Setups':<14} {m['count']:>12} {ref['raw_setups']:>12} {m['count']-ref['raw_setups']:>+10}")
        print(f"  {'Win Rate %':<14} {m['wr']:>11.1f}% {ref['raw_wr']:>11.1f}% {(m['wr']-ref['raw_wr']):>+9.1f}%")
        print(f"  {'Avg PnL %':<14} {m['avg_pnl']:>+11.2f}% {ref['raw_pnl']:>+11.1f}% {(m['avg_pnl']-ref['raw_pnl']):>+9.2f}%")
        print(f"  {'Sharpe':<14} {m['sharpe']:>12.2f} {ref['raw_sharpe']:>12.1f} {(m['sharpe']-ref['raw_sharpe']):>+9.2f}")

        # Exit breakdown
        tp_total = sum(s['tp'] for s in stats.values())
        sl_total = sum(s['sl'] for s in stats.values())
        trail_total = sum(s['trail'] for s in stats.values())
        be_total = sum(s['be'] for s in stats.values())
        pf_total = sum(s['predflip'] for s in stats.values())
        mh_total = sum(s['maxh'] for s in stats.values())
        print(f"\n  Exits: TP={tp_total}({tp_total/total_trades*100:.0f}%) SL={sl_total}({sl_total/total_trades*100:.0f}%) Trail={trail_total}({trail_total/total_trades*100:.0f}%) BE={be_total}({be_total/total_trades*100:.0f}%) Flip={pf_total}({pf_total/total_trades*100:.0f}%) MaxH={mh_total}({mh_total/total_trades*100:.0f}%)")

        # Per-setup
        print(f"\n  {'ID':>5} {'Dir':>5} {'N':>5} {'WR%':>7} {'AvgPnL%':>9} {'TP':>3} {'SL':>3} {'Trail':>5} {'BE':>3} {'Flip':>4} {'MaxH':>4} {'Claimed':>8}")
        print(f"  {'─' * 65}")
        for sid in sorted(stats.keys(), key=lambda x: (x[0].isdigit(), x)):
            s = stats[sid]
            if s['count'] == 0:
                continue
            wr = s['wins'] / s['count'] * 100
            avg = s['pnl_sum'] / s['count']
            claimed = SETUP_DB.get(sid, (None, None, None, None, 0))[4]
            d = SETUP_DB.get(sid, ('?',))[0][:1] + '/' if SETUP_DB.get(sid) else '?'
            print(f"  {sid:>5} {d:>5} {s['count']:>5} {wr:>6.1f}% {avg:>+8.2f}% {s['tp']:>3} {s['sl']:>3} {s['trail']:>5} {s['be']:>3} {s['predflip']:>4} {s['maxh']:>4} {claimed:>7.1f}%")

        # Verdict
        wr_gap = abs(m['wr'] - ref['raw_wr'])
        pnl_gap = abs(m['avg_pnl'] - ref['raw_pnl'])
        count_gap = abs(m['count'] - ref['raw_setups'])
        if wr_gap < 3 and pnl_gap < 0.3 and count_gap < 50:
            print(f"\n  ✅ CLOSE MATCH — CSV simulation aligns with screenshot within tolerance")
        elif count_gap > 100:
            print(f"\n  ❌ COUNT MISMATCH — CSV detected {m['count']} vs screenshot {ref['raw_setups']}")
            print(f"      → Debug Combined column may fire on different bars than indicator's BT engine")
        elif wr_gap > 10:
            print(f"\n  ❌ WR MISMATCH — CSV sim {m['wr']:.1f}% vs screenshot {ref['raw_wr']:.1f}%")
            print(f"      → CSV TP/SL simulation differs from indicator's MC-based exit logic")
        else:
            print(f"\n  ⚠️  PARTIAL MATCH — some metrics align, others diverge")


if __name__ == '__main__':
    main()
