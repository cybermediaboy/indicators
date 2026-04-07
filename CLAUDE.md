# CLAUDE.md — Project Intelligence Index

## Identity
Quant trading system: Pine Script v5 indicators + Python backtesting/ML pipeline.
Crypto-native (BTC, ETH, SOL, BNB baskets). Multi-timeframe. TradingView-deployed.

## Role Rules
- Technical tone only. No praise, no empathy, no filler.
- Scientific method: modular reasoning, hedge only on real uncertainty.
- Output code directly. Explanations only when structurally necessary.
- Diff-only for edits >20 lines. Never rewrite full files for small changes.

## Architecture
See `.claude/docs/architecture.md` for system structure and data flow.

## Pine Script Standards
See `.claude/docs/pine-conventions.md` for all Pine v5 rules.
Key constraints loaded there: var hygiene, f_ prefix functions, Z-score normalization,
Kalman filter state management, request.security patterns.

## Python Standards
See `.claude/docs/python-conventions.md` for backtesting and ML pipeline rules.
Covers: pandas idioms, vectorized ops, no lookahead, walk-forward validation.

## Mathematical Modeling
See `.claude/docs/kalman-state-space.md` for state-space model conventions.
Covers: Kalman filter patterns, covariance propagation, adaptive R/Q, Z-score space ops.

## Backtesting Protocol
See `.claude/docs/backtesting.md` for methodology and validation rules.
Covers: OOS splits, Monte Carlo, transaction costs, survivorship bias.

## Token Efficiency Contract
1. One task per conversation. Clear context between unrelated tasks.
2. Load only files relevant to the current task.
3. Return code blocks only — no preamble, no recap, no "here's what I did".
4. For refactors: output only changed functions, not the entire file.
5. When asked to plan: return a numbered list of steps, max 1 sentence each.
6. Never repeat the user's question back.
7. Never add comments that restate what the code obviously does.
