#!/usr/bin/env python3
"""
CVB v19 Setup Recalibration — TP/SL/MaxHold Sweep on Actual Fire Points

Uses Debug Combined column to find exact bars where each setup fired,
then sweeps TP/SL/MaxHold across all CSV dumps to find optimal values.
This is faster and more accurate than re-evaluating entry conditions.

Usage: python recalibrate_setups.py
"""

import csv
import math
import sys
from pathlib import Path
from itertools import product

DUMPS_DIR = Path(__file__).parent / "tv-dumps"

# Setup codes from SetupsLib.f_setup_id_to_code (v19)
CODE_TO_ID = {
    101: 'S1', 102: 'S2', 103: 'S3', 105: 'S5', 106: 'S6', 107: 'S7',
    108: 'S8', 109: 'S9', 110: 'S10', 111: 'S11', 112: 'S12',
    201: 'L1', 202: 'L2', 203: 'L3', 104: 'L4', 205: 'L5',
    206: 'L6', 207: 'L7', 208: 'L8', 209: 'L9',
    301: 'V1', 302: 'V2', 303: 'V3', 304: 'V4',
    381: '81', 373: '73', 375: '75', 364: '64',
}

# Default directions
SETUP_DIR = {
    'S1': 'SHORT', 'S5': 'SHORT', 'S6': 'SHORT', 'S7': 'SHORT',
    'S8': 'SHORT', 'S9': 'SHORT', 'S10': 'SHORT', 'S11': 'SHORT',
    'S12': 'SHORT', 'L1': 'LONG', 'L2': 'LONG', 'L3': 'LONG',
    'L5': 'LONG', 'L6': 'LONG', 'L7': 'LONG', 'L8': 'LONG',
    'L9': 'LONG', 'V1': 'LONG', 'V2': 'SHORT', 'V3': 'LONG',
    'V4': 'LONG', '81': 'LONG', '73': 'SHORT', '75': 'SHORT',
    '64': 'LONG',
}


