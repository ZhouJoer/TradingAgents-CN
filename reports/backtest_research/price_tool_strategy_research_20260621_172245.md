# EMA / Price Action / Fibonacci ETF Research

- Generated: 2026-06-21T17:22:45
- Period: 2019-01-01 to 2026-06-18 (1808 trading dates)
- Adjust: qfq
- Universe size: 22
- Experimental trials: 60
- Costs: commission 5.0 bps, slippage 5.0 bps

## Holdout Splits

| split | start | end |
| --- | --- | --- |
| train | 2019-01-02 | 2023-06-20 |
| validation | 2023-06-21 | 2024-12-17 |
| test | 2024-12-18 | 2026-06-18 |

## Baselines

| strategy | test ret | test excess | test dd | test calmar | full ret | full dd | full calmar | trades |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| industry_momentum_enhanced | 97.18% | 66.47% | -29.75% | 2.031 | 525.16% | -35.13% | 0.828 | 81 |
| biweekly_adaptive_stable_rotation | 13.52% | -17.19% | -21.71% | 0.425 | 148.80% | -33.06% | 0.410 | 384 |
| dual_momentum_core | 51.77% | 21.06% | -27.98% | 1.204 | 190.13% | -44.67% | 0.358 | 255 |
| trend_following_equal_weight | 50.08% | 19.37% | -21.58% | 1.513 | 216.89% | -36.85% | 0.473 | 521 |

## Experimental Family Summary

| strategy | trials | accepted | median test ret | median test excess | best score | best test ret | best test excess | best test dd | best test calmar |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ema_momentum_rotation | 21 | 1 | 42.90% | 12.19% | 2.781 | 93.16% | 62.44% | -15.81% | 3.677 |
| fibonacci_retracement_rotation | 18 | 0 | -8.17% | -38.88% | 2.796 | 63.60% | 32.89% | -11.86% | 3.446 |
| price_action_breakout_rotation | 21 | 2 | 17.44% | -13.27% | 1.445 | 33.52% | 2.81% | -13.47% | 1.654 |

## Top Experimental Trials

| rank | strategy | score | accepted | test ret | test excess | test dd | test calmar | wf beat | full ret | full dd | params |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | fibonacci_retracement_rotation | 2.796 | no | 63.60% | 32.89% | -11.86% | 3.446 | 75.00% | 35.77% | -48.16% | {"bounce_days":3,"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash","fib_... |
| 2 | ema_momentum_rotation | 2.781 | no | 93.16% | 62.44% | -15.81% | 3.677 | 50.00% | 128.18% | -62.36% | {"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash","fast_ema":10,"min_da... |
| 3 | ema_momentum_rotation | 2.716 | no | 85.99% | 55.28% | -15.60% | 3.464 | 50.00% | 151.73% | -54.04% | {"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash","fast_ema":40,"min_da... |
| 4 | ema_momentum_rotation | 1.474 | yes | 52.04% | 21.33% | -17.87% | 1.895 | 75.00% | 92.25% | -55.81% | {"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash","fast_ema":30,"min_da... |
| 5 | price_action_breakout_rotation | 1.445 | yes | 33.52% | 2.81% | -13.47% | 1.654 | 50.00% | 48.78% | -33.19% | {"breakout_buffer":0.99,"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash... |
| 6 | ema_momentum_rotation | 1.401 | no | 69.10% | 38.39% | -23.65% | 1.867 | 75.00% | 200.62% | -45.10% | {"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash","fast_ema":30,"min_da... |
| 7 | ema_momentum_rotation | 1.187 | no | 67.81% | 37.10% | -21.82% | 1.988 | 50.00% | 217.59% | -41.94% | {"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash","fast_ema":20,"min_da... |
| 8 | price_action_breakout_rotation | 1.017 | yes | 53.18% | 22.46% | -22.38% | 1.544 | 50.00% | 107.86% | -43.29% | {"breakout_buffer":0.97,"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash... |
| 9 | ema_momentum_rotation | 0.974 | no | 55.37% | 24.66% | -23.73% | 1.513 | 75.00% | 186.33% | -44.73% | {"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash","fast_ema":20,"min_da... |
| 10 | ema_momentum_rotation | 0.973 | no | 83.01% | 52.30% | -29.05% | 1.800 | 0.00% | 37.83% | -64.43% | {"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash","fast_ema":20,"min_da... |
| 11 | fibonacci_retracement_rotation | 0.934 | no | 26.19% | -4.52% | -15.07% | 1.167 | 50.00% | 72.62% | -52.02% | {"bounce_days":3,"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash","fib_... |
| 12 | ema_momentum_rotation | 0.894 | no | 54.15% | 23.44% | -23.73% | 1.482 | 75.00% | 158.36% | -45.87% | {"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash","fast_ema":20,"min_da... |
| 13 | price_action_breakout_rotation | 0.843 | no | 67.33% | 36.61% | -20.48% | 2.105 | 0.00% | 34.98% | -65.05% | {"breakout_buffer":0.99,"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash... |
| 14 | price_action_breakout_rotation | 0.645 | no | 53.63% | 22.92% | -19.04% | 1.829 | 25.00% | -22.23% | -66.70% | {"breakout_buffer":1.0,"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash"... |
| 15 | ema_momentum_rotation | 0.558 | no | 54.53% | 23.82% | -22.28% | 1.588 | 25.00% | 175.84% | -50.61% | {"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash","fast_ema":30,"min_da... |
