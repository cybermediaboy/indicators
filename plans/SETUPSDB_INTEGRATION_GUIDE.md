# setupsDB Integration Guide for CVB v20

## Summary
Replace hardcoded setup logic (lines 2893-3100) with data-driven setupsDB architecture.

## Files Created
- ✅ `/libs/setupsDBGem.pine` - Market orders, 0.15% friction (8 setups)
- ✅ `/libs/setupsDBQuen.pine` - Limit orders, 0.04% friction (5 setups)
- ✅ `Combined Vector Bands v20 setupsDB.pine` - Main indicator (partial)

## Changes Completed in v20
1. ✅ Added `import cybermediaboy/setupsDBGem/1 as SetupsDB` (line 12)
2. ✅ Updated indicator title to "CVB v20 setupsDB" (line 14)
3. ✅ Removed obsolete tracking vars: `last_s1-s12_bar`, `last_l5-l9_bar`, `last_setup1-4_bar`, `last_v4_bar` (lines 506-521)
4. ✅ Removed `last_s1_bar`, `last_l1_bar` from debounce section (line 2097)
5. ✅ Removed `last_v4_bar` and `vel_recouple` logic (line 2863)

## Remaining Work: Replace Hardcoded Setup Block

### Location
**Lines 2893-3100** in `Combined Vector Bands v20 setupsDB.pine`

### DELETE THIS ENTIRE BLOCK:
```pine
// Lines 2893-3100: All hardcoded setup_s1-s12, setup_l1-l9, setup_v1-v4 definitions
// Lines 2961-3070: pred_round_delay_active armed setup logic
// Lines 3014-3022: setup_corr_bottom_mr_confirm, setup_corr_peak_mr_confirm, setup_bear_div_oversold
// Lines 3024-3070: Armed setup delay logic (S5, L2, V1, V2, V4)
// Lines 3072-3100: setup_cld_fall_rise_up + all SetupsLib.f_register_event_auto() calls
```

### REPLACE WITH THIS CODE:

```pine
// Call setupsDB to evaluate all setups
var array<SetupsDB.SetupConfig> triggered_setups = na
triggered_setups := SetupsDB.evaluate_all(
    int(z0 * 1200),  // entry_ctx: map z0 to context codes (1000/1100/1200)
    nz(mr_for_setups),
    nz(basket_vec_z),
    nz(basket_vec_z),
    nz(burst_pct_val),
    nz(te_osc),
    close,
    nz(fv_cyclic_kalman),
    nz(ma0),
    nz(pred_vec_ma),
    nz(PhiTotal_orth),
    nz(innov_band_lower),
    nz(innov_band_upper),
    innov_width,
    innov_width_med,
    nz(z3_dn),
    vwap_short_rej_active,
    vwap_long_rej_active,
    nz(squeeze_bull),
    nz(mc_knn_confidence)
)

// Process triggered setups from database
array<SetupsLib.SetupEvent> engine_events = array.new<SetupsLib.SetupEvent>()
if array.size(triggered_setups) > 0
    for i = 0 to array.size(triggered_setups) - 1
        SetupsDB.SetupConfig cfg = array.get(triggered_setups, i)
        
        // Direction-based cooldown check
        int last_bar = cfg.dir == "SHORT" ? last_pred_short_bar : last_pred_long_bar
        bool is_dir_allowed = (cfg.dir == "SHORT" and allow_short) or (cfg.dir == "LONG" and allow_long)
        bool cooldown_ok = f_setup_cooldown_ok(cfg.id, cfg.dir, last_bar)
        
        if is_dir_allowed and cooldown_ok
            // Register setup event
            string tooltip_data = cfg.name + " | WR: " + str.tostring(cfg.wr, "#.#") + "% | Sharpe: " + str.tostring(cfg.sharpe, "#.###")
            SetupsLib.f_register_event_auto(engine_events, SETUP_DB, true, cfg.id, tooltip_data)

// DEBUG REMOVED: setup_debug_code, setup_debug_mask

// Reset MC visualization variables at start of each bar
mae_viz_price := na
mfe_viz_price := na
```

