"""
Setup Decode Utility for CVB v19 Indicator Analysis

Bit-encoded export reference (from Combined Vector Bands v19 kNN+ConeFilter.pine):
- Debug Combined (col 39): setup_debug_merged + cld_debug_bitfield * 100000.0
- setup_debug_merged: setup_code + (setup_code > 0 ? 10000.0 : 0.0) + (is_realtime ? 20000.0 : 0.0)
- cld_debug_bitfield: (cld_continuation?100:0) + (cld_exhaustion?200:0) + (macro_exhaustion?300:0)
"""

# Complete setup debug code mapping from indicator (lines ~3929-3981)
SETUP_CODE_MAP = {
    # S setups (category 1) — all SHORT context
    100:  ('S1',  'SHORT'),    # TE0.8+LTFlow
    500:  ('S5',  'SHORT'),    # LTFlow
    600:  ('S6',  'SHORT'),    # MRStrict-0.5
    700:  ('S7',  'SHORT'),    # TE+VecDiv
    800:  ('S8',  'SHORT'),    # SReentry+VecDiv
    900:  ('S9',  'SHORT'),    # CFV+TE+LTFlo
    1000: ('S10', 'SHORT'),    # PredMA+VelDec
    1110: ('S11', 'SHORT'),    # LTF+MR+Coupled
    1120: ('S12', 'SHORT'),    # L9/S12 PhiDiv divergence
    # L setups (category 1, 11xx-19xx) — all LONG context
    1100: ('L1', 'LONG'),      # TE0.8+CFVrise
    1200: ('L2', 'LONG'),
    1300: ('L3', 'LONG'),
    1500: ('L5', 'LONG'),      # MRStrict+0.5
    1600: ('L6', 'LONG'),      # LReentry+VecDiv
    1700: ('L7', 'LONG'),      # CFV+TE+LTFhi
    1800: ('L8', 'LONG'),      # PredMA+VelRec
    1900: ('L9', 'LONG'),      # PhiDiv long
    # V setups (category 2) — engine events
    2100: ('V1', 'LONG'),      # BounceFire
    2200: ('V2', 'SHORT'),     # MRSetup
    2300: ('V3', 'LONG'),      # Transition
    2400: ('V4', 'LONG'),      # VelRecouple
    # Numeric setups (category >=5)
    8100: ('81', 'LONG'),      # CORR⊥+MR
    7300: ('73', 'SHORT'),     # CORR↑+MR
    7500: ('75', 'SHORT'),     # BearDiv⊥OS
    6400: ('64', 'LONG'),      # CLD↗
}

# Lloyd-Max TurboQuant centroids (for packed vector reconstruction)
LM_CENTROIDS = [-2.152, -1.344, -0.756, -0.245, 0.245, 0.756, 1.344, 2.152]


def decode_setup(code: float) -> tuple:
    """
    Decode setup debug code from Pine Script indicator.

    Args:
        code: Raw debug code (e.g., 2200.0, 1000.0, 1110.0, or combined with state bits)

    Returns:
        (label, direction, category, number)
        Returns (None, None, None, None) for code == 0
    """
    if code == 0 or code is None:
        return None, None, None, None

    rel = int(code) % 10000  # Strip realtime/state bits

    # Derive category and number from the raw setup code
    if rel < 1100 and rel >= 100:
        cat = 1  # S setups: S1=100, S5=500, S6=600, ...
        num = rel // 100
        if rel == 1000:
            num = 10
        elif rel == 1110:
            num = 11  # won't hit (>=1100), handled below
        elif rel == 1120:
            num = 12  # won't hit (>=1100), handled below
    elif 1100 <= rel < 2000:
        cat = 1  # L setups + S11, S12
        if rel == 1100:
            num = 1  # L1
        elif rel == 1110:
            num = 11  # S11
        elif rel == 1120:
            num = 12  # S12
        elif rel == 1200:
            num = 2  # L2
        elif rel == 1300:
            num = 3  # L3
        elif rel == 1500:
            num = 5  # L5
        elif rel == 1600:
            num = 6  # L6
        elif rel == 1700:
            num = 7  # L7
        elif rel == 1800:
            num = 8  # L8
        elif rel == 1900:
            num = 9  # L9
        else:
            num = (rel - 1000) // 100
    elif 2000 <= rel < 3000:
        cat = 2  # V setups
        num = (rel - 2000) // 100
    else:
        cat = 3  # Numeric setups
        num = rel

    if rel in SETUP_CODE_MAP:
        label, direction = SETUP_CODE_MAP[rel]
        return label, direction, cat, num

    # Numeric setups can appear as full codes (7300, 7500, 8100, 6400)
    full_code = int(code)
    if full_code in SETUP_CODE_MAP:
        label, direction = SETUP_CODE_MAP[full_code]
        return label, direction, cat, num

    return f'UNK{rel}', 'BOTH', cat, num


