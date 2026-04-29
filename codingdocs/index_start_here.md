# CODINGDOCS — Start Here

> **For AI coders and human developers.**  
> Load this file first. It maps every doc to a context-window budget and tells you which file to load for which task.

---

## What This Folder Is

This folder contains the **authoritative conventions, error cookbook, and architectural principles** for all Pine Script v5/v6 development in this repository. Every rule here is extracted from real indicator cascades (5+ production indicators, 98 gap-entries, 50+ deduplicated error trajectories). Nothing is theoretical.

**Repo:** `cybermediaboy/indicators`  
**Branch:** `main`  
**Path:** `codingdocs/`  
**Last updated:** 2026-04-28

---

## File Map — Load Only What You Need

| File | Purpose | Load when | ~Tokens |
|------|---------|-----------|--------|
| **`index_start_here.md`** | This file. Navigation hub. | Always load first | ~600 |
| **`EUGENES_PINE_PRINCIPLES.md`** | 98 canonical principles (G1-G98). The master rule set. | Starting any new indicator or library task | ~5,000 |
| **`COMPILE_ERROR_COOKBOOK.md`** | Navigation hub for error catalog. Links to sub-files. | Got a compiler/runtime error | ~800 |
| **`cookbook/3.1_compile_blockers.md`** | 60+ hard compiler-reject patterns with before/after/fix | Error is a compile-time message | ~6,000 |
| **`cookbook/3.2_runtime_errors.md`** | RE10045, history-limit, memory-limit, NaN cascade | Indicator crashes at runtime | ~2,000 |
| **`cookbook/3.3_logic_silent_bugs.md`** | No error, wrong output (stdev collapse, exp(0)=1, dim explosion) | Output looks wrong but no error message | ~2,500 |
| **`cookbook/3.4_token_budget_bugs.md`** | 80k AST cap, UDT dot penalty, dead code removal | Token limit exceeded | ~1,500 |
| **`cookbook/3.5_performance_limit_bugs.md`** | Heavy-bar gating, request.security cap, LTF traps | Memory limit / slow chart / LTF flat | ~2,000 |
| **`LIBRARY_UPDATE_INSTRUCTIONS.md`** | Step-by-step protocol for updating any of the 4 libs | Modifying a library (MCLib, MLLib, CausalityLib, TAUtilityLib) | ~3,500 |
| **`AI_CODER_PROMPT_TEMPLATE.md`** | Prompt sections A-D for any AI coder working on this codebase | Delegating a task to an AI coder | ~2,500 |
| **`EDITION_AUTHORING_GUIDE.md`** | How to create a new indicator edition | Creating a new indicator variant | ~1,500 |
| **`MIGRATION_GUIDE.md`** | 7-phase protocol for migrating indicators to updated libs | Migrating an indicator after lib changes | ~3,000 |
| **`repros/`** | Minimal Pine Script reproducers for Tier-1 error patterns | Verifying an error pattern live in TV editor | ~50 tokens/file |

**Total if loading everything:** ~31,000 tokens. Never load all at once — use the task map below.

---

## Task → File Map (context-window efficient)

### "Write a new indicator from scratch"
```
Load: index_start_here.md + EUGENES_PINE_PRINCIPLES.md + AI_CODER_PROMPT_TEMPLATE.md
```

### "Fix a compiler error"
```
1. Search §0 of COMPILE_ERROR_COOKBOOK.md (keyword / symptom index)
2. Load only the relevant sub-file (3.1 / 3.2 / 3.3 / 3.4 / 3.5)
3. Find entry by Gap ID (e.g. G15) or error message substring
```

### "Update a library"
```
Load: LIBRARY_UPDATE_INSTRUCTIONS.md + relevant lib section of EUGENES_PINE_PRINCIPLES.md (§G7-G14)
```

### "Create a new indicator edition"
```
Load: EDITION_AUTHORING_GUIDE.md + EUGENES_PINE_PRINCIPLES.md §G37-G46
```