def load_csv_dump(path):
    """Load CSV and return bars with debug column parsed."""
    bars = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                debug_val = float(row['Debug Combined']) if row.get('Debug Combined') else 0
                bars.append({
                    'close': float(row['close']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'debug': debug_val,
                })
            except (ValueError, KeyError):
                continue
    return bars


def extract_setup_fires(bars):
    """Extract (bar_idx, setup_id, direction) for each setup fire."""
    fires_by_id = {}  # setup_id -> [(bar_idx, direction), ...]
    last_fire = {}  # setup_id -> last bar_idx (for gap filter)

    for i, bar in enumerate(bars):
        val = bar['debug']
        if not val or val == 0:
            continue
        setup_merged = int(val) % 100000
        code = setup_merged % 10000
        sid = CODE_TO_ID.get(code)
        if sid is None:
            continue
        # 5-bar gap filter (same as indicator)
        if sid in last_fire and i - last_fire[sid] < 5:
            continue
        last_fire[sid] = i
        direction = SETUP_DIR.get(sid, 'UNKNOWN')
        fires_by_id.setdefault(sid, []).append((i, direction))

    return fires_by_id


# Commission rate (per side, market order taker fee)
# Bybit: 0.055% per side, Binance: 0.04-0.05% per side
# Using 0.05% per side (0.10% round trip) as conservative baseline
COMMISSION_PCT = 0.05  # per side, in percent

def simulate_trade(bars, entry_idx, direction, tp_pct, sl_pct, max_hold):
    """Simulate trade from entry bar, deducting commission on entry+exit."""
    if entry_idx >= len(bars) - 1:
        return 0.0, 0.0, 0.0, 'NO_DATA'

    ep = bars[entry_idx]['close']
    # Commission cost: paid on entry (full position) + exit (full position)
    # Total commission = 2 * COMMISSION_PCT% of position value
    commission_cost = 2 * COMMISSION_PCT

    mfe = 0.0
    mae = 0.0
    limit = min(entry_idx + max_hold + 1, len(bars))

    for i in range(entry_idx + 1, limit):
        bar = bars[i]
        hi, lo, cl = bar['high'], bar['low'], bar['close']

        if direction == 'SHORT':
            favorable = (ep - lo) / ep * 100
            adverse = (ep - hi) / ep * 100
            pnl_raw = (ep - cl) / ep * 100
            mfe = max(mfe, favorable)
            mae = min(mae, adverse)
            tp_price = ep * (1 - tp_pct / 100)
            sl_price = ep * (1 - sl_pct / 100)
            if lo <= tp_price:
                pnl_net = (ep - tp_price) / ep * 100 - commission_cost
                return pnl_net, mfe, mae, 'TP'
            if hi >= sl_price:
                pnl_net = (ep - sl_price) / ep * 100 - commission_cost
                return pnl_net, mfe, mae, 'SL'
        else:
            favorable = (hi - ep) / ep * 100
            adverse = (lo - ep) / ep * 100
            pnl_raw = (cl - ep) / ep * 100
            mfe = max(mfe, favorable)
            mae = min(mae, adverse)
            tp_price = ep * (1 + tp_pct / 100)
            sl_price = ep * (1 + sl_pct / 100)
            if hi >= tp_price:
                pnl_net = (tp_price - ep) / ep * 100 - commission_cost
                return pnl_net, mfe, mae, 'TP'
            if lo <= sl_price:
                pnl_net = (sl_price - ep) / ep * 100 - commission_cost
                return pnl_net, mfe, mae, 'SL'

    last_bar = bars[min(entry_idx + max_hold, len(bars) - 1)]
    cl = last_bar['close']
    pnl_raw = (cl - ep) / ep * 100 if direction == 'LONG' else (ep - cl) / ep * 100
    pnl_net = pnl_raw - commission_cost
    return pnl_net, mfe, mae, 'MAXHOLD'


def compute_metrics(pnl_list):
    n = len(pnl_list)
    if n == 0:
        return {'wr': 0, 'avg_pnl': 0, 'sharpe': 0, 'total_pnl': 0, 'count': 0, 'wins': 0, 'rr': 0}
    wins = sum(1 for p in pnl_list if p > 0)
    losses = [p for p in pnl_list if p <= 0]
    avg = sum(pnl_list) / n
    var = sum(p*p for p in pnl_list) / n - avg * avg
    std = math.sqrt(max(var, 0))
    sharpe = avg / std if std > 0 else 0
    avg_win = sum(p for p in pnl_list if p > 0) / wins if wins > 0 else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0
    rr = avg_win / avg_loss if avg_loss > 0 else 0
    return {
        'wr': wins / n * 100,
        'avg_pnl': avg,
        'sharpe': sharpe,
        'total_pnl': sum(pnl_list),
        'count': n,
        'wins': wins,
        'rr': rr,
    }


def run_sweep(setup_id, all_fires, all_bars_list, min_trades=5):
    """Sweep TP/SL/MaxHold for one setup across all dumps."""
    # Collect all fire points across all dumps
    fire_points = []  # [(bars_ref, entry_idx, direction), ...]
    for fires, bars in zip(all_fires, all_bars_list):
        for idx, direction in fires.get(setup_id, []):
            if idx < len(bars) - 1:
                fire_points.append((bars, idx, direction))

    if len(fire_points) < min_trades:
        return None

    # Parameter grid
    tp_values = [0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 1.00]
    sl_values = [-0.50, -0.60, -0.70, -0.80, -1.00, -1.20, -1.50]
    mh_values = [4, 6, 8, 10, 12, 14, 16, 20]

    # Limit combos for speed: use strategic subset
    combos = []
    for tp in tp_values:
        for sl in sl_values:
            for mh in mh_values:
                # Skip unreasonable combos (SL wider than 2x TP, etc.)
                if abs(sl) > tp * 3:
                    continue
                if mh > 20:
                    continue
                combos.append((tp, sl, mh))

    # Also add some targeted combos for common setups
    targeted = [
        (0.50, -0.80, 8), (0.60, -1.00, 10), (0.70, -1.00, 12),
        (0.80, -1.20, 14), (0.50, -1.00, 6), (0.60, -0.80, 8),
    ]
    for t in targeted:
        if t not in combos:
            combos.append(t)

    print(f"  {setup_id}: {len(fire_points)} fires, {len(combos)} combos...", end="", flush=True)

    best_score = -999
    best_config = None
    best_metrics = None

    for tp, sl, mh in combos:
        pnls = []
        for bars, idx, direction in fire_points:
            pnl, mfe, mae, reason = simulate_trade(bars, idx, direction, tp, sl, mh)
            pnls.append(pnl)

        m = compute_metrics(pnls)
        if m['count'] < min_trades:
            continue

        # Composite score
        wr_bonus = m['wr'] if m['wr'] > 50 else m['wr'] * 0.3
        score = wr_bonus * 0.5 + m['sharpe'] * 10 + m['total_pnl'] * 0.1 + m['rr'] * 5

        if score > best_score:
            best_score = score
            best_config = (tp, sl, mh)
            best_metrics = m

    if best_config:
        tp, sl, mh = best_config
        print(f" DONE → WR={best_metrics['wr']:.1f}% Sh={best_metrics['sharpe']:.2f} RR={best_metrics['rr']:.2f} N={best_metrics['count']} tp={tp} sl={sl} mh={mh}")
        return {
            'setup_id': setup_id,
            'direction': SETUP_DIR.get(setup_id, '?'),
            'tp_pct': tp,
            'sl_pct': sl,
            'max_hold': mh,
            'metrics': best_metrics,
        }
    else:
        print(f" NO VALID (<{min_trades} trades)")
        return None


def main():
    print("=" * 80)
    print("CVB v19 Setup Recalibration — TP/SL/MaxHold Sweep on Actual Fires")
    print("=" * 80)

    csv_files = sorted(DUMPS_DIR.glob("*.csv"))
    csv_files = [f for f in csv_files if not f.name.startswith('pine-logs')]

    if not csv_files:
        print("ERROR: No CSV dumps found")
        sys.exit(1)

    print(f"\nLoading {len(csv_files)} CSV dumps...")
    all_bars = []
    all_fires = []
    for f in csv_files:
        bars = load_csv_dump(f)
        if bars:
            fires = extract_setup_fires(bars)
            all_bars.append(bars)
            all_fires.append(fires)
            total_fires = sum(len(v) for v in fires.values())
            print(f"  {f.name}: {len(bars)} bars, {total_fires} setup fires")

    # Count total fires per setup across all dumps
    print("\nSetup fire counts across all dumps:")
    all_setup_fires = {}
    for fires in all_fires:
        for sid, entries in fires.items():
            all_setup_fires[sid] = all_setup_fires.get(sid, 0) + len(entries)

    for sid in sorted(all_setup_fires.keys()):
        print(f"  {sid}: {all_setup_fires[sid]} fires")

    # Run sweep for each setup that has enough fires
    setup_ids = sorted(all_setup_fires.keys())
    results = []

    print(f"\nSweeping TP/SL/MaxHold for {len(setup_ids)} setups...")
    print("-" * 80)

    for sid in setup_ids:
        if all_setup_fires[sid] < 5:
            print(f"  {sid}: skipping (<5 total fires)")
            continue
        result = run_sweep(sid, all_fires, all_bars)
        if result:
            results.append(result)

    # Output results
    print("\n" + "=" * 80)
    print("OPTIMIZED SETUP DATABASE — RECALIBRATED")
    print("=" * 80)
    print(f"\n{'ID':>5} {'Dir':>5} {'WR%':>7} {'Sharpe':>8} {'RR':>6} {'AvgPnL%':>9} {'TotalPNL':>10} {'N':>5} {'TP%':>5} {'SL%':>6} {'MH':>4}")
    print("-" * 90)

    for r in sorted(results, key=lambda x: x['setup_id']):
        m = r['metrics']
        print(f"{r['setup_id']:>5} {r['direction']:>5} {m['wr']:>6.1f}% {m['sharpe']:>8.2f} {m['rr']:>6.2f} {m['avg_pnl']:>+8.2f}% {m['total_pnl']:>+10.2f}% {m['count']:>5} {r['tp_pct']:>5.2f} {r['sl_pct']:>6.2f} {r['max_hold']:>4}")

    # v19 original for comparison
    V19 = {
        'S1':  (0.80, -1.20, 12, 64.5), 'S5':  (0.80, -1.50, 10, 60.2),
        'S6':  (0.80, -1.20,  8, 65.0), 'S7':  (0.80, -1.20, 15, 61.0),
        'S8':  (0.80, -1.20, 12, 69.2), 'S9':  (0.80, -1.20, 16, 73.0),
        'S10': (0.80, -1.20, 14, 61.5), 'S12': (0.80, -1.20, 12, 73.9),
        'L1':  (0.80, -1.20, 15, 63.6), 'L2':  (0.80, -1.20, 14, 51.7),
        'L5':  (0.80, -1.20,  8, 68.0), 'L6':  (0.80, -1.20, 12, 70.0),
        'L7':  (0.80, -1.20, 16, 72.5), 'L8':  (0.80, -1.20, 14, 60.0),
        'L9':  (0.80, -1.20, 15, 75.3), 'V1':  (0.80, -1.20,  8, 81.0),
        'V2':  (0.80, -1.20, 10, 73.0), 'V3':  (0.80, -1.20, 12, 75.0),
        'V4':  (0.80, -1.50, 14, 64.0), '81':  (0.80, -1.20, 12, 81.0),
        '73':  (0.80, -1.20, 12, 73.0), '75':  (0.80, -1.20, 12, 75.0),
        '64':  (0.80, -1.20, 14, 64.0),
    }

    print("\n" + "=" * 80)
    print("COMPARISON: Quen vs v19 Original")
    print("=" * 80)
    print(f"\n{'ID':>5} | {'WR% Quen':>9} {'WR% v19':>9} {'ΔWR':>6} | {'TP Quen':>8} {'TP v19':>8} | {'SL Quen':>8} {'SL v19':>8} | {'MH Quen':>8} {'MH v19':>8}")
    print("-" * 100)

    for r in sorted(results, key=lambda x: x['setup_id']):
        sid = r['setup_id']
        v19 = V19.get(sid)
        v19_wr = v19[3] if v19 else 0
        v19_tp = v19[0] if v19 else 0
        v19_sl = v19[1] if v19 else 0
        v19_mh = v19[2] if v19 else 0
        dq = r['metrics']['wr'] - v19_wr
        print(f"{sid:>5} | {r['metrics']['wr']:>8.1f}% {v19_wr:>8.1f}% {dq:>+5.1f}% | {r['tp_pct']:>8.2f} {v19_tp:>8.2f} | {r['sl_pct']:>8.2f} {v19_sl:>8.2f} | {r['max_hold']:>8} {v19_mh:>8}")

    # Generate SetupsLibQuen-compatible output
    print("\n" + "=" * 80)
    print("SETUPSLIB-QUEN DB ENTRIES (copy-paste ready)")
    print("=" * 80)
    print()

    for r in sorted(results, key=lambda x: x['setup_id']):
        sid = r['setup_id']
        m = r['metrics']
        fam_label = {'S1':'VEL','S5':'VEL','S6':'MR','S7':'VEL','S8':'VEL','S9':'VEL',
                     'S10':'VEL','S11':'MR','S12':'TRAN','L1':'TRAN','L2':'TRAN',
                     'L3':'TRAN','L5':'MR','L6':'TRAN','L7':'TRAN','L8':'TRAN',
                     'L9':'TRAN','V1':'UNC','V2':'MR','V3':'TRAN','V4':'TRAN',
                     '81':'UNC','73':'VEL','75':'VEL','64':'CONT'}.get(sid, '?')
        edge = {'S1':1.08,'S5':1.08,'S6':1.15,'S7':1.10,'S8':1.20,'S9':1.25,
                'S10':1.30,'S11':1.15,'S12':1.18,'L1':1.17,'L2':1.30,'L3':1.15,
                'L5':1.18,'L6':1.12,'L7':1.22,'L8':1.28,'L9':1.22,'V1':1.17,
                'V2':1.26,'V3':1.14,'V4':0.97,'81':1.20,'73':1.15,'75':1.10,
                '64':1.05}.get(sid, 1.0)

        sid_lower = sid.lower()
        print(f'    SetupSpec.q{sid_lower} = SetupSpec.new("{sid}", "...", "{r["direction"]}", FAM_{fam_label}, {m["wr"]:.1f}, {m["sharpe"]:.2f}, {r["tp_pct"]:.2f}, {r["sl_pct"]:.2f}, {r["max_hold"]}, "WR{m["wr"]:.0f}% Sh{m["sharpe"]:.1f} RR{m["rr"]:.2f} (quen)", na, {edge}, "...", 0, SS_NONE, 1.0, 0, 0)')

    print()
    print("=" * 80)
    print(f"Total setups optimized: {len(results)}")
    print("To apply: copy the generated SetupSpec entries into SetupsLibQuen.pine")
    print("=" * 80)


if __name__ == '__main__':
    main()