def decode_debug_combined(value: float) -> dict:
    """
    Full decode of Debug Combined column (col 39).

    Returns dict with setup_code, setup_label, direction, is_realtime,
    cld_continuation, cld_exhaustion, macro_exhaustion.
    """
    if value == 0 or value is None:
        return None

    setup_merged = int(value) % 100000
    cld_code = int(value) // 100000

    setup_code = setup_merged % 10000
    is_active = (setup_merged // 10000) % 10 >= 1
    is_realtime = (setup_merged // 20000) % 10 >= 1

    label, direction, cat, num = decode_setup(setup_code)

    return {
        'setup_code': setup_code,
        'setup_label': label,
        'direction': direction,
        'is_active': is_active,
        'is_realtime': is_realtime,
        'cld_continuation': cld_code == 100,
        'cld_exhaustion': cld_code == 200,
        'macro_exhaustion': cld_code == 300,
    }


def decode_knn_superpack(value: float) -> dict:
    """
    Decode kNN Superpack column (col 41).

    NEW 41-bit layout: confidence(7b, bits 34-40) | corr_damping(3b, bits 31-33)
    | family(3b, bits 28-30) | packed_vec(28b, bits 0-27)
    Formula: (confidence << 34) | (damping_q << 31) | (family << 28) | packed_vec

    Returns dict with confidence, corr_damping, family, family_name, packed_vec,
    and reconstructed 7 features (approximate via Lloyd-Max centroids).
    """
    if value == 0 or value is None:
        return None

    value = int(value)
    confidence = value // 17179869184  # 2^34
    remainder1 = value % 17179869184
    damping_q = remainder1 // 2147483648  # 2^31
    remainder2 = remainder1 % 2147483648
    family = remainder2 // 268435456  # 2^28
    packed_vec = remainder2 % 268435456

    corr_damping = damping_q / 7.0  # Quantized 0-7 → 0.00-1.00
    family_names = {0: 'Continuation', 1: 'MR', 2: 'Transition', 3: 'Velocity', 4: 'Uncertain'}

    # Unpack 7 features from 28-bit packed vector
    # f_pack_vector_7: idx_n + res_n * 2^(3+4*n) for n=0..6
    features = {}
    pv = packed_vec
    for i in range(7):
        shift_idx = 4 * i
        shift_res = shift_idx + 3
        idx = (pv >> shift_idx) & 0b111
        res = (pv >> shift_res) & 0b1
        centroid = LM_CENTROIDS[idx]
        # Residual: 0 = lower half, 1 = upper half of Voronoi cell
        # Approximate adjustment: ±0.2 from centroid boundary
        adjustment = (res - 0.5) * 0.4
        features[f'f{i+1}'] = {
            'index': idx,
            'residual': res,
            'centroid': centroid,
            'reconstructed': round(centroid + adjustment, 3),
        }

    return {
        'confidence': confidence,
        'corr_damping': round(corr_damping, 2),
        'corr_damping_q': damping_q,
        'family': family,
        'family_name': family_names.get(family, 'Unknown'),
        'packed_vec': packed_vec,
        'features': features,
    }


def decode_setup_context_flags(value: float) -> dict:
    """Decode Setup Context Flags column (col 35)."""
    if value == 0 or value is None:
        return {}

    v = int(value)
    flags = {
        'pred_rounded':       bool(v & 0x0001),
        'pred_round_long':    bool(v & 0x0002),
        'pred_round_short':   bool(v & 0x0004),
        'ltf_is_decoupled':   bool(v & 0x0008),
        'ltf_decouple_event': bool(v & 0x0010),
        'ltf_recouple_event': bool(v & 0x0020),
        'phi_informative':    bool(v & 0x0040),
        'bounce_event':       bool(v & 0x0080),
        'mr_event':           bool(v & 0x0100),
        'transition_event':   bool(v & 0x0200),
        'cld_continuation':   bool(v & 0x0400),
        'cld_exhaustion':     bool(v & 0x0800),
        'macro_exhaustion':   bool(v & 0x1000),
        'continuation_setup': bool(v & 0x2000),
        'idiosyncratic_flow': bool(v & 0x4000),
        'is_falling_knife':   bool(v & 0x8000),
    }
    return flags


def decode_csv_row(row: dict) -> dict:
    """
    Decode all bit-encoded columns from a single CSV row dict.

    Expected keys: 'Debug Combined', 'Trade State', 'MC Debug',
    'Entry Context', 'Exit Context', 'Setup Context Flags',
    'Basket Fit (0-100)', 'TE Direction',
    'kNN Superpack (Conf|Family|Features)'

    Returns dict with all decoded fields.
    """
    result = {}

    # Debug Combined (col 39)
    if 'Debug Combined' in row:
        result['debug'] = decode_debug_combined(float(row['Debug Combined']))

    # Setup Context Flags (col 35)
    if 'Setup Context Flags' in row:
        result['context_flags'] = decode_setup_context_flags(float(row['Setup Context Flags']))

    # kNN Superpack (col 41)
    if 'kNN Superpack (Conf|Family|Features)' in row:
        val = row['kNN Superpack (Conf|Family|Features)']
        if val and val.strip():
            result['knn'] = decode_knn_superpack(float(val))

    # Continuous columns
    if 'Basket Fit (0-100)' in row:
        result['basket_fit'] = float(row['Basket Fit (0-100)']) if row['Basket Fit (0-100)'] else None
    if 'TE Direction' in row:
        result['te_direction'] = float(row['TE Direction']) if row['TE Direction'] else None

    return result


def calculate_pnl(entry: float, exit: float, direction: str) -> float:
    """PnL as percentage (positive = win, negative = loss)."""
    if direction == 'LONG':
        return (exit - entry) / entry
    elif direction == 'SHORT':
        return (entry - exit) / entry
    else:
        return (exit - entry) / entry


def decode_batch(setup_codes: list) -> list:
    """Batch decode multiple setup codes."""
    return [decode_setup(c) for c in setup_codes]


if __name__ == '__main__':
    test_codes = [
        2200.0,   # V2 raw -> SHORT
        12200.0,  # V2 history (active flag) -> SHORT
        42200.0,  # V2 realtime -> SHORT
        2300.0,   # V3 raw -> LONG
        11000.0,  # S10 history (1000+10000) -> SHORT
        31000.0,  # S10 realtime (1000+10000+20000) -> SHORT
        11110.0,  # S11 history (1110+10000) -> SHORT
        500.0,    # S5 -> SHORT
        600.0,    # S6 -> SHORT
        7300.0,   # 73 -> SHORT
        7500.0,   # 75 -> SHORT
        0.0,      # No setup -> None
        6400.0,   # 64 -> LONG
        1120.0,   # S12 -> SHORT
        1900.0,   # L9 -> LONG
        11100.0,  # L1 history (1100+10000) -> LONG
        100100.0, # S1 + CLD continuation -> SHORT
    ]

    print("Setup Decode (v19 complete mapping):")
    print("-" * 62)
    for code in test_codes:
        label, direction, cat, num = decode_setup(code)
        label_str = label or 'None'
        dir_str = direction or 'None'
        print(f"Code {code:>8.1f} -> {label_str:>12} | {dir_str:>6} | cat={cat} num={num}")

    # Demo: decode kNN superpack from actual CSV
    print("\n\nkNN Superpack Decode Demo:")
    print("-" * 62)
    sample = 52657278706
    result = decode_knn_superpack(sample)
    if result:
        print(f"  Confidence: {result['confidence']}%")
        print(f"  Family:     {result['family']} ({result['family_name']})")
        print(f"  Packed vec: {result['packed_vec']}")
        for fname, fdata in result['features'].items():
            print(f"  {fname}: idx={fdata['index']} res={fdata['residual']} → ~{fdata['reconstructed']}")
