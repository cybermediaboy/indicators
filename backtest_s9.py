#!/usr/bin/env python3
"""
Backtest S9 Setup on CSV Dumps
S9: CFV+TE+LTFlo (SHORT)
- CFV falling (not cfv_rising and not cfv_rising[1])
- TE high (> 0.05)
- LTF decoupled (abs(ltf_corr_ema) < 0.3)
- Not falling knife

Metrics: Win Rate, Risk/Reward, Sharpe, Yield
"""

import csv
import math
from pathlib import Path
from typing import Dict, List
from datetime import datetime

# S9 Setup Parameters (from SetupsLib)
S9_TP_PCT = 0.80  # 80% profit target
S9_SL_PCT = -1.20  # -120% stop loss
S9_MAX_HOLD = 16  # max 16 bars
TE_SETUP_THRESH = 0.05
LTF_DECOUPLE_THRESH = 0.3
SETUP_MIN_GAP = 5  # minimum bars between setups

def load_csv(csv_path: Path) -> List[Dict]:
    """Load CSV dump with proper column parsing."""
    bars = []
    
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames
        
        for row in reader:
            # Extract relevant columns by index
            bar = {
                'time': int(row[cols[0]]),
                'open': float(row[cols[1]]),
                'high': float(row[cols[2]]),
                'low': float(row[cols[3]]),
                'close': float(row[cols[4]]),
                'debug_combined': int(row[cols[35]]) if row[cols[35]] else 0,
            }
            bars.append(bar)
    
    # Calculate derived fields
    for i in range(len(bars)):
        bar = bars[i]
        bar['datetime'] = datetime.fromtimestamp(bar['time'])
    
    return bars

def detect_s9_signals(bars: List[Dict]) -> List[Dict]:
    """Detect S9 setup signals from Debug Combined column.
    
    Debug Combined encoding from Pine Script:
    - setup_debug_code = 900.0 for S9
    - setup_debug_merged = setup_debug_code + ((setup_debug_code > 0 ? 1.0 : 0.0) * 10000.0) + (barstate.isrealtime ? 20000.0 : 0.0)
    - debug_combined = setup_debug_merged + cld_debug_bitfield * 100000.0
    
    For S9 (setup_debug_code = 900):
    - setup_debug_merged = 900 + 10000 = 10900 (not realtime) or 30900 (realtime)
    - debug_combined = 10900 + cld * 100000 or 30900 + cld * 100000
    - where cld can be 0, 100, 200, or 300
    
    So we check if (debug_combined % 100000) is in [10900, 30900]
    """
    signals = []
    
    for i in range(len(bars)):
        bar = bars[i]
        debug_val = bar['debug_combined']
        
        # Extract setup_debug_merged (lower 5 digits)
        setup_merged = debug_val % 100000
        
        # Check if this is an S9 signal (10900 or 30900)
        if setup_merged in [10900, 30900]:
            signals.append({
                'bar_idx': i,
                'datetime': bar['datetime'],
                'entry_price': bar['close'],
                'setup_id': 'S9',
                'direction': 'SHORT'
            })
    
    return signals

