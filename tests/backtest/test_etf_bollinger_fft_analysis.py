from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from scripts.analyze_etf_bollinger_fft import (
    AnalysisConfig,
    build_outcome,
    event_indices,
    fft_features,
)


def _config(**overrides) -> AnalysisConfig:
    values = {
        "boll_window": 20,
        "boll_k": 2.0,
        "squeeze_lookback": 60,
        "squeeze_quantile": 0.2,
        "contraction_days": 3,
        "event_mode": "squeeze-start",
        "event_cooldown": 20,
        "horizons": [5],
        "large_move_threshold": 0.08,
        "fft_window": 64,
        "fft_min_period": 5.0,
        "fft_max_period": None,
        "fft_top_k": 3,
        "control_samples_per_event": 5,
        "seed": 7,
        "permutation_rounds": 0,
    }
    values.update(overrides)
    return AnalysisConfig(**values)


class ETFBollingerFFTAnalysisTest(unittest.TestCase):
    def test_squeeze_start_requires_low_width_crossing_and_contraction(self) -> None:
        widths = [0.12] * 70 + [0.11, 0.10, 0.09, 0.079] + [0.078] * 40
        group = pd.DataFrame(
            {
                "boll_width": widths,
                "squeeze_threshold": [0.08] * len(widths),
            }
        )
        group["is_low_width"] = group["boll_width"] <= group["squeeze_threshold"]

        indices = event_indices(group, _config())

        self.assertEqual(indices, [73])

    def test_build_outcome_marks_large_future_move(self) -> None:
        dates = pd.bdate_range("2024-01-01", periods=20)
        closes = [100.0] * 20
        highs = [101.0] * 20
        lows = [99.0] * 20
        highs[13] = 112.0
        group = pd.DataFrame(
            {
                "code": ["510300"] * 20,
                "trade_date": dates,
                "open": closes,
                "high": highs,
                "low": lows,
                "close": closes,
                "boll_width": [0.05] * 20,
                "squeeze_threshold": [0.06] * 20,
            }
        )

        outcome = build_outcome(group, 10, 5, "event", _config(fft_window=16))

        self.assertTrue(outcome["large_move"])
        self.assertAlmostEqual(outcome["max_up"], 0.12)

    def test_fft_features_recovers_synthetic_cycle(self) -> None:
        period = 21
        x = np.arange(260)
        close = pd.Series(100 + 3 * np.sin(2 * np.pi * x / period) + 0.03 * x)

        features = fft_features(close, len(close) - 1, 256, 3)

        self.assertIsNotNone(features["top_period"])
        self.assertLess(abs(float(features["top_period"]) - period), 4.0)


if __name__ == "__main__":
    unittest.main()