### "Migrate indicator after lib update"
```
Load: MIGRATION_GUIDE.md + LIBRARY_UPDATE_INSTRUCTIONS.md §post-lib-changes
```

### "Indicator output looks wrong (no error)"
```
Load: cookbook/3.3_logic_silent_bugs.md + cookbook/3.5_performance_limit_bugs.md
```

### "Token limit exceeded"
```
Load: cookbook/3.4_token_budget_bugs.md + EUGENES_PINE_PRINCIPLES.md §G49
```

---

## Codebase Architecture (30-second orientation)

```
cybermediaboy/indicators/
├── Combined Vector Bands v20 setupsDB.pine   ← main production indicator
├── libs/
│   ├── MCLib          ← Monte Carlo engine
│   ├── MLLib          ← KNN + ML helpers
│   ├── CausalityLib   ← Granger, copula, correlation
│   └── TAUtilityLib   ← label/line rendering, logger, utility UDTs
├── codingdocs/        ← YOU ARE HERE
│   ├── index_start_here.md
│   ├── EUGENES_PINE_PRINCIPLES.md
│   ├── COMPILE_ERROR_COOKBOOK.md
│   ├── cookbook/      ← error catalog sub-files
│   ├── repros/        ← minimal .pine reproducers
│   └── ...
└── wiki-codemap.md    ← legacy code map (superseded by codingdocs/)
```

**Single Source of Truth (SPoT) — Axiom #0:**  
Every rule lives in one place. `EUGENES_PINE_PRINCIPLES.md` is the master. If any other file conflicts with it, the Principles file wins.

---

## Gap ID System

Every documented error/pattern/principle has a Gap ID: `G1` through `G98` (as of 2026-04-28).  
Gap IDs appear in:
- `EUGENES_PINE_PRINCIPLES.md` (definition)
- `COMPILE_ERROR_COOKBOOK.md` sub-files (error catalog entries)
- `repros/` filenames (e.g. `G15_hline_series_value.pine`)
- Inline `// G15` comments in production .pine files where the fix was applied

**Tier system:**
- **Tier 1** (~38 entries): frequency ≥2 OR severity=compile-blocker. In main doc body.
- **Tier 2** (~32 entries): single occurrence, medium severity. In annexes.
- **Tier 3** (~28 entries): niche, situational. In cookbook sub-files only.

---

## Pine Version Notes

| Feature | v5 | v6 |
|---------|----|----|  
| Local scope limit | 550 | Unlimited (Feb 2025) |
| `export type` | ❌ | ✅ required for cross-file UDTs |
| `request.footprint()` | ❌ | ✅ Premium+ (Jan 2026) |
| Maps, UDTs | Limited | Full |
| Enums | ❌ | ✅ |
| `runtime.log()` | ❌ | ✅ |
| Dynamic requests in loops | ❌ | ✅ |

All production code in this repo targets **Pine Script v6**.

---

## Logger Flush — Critical Rule (read before touching TAUtilityLib)

The logger in TAUtilityLib has **3 flush modes**:
- `BUFFERED` — auto-flushes when buffer hits ~4000 chars OR line_count ≥ 2500. No `barstate.islast` dependency.
- `PER_BAR` — flushes on `barstate.isconfirmed` (confirmed close only).
- `EXPLICIT` — manual `flush()` call at natural boundaries (e.g. RCOM completion).

`barstate.islast` is **NOT** a flush trigger in any mode. Using it as one is a known anti-pattern (G37).

---

## Var Limit Rule

- **Hard limit:** `var` declarations < 500 per script
- **Practical target:** < 300
- **UDT instance** = 1 slot regardless of field count
- Exceeding 500 causes silent degradation before hard compiler rejection

---

*Generated 2026-04-28 from 5 production indicators + 3 error batches + trajectory 3c7c97da*  
*Gap tracker: G1-G98 | Tier 1: ~38 | Tier 2: ~32 | Tier 3: ~28*