def simulate_trade(bars: List[Dict], signal: Dict, tp_pct: float, sl_pct: float, max_hold: int) -> Dict:
    """Simulate a single trade and return outcome."""
    entry_bar = signal['bar_idx']
    entry_price = signal['entry_price']
    direction = signal['direction']
    
    tp_price = entry_price * (1 - tp_pct) if direction == 'SHORT' else entry_price * (1 + tp_pct)
    sl_price = entry_price * (1 - sl_pct) if direction == 'SHORT' else entry_price * (1 + abs(sl_pct))
    
    # Track max favorable and adverse excursion
    mfe = 0.0  # Maximum favorable excursion
    mae = 0.0  # Maximum adverse excursion
    
    for i in range(entry_bar + 1, min(entry_bar + max_hold + 1, len(bars))):
        bar = bars[i]
        high = bar['high']
        low = bar['low']
        close = bar['close']
        
        if direction == 'SHORT':
            # Calculate PnL at this bar
            pnl_pct = (entry_price - close) / entry_price
            
            # Update MFE/MAE
            favorable = (entry_price - low) / entry_price
            adverse = (entry_price - high) / entry_price
            mfe = max(mfe, favorable)
            mae = max(mae, adverse)  # adverse is negative for short
            
            # Check TP
            if low <= tp_price:
                actual_pnl = (entry_price - tp_price) / entry_price
                return {
                    'exit_bar': i,
                    'exit_price': tp_price,
                    'pnl_pct': actual_pnl,
                    'exit_reason': 'TP',
                    'hold_bars': i - entry_bar,
                    'mfe': mfe,
                    'mae': mae
                }
            
            # Check SL
            if high >= sl_price:
                actual_pnl = (entry_price - sl_price) / entry_price
                return {
                    'exit_bar': i,
                    'exit_price': sl_price,
                    'pnl_pct': actual_pnl,
                    'exit_reason': 'SL',
                    'hold_bars': i - entry_bar,
                    'mfe': mfe,
                    'mae': mae
                }
        else:
            # LONG (not used for S9 but kept for completeness)
            pnl_pct = (close - entry_price) / entry_price
            favorable = (high - entry_price) / entry_price
            adverse = (low - entry_price) / entry_price
            mfe = max(mfe, favorable)
            mae = max(mae, adverse)
            
            if high >= tp_price:
                actual_pnl = (tp_price - entry_price) / entry_price
                return {
                    'exit_bar': i,
                    'exit_price': tp_price,
                    'pnl_pct': actual_pnl,
                    'exit_reason': 'TP',
                    'hold_bars': i - entry_bar,
                    'mfe': mfe,
                    'mae': mae
                }
            
            if low <= sl_price:
                actual_pnl = (sl_price - entry_price) / entry_price
                return {
                    'exit_bar': i,
                    'exit_price': sl_price,
                    'pnl_pct': actual_pnl,
                    'exit_reason': 'SL',
                    'hold_bars': i - entry_bar,
                    'mfe': mfe,
                    'mae': mae
                }
    
    # Max hold reached
    final_close = bars[min(entry_bar + max_hold, len(bars) - 1)]['close']
    if direction == 'SHORT':
        final_pnl = (entry_price - final_close) / entry_price
    else:
        final_pnl = (final_close - entry_price) / entry_price
    
    return {
        'exit_bar': min(entry_bar + max_hold, len(bars) - 1),
        'exit_price': final_close,
        'pnl_pct': final_pnl,
        'exit_reason': 'MAX_HOLD',
        'hold_bars': max_hold,
        'mfe': mfe,
        'mae': mae
    }