### UPDATE ENGINE EVENT PROCESSING (lines 3105-3133):

**REPLACE** the `last_setup1_bar` through `last_setup4_bar` tracking logic with:

```pine
int engine_event_count = array.size(engine_events)
if engine_event_count > 0
    for i = 0 to engine_event_count - 1
        SetupsLib.SetupEvent setup_event = array.get(engine_events, i)
        [next_pos, next_last_trigger_bar, next_mae, next_mfe, next_entry_ctx, next_fire_code] = f_fire_setup_by_id(setup_event.id, setup_event.tooltip, setup_event.size_info, last_setup_trigger_bar)
        if next_fire_code != 0
            actualfiresignal := next_fire_code
        pos := next_pos
        last_setup_trigger_bar := next_last_trigger_bar
        
        // Update visualization variables
        if not na(next_mae)
            mae_viz_price := next_mae
        if not na(next_mfe)
            mfe_viz_price := next_mfe
        
        // Update direction-based cooldown trackers
        if setup_event.id == "S11" or setup_event.id == "S3" or setup_event.id == "S_Inn" or setup_event.id == "S_Trap" or setup_event.id == "S8" or setup_event.id == "S4"
            last_pred_short_bar := bar_index
        else if setup_event.id == "L6" or setup_event.id == "L_Exp"
            last_pred_long_bar := bar_index
```

## Variables to Remove References To

Search and remove/replace all references to these obsolete variables:
- `setup_s1` through `setup_s12`
- `setup_l1` through `setup_l9`
- `setup_v1` through `setup_v4`
- `setup_corr_bottom_mr_confirm`
- `setup_corr_peak_mr_confirm`
- `setup_bear_div_oversold`
- `setup_cld_fall_rise_up`
- `fire_l1`, `fire_l2`, `fire_l3`
- `pred_round_delay_active` (if not used elsewhere)
- `armed_setup_id`, `armed_bar`, `armed_direction`, `armed_tooltip`, `armed_size_info`, `armed_conditions_mr`, `armed_conditions_z0` (if not used elsewhere)

## Benefits After Integration

### Code Reduction
- **~210 lines removed** from main indicator
- **~19 global variables removed** (all `last_sX_bar`, `last_lX_bar` trackers)
- **~25 boolean setup variables removed** (all `setup_sX`, `setup_lX`)

### Architecture Improvements
- ✅ **Single Source of Truth**: All setup logic in external library
- ✅ **Plug-and-Play**: Switch between Gem/Quen by changing one import line
- ✅ **Zero Hardcoding**: No setup formulas in main indicator
- ✅ **Memory Efficient**: Setup logic scoped to library, not global

### Switching Between Databases

**For Market Orders (0.15% friction):**
```pine
import cybermediaboy/setupsDBGem/1 as SetupsDB
```

**For Limit Orders (0.04% friction, scalping):**
```pine
import cybermediaboy/setupsDBQuen/1 as SetupsDB
```

## Testing Checklist

After integration:
1. ☐ Compile script - verify no syntax errors
2. ☐ Check setup labels appear on chart
3. ☐ Verify TP/SL lines draw correctly
4. ☐ Confirm cooldown logic works (no consecutive fires)
5. ☐ Test switching between setupsDBGem and setupsDBQuen
6. ☐ Run backtest to verify setup triggers match expected behavior

## Notes

- The setupsDB libraries use **different setup IDs** than the old system (S11, S3, L6 vs old S1-S12, L1-L9)
- Entry context mapping may need adjustment: `int(z0 * 1200)` is a placeholder
- VWAP rejection flags need to be mapped correctly (`vwap_short_rej_active`, `vwap_long_rej_active`)
- `burst_pct_val` should be the burst score oscillator value
- `pred_vec_ma` should be the predictive vector MA line

## Contact

If you encounter compilation errors after integration, check:
1. All old setup variable references are removed
2. `f_fire_setup_by_id()` function signature matches new setup IDs
3. setupsDB libraries are published to TradingView with correct version numbers
