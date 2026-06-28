# EMA / Price Action / Fibonacci ETF Research

- Generated: 2026-06-21T17:18:01
- Period: 2019-01-01 to 2026-06-18 (1808 trading dates)
- Adjust: qfq
- Universe size: 22
- Experimental trials: 9
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
| ema_momentum_rotation | 4 | 3 | 47.69% | 16.98% | 0.835 | 54.15% | 23.44% | -23.73% | 1.482 |
| fibonacci_retracement_rotation | 1 | 0 | -13.83% | -44.54% | -1.218 | -13.83% | -44.54% | -22.64% | -0.435 |
| price_action_breakout_rotation | 4 | 0 | -11.55% | -42.26% | -0.893 | -8.92% | -39.63% | -27.86% | -0.226 |

## Top Experimental Trials

| rank | strategy | score | accepted | test ret | test excess | test dd | test calmar | wf beat | full ret | full dd | params |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ema_momentum_rotation | 0.835 | yes | 54.15% | 23.44% | -23.73% | 1.482 |  | 158.36% | -45.87% | {"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash","fast_ema":20,"min_da... |
| 2 | ema_momentum_rotation | 0.748 | yes | 55.37% | 24.66% | -23.73% | 1.513 |  | 186.33% | -44.73% | {"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash","fast_ema":20,"min_da... |
| 3 | ema_momentum_rotation | 0.619 | yes | 41.22% | 10.51% | -22.79% | 1.192 |  | 22.92% | -47.50% | {"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash","fast_ema":30,"min_da... |
| 4 | ema_momentum_rotation | 0.086 | no | 23.33% | -7.38% | -30.16% | 0.521 |  | 117.95% | -46.83% | {"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash","fast_ema":10,"min_da... |
| 5 | price_action_breakout_rotation | -0.893 | no | -8.92% | -39.63% | -27.86% | -0.226 |  | 28.97% | -27.86% | {"breakout_buffer":0.99,"cash_entry_confirmations":2,"cash_entry_mode":"daily_when_cash... |