def calculate_metrics(trades: List[Dict]) -> Dict:
    """Calculate backtest metrics."""
    if not trades:
        return {
            'total_trades': 0,
            'win_rate': 0.0,
            'avg_pnl': 0.0,
            'total_pnl': 0.0,
            'sharpe': 0.0,
            'avg_rr': 0.0,
            'avg_mfe': 0.0,
            'avg_mae': 0.0,
            'avg_hold': 0.0
        }
    
    pnls = [t['pnl_pct'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    total_trades = len(trades)
    win_rate = len(wins) / total_trades if total_trades > 0 else 0.0
    avg_pnl = sum(pnls) / len(pnls)
    total_pnl = sum(pnls)
    
    # Sharpe ratio (annualized, assuming 15m bars = 4 bars/hour = 96 bars/day = 25200 bars/year)
    # Using per-bar returns
    if len(pnls) > 1:
        mean_pnl = sum(pnls) / len(pnls)
        variance = sum((x - mean_pnl) ** 2 for x in pnls) / len(pnls)
        std_pnl = math.sqrt(variance)
        sharpe = (mean_pnl / std_pnl) * math.sqrt(25200) if std_pnl > 0 else 0.0
    else:
        sharpe = 0.0
    
    # Risk/Reward (avg win / avg loss)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    avg_rr = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    # MFE/MAE
    mfes = [t['mfe'] for t in trades]
    maes = [abs(t['mae']) for t in trades]
    avg_mfe = sum(mfes) / len(mfes) if mfes else 0.0
    avg_mae = sum(maes) / len(maes) if maes else 0.0
    
    # Average hold
    avg_hold = sum(t['hold_bars'] for t in trades) / len(trades)
    
    return {
        'total_trades': total_trades,
        'win_rate': win_rate,
        'avg_pnl': avg_pnl,
        'total_pnl': total_pnl,
        'sharpe': sharpe,
        'avg_rr': avg_rr,
        'avg_mfe': avg_mfe,
        'avg_mae': avg_mae,
        'avg_hold': avg_hold
    }

def backtest_csv(csv_path: Path) -> Dict:
    """Run backtest on a single CSV file."""
    print(f"\n{'='*60}")
    print(f"Backtesting: {csv_path.name}")
    print(f"{'='*60}")
    
    # Load data
    bars = load_csv(csv_path)
    print(f"Loaded {len(bars)} bars")
    
    # Detect signals
    signals = detect_s9_signals(bars)
    print(f"Detected {len(signals)} S9 signals")
    
    if len(signals) == 0:
        return {
            'file': csv_path.name,
            'metrics': calculate_metrics([]),
            'trades': []
        }
    
    # Apply minimum gap between signals
    filtered_signals = []
    last_signal_bar = -SETUP_MIN_GAP
    for signal in signals:
        if signal['bar_idx'] - last_signal_bar >= SETUP_MIN_GAP:
            filtered_signals.append(signal)
            last_signal_bar = signal['bar_idx']
    
    print(f"After gap filter: {len(filtered_signals)} signals")
    
    # Simulate trades
    trades = []
    tp_count = 0
    sl_count = 0
    max_hold_count = 0
    
    for signal in filtered_signals:
        trade = simulate_trade(bars, signal, S9_TP_PCT, S9_SL_PCT, S9_MAX_HOLD)
        trades.append(trade)
        
        if trade['exit_reason'] == 'TP':
            tp_count += 1
        elif trade['exit_reason'] == 'SL':
            sl_count += 1
        else:
            max_hold_count += 1
    
    print(f"Trade outcomes: TP={tp_count}, SL={sl_count}, MaxHold={max_hold_count}")
    
    # Calculate metrics
    metrics = calculate_metrics(trades)
    
    return {
        'file': csv_path.name,
        'metrics': metrics,
        'trades': trades
    }

def main():
    """Run backtest on all CSV dumps."""
    csv_dir = Path('/Users/eugene/CascadeProjects/fresh CVB indicator project/tv-dumps')
    csv_files = list(csv_dir.glob('*.csv'))
    
    print(f"Found {len(csv_files)} CSV files")
    print(f"S9 Setup Parameters:")
    print(f"  TP: {S9_TP_PCT*100:.1f}%")
    print(f"  SL: {S9_SL_PCT*100:.1f}%")
    print(f"  Max Hold: {S9_MAX_HOLD} bars")
    print(f"  TE Threshold: {TE_SETUP_THRESH}")
    print(f"  LTF Decouple Threshold: {LTF_DECOUPLE_THRESH}")
    
    all_results = []
    all_trades = []
    
    for csv_file in sorted(csv_files):
        result = backtest_csv(csv_file)
        all_results.append(result)
        all_trades.extend(result['trades'])
    
    # Aggregate results
    print(f"\n{'='*60}")
    print("AGGREGATE RESULTS")
    print(f"{'='*60}")
    
    aggregate_metrics = calculate_metrics(all_trades)
    
    print(f"\nTotal Trades: {aggregate_metrics['total_trades']}")
    print(f"Win Rate: {aggregate_metrics['win_rate']*100:.2f}%")
    print(f"Avg PnL: {aggregate_metrics['avg_pnl']*100:.2f}%")
    print(f"Total PnL: {aggregate_metrics['total_pnl']*100:.2f}%")
    print(f"Sharpe: {aggregate_metrics['sharpe']:.2f}")
    print(f"Avg R:R: {aggregate_metrics['avg_rr']:.2f}")
    print(f"Avg MFE: {aggregate_metrics['avg_mfe']*100:.2f}%")
    print(f"Avg MAE: {aggregate_metrics['avg_mae']*100:.2f}%")
    print(f"Avg Hold: {aggregate_metrics['avg_hold']:.1f} bars")
    
    print(f"\n{'='*60}")
    print("PER-FILE RESULTS")
    print(f"{'='*60}")
    print(f"{'File':<40} {'Trades':>8} {'WR%':>8} {'AvgPnl%':>10} {'Sharpe':>8}")
    print(f"{'-'*60}")
    
    for result in all_results:
        m = result['metrics']
        print(f"{result['file']:<40} {m['total_trades']:>8} {m['win_rate']*100:>7.1f}% {m['avg_pnl']*100:>9.2f}% {m['sharpe']:>8.2f}")

if __name__ == '__main__':
    main()
