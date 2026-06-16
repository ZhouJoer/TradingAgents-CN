from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List


COMMON_PARAMETER_SCHEMA: List[Dict[str, Any]] = [
    {"key": "top_k", "label": "Top K", "type": "number", "min": 1, "max": 5},
    {
        "key": "rebalance_frequency",
        "label": "调仓频率",
        "type": "select",
        "options": ["weekly", "biweekly", "monthly"],
    },
    {
        "key": "empty_threshold",
        "label": "空仓规则",
        "type": "select",
        "options": ["ret_gt_0", "score_gt_0", "trend_filter"],
    },
    {
        "key": "cash_entry_mode",
        "label": "空仓入场",
        "type": "select",
        "options": ["daily_when_cash", "rebalance_only"],
    },
    {"key": "cash_entry_confirmations", "label": "空仓确认次数", "type": "number", "min": 1, "max": 5},
    {
        "key": "min_days_to_rebalance_for_cash_entry",
        "label": "距调仓日最少交易日",
        "type": "number",
        "min": 0,
        "max": 20,
    },
]


STRATEGY_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "industry_momentum_enhanced": {
        "id": "industry_momentum_enhanced",
        "name": "行业 ETF 增强动量轮动",
        "family": "momentum",
        "status": "candidate",
        "description": "用多周期相对强弱给 ETF 排名，并结合绝对动量、趋势过滤和波动惩罚控制追高风险。",
        "signals": ["多周期动量", "绝对动量", "趋势过滤", "波动惩罚"],
        "default_frequency": "monthly",
        "default_params": {
            "rebalance_frequency": "monthly",
            "top_k": 1,
            "momentum_windows": [40, 120, 250],
            "momentum_weights": [0.3, 0.5, 0.2],
            "absolute_window": 60,
            "trend_fast_ma": 20,
            "trend_ma": 120,
            "vol_window": 60,
            "vol_penalty": 0.03,
            "empty_threshold": "trend_filter",
            "cash_entry_mode": "daily_when_cash",
        },
        "parameter_schema": COMMON_PARAMETER_SCHEMA
        + [
            {"key": "momentum_windows", "label": "动量窗口", "type": "list"},
            {"key": "trend_fast_ma", "label": "快趋势均线", "type": "number"},
            {"key": "trend_ma", "label": "趋势均线", "type": "number"},
            {"key": "vol_penalty", "label": "波动惩罚", "type": "number"},
        ],
    },
    "vol_adjusted_momentum": {
        "id": "vol_adjusted_momentum",
        "name": "波动调整动量轮动",
        "family": "momentum",
        "status": "candidate",
        "description": "用动量/波动率排序，并按低波动资产给更高权重，适合减少单一高波动标的冲击。",
        "signals": ["风险调整动量", "逆波动权重", "绝对动量"],
        "default_frequency": "monthly",
        "default_params": {
            "rebalance_frequency": "monthly",
            "top_k": 3,
            "fast_window": 60,
            "slow_window": 120,
            "fast_vol_window": 60,
            "slow_vol_window": 120,
            "trend_ma": 60,
            "empty_threshold": "ret_gt_0",
            "max_weight": 0.45,
            "cash_entry_mode": "daily_when_cash",
        },
        "parameter_schema": COMMON_PARAMETER_SCHEMA
        + [
            {"key": "fast_window", "label": "快动量窗口", "type": "number"},
            {"key": "slow_window", "label": "慢动量窗口", "type": "number"},
            {"key": "fast_vol_window", "label": "波动窗口", "type": "number"},
        ],
    },
    "dual_momentum_core": {
        "id": "dual_momentum_core",
        "name": "双动量核心轮动",
        "family": "momentum",
        "status": "baseline",
        "description": "先用绝对动量剔除弱势 ETF，再在合格标的中按相对动量排序。",
        "signals": ["绝对动量", "相对动量", "趋势过滤"],
        "default_frequency": "monthly",
        "default_params": {
            "rebalance_frequency": "monthly",
            "top_k": 2,
            "momentum_window": 120,
            "trend_ma": 60,
            "empty_threshold": "trend_filter",
            "cash_entry_mode": "daily_when_cash",
        },
        "parameter_schema": COMMON_PARAMETER_SCHEMA
        + [
            {"key": "momentum_window", "label": "动量窗口", "type": "number"},
            {"key": "trend_ma", "label": "趋势均线", "type": "number"},
        ],
    },
    "trend_following_equal_weight": {
        "id": "trend_following_equal_weight",
        "name": "趋势跟随等权",
        "family": "trend",
        "status": "baseline",
        "description": "持有价格站上慢均线且快均线确认的 ETF，合格标的等权配置。",
        "signals": ["快均线", "慢均线", "正动量"],
        "default_frequency": "monthly",
        "default_params": {
            "rebalance_frequency": "monthly",
            "top_k": 5,
            "fast_ma": 20,
            "slow_ma": 60,
            "score_window": 60,
            "empty_threshold": "trend_filter",
            "cash_entry_mode": "daily_when_cash",
        },
        "parameter_schema": COMMON_PARAMETER_SCHEMA
        + [
            {"key": "fast_ma", "label": "快均线", "type": "number"},
            {"key": "slow_ma", "label": "慢均线", "type": "number"},
            {"key": "score_window", "label": "评分窗口", "type": "number"},
        ],
    },
    "adaptive_regime_rotation": {
        "id": "adaptive_regime_rotation",
        "name": "市场状态自适应轮动",
        "family": "adaptive",
        "status": "candidate",
        "description": "先用基准趋势识别上涨、震荡、下跌状态，再分别切换强动量、低波正动量和防守资产逻辑；默认按月轮仓，周/双周容易受噪音和成本影响。",
        "signals": ["市场状态", "强动量", "低波动", "防守资产", "趋势确认"],
        "default_frequency": "monthly",
        "default_params": {
            "rebalance_frequency": "monthly",
            "top_k": 1,
            "top_k_uptrend": 1,
            "top_k_range": 1,
            "top_k_downtrend": 1,
            "momentum_windows": [40, 120, 250],
            "momentum_weights": [0.3, 0.5, 0.2],
            "absolute_window": 60,
            "trend_fast_ma": 20,
            "trend_ma": 120,
            "vol_window": 60,
            "vol_penalty": 0.03,
            "regime_fast_ma": 20,
            "regime_slow_ma": 120,
            "regime_momentum_window": 40,
            "regime_up_threshold": 0.02,
            "regime_down_threshold": -0.03,
            "range_window": 40,
            "range_ma": 60,
            "range_vol_window": 20,
            "range_vol_penalty": 0.02,
            "defensive_codes": ["518880", "512890", "515100", "515300", "563020"],
            "defensive_window": 60,
            "defensive_ma": 120,
            "cash_entry_mode": "daily_when_cash",
        },
        "parameter_schema": COMMON_PARAMETER_SCHEMA
        + [
            {"key": "regime_fast_ma", "label": "状态快均线", "type": "number"},
            {"key": "regime_slow_ma", "label": "状态慢均线", "type": "number"},
            {"key": "regime_momentum_window", "label": "状态动量窗口", "type": "number"},
            {"key": "top_k_uptrend", "label": "上涨持仓数", "type": "number"},
            {"key": "top_k_range", "label": "震荡持仓数", "type": "number"},
            {"key": "top_k_downtrend", "label": "下跌防守持仓数", "type": "number"},
            {"key": "defensive_codes", "label": "防守资产池", "type": "list"},
        ],
    },
    "biweekly_adaptive_stable_rotation": {
        "id": "biweekly_adaptive_stable_rotation",
        "name": "双周稳健自适应轮动",
        "family": "adaptive",
        "status": "candidate",
        "description": "按双周约 10 个交易日的节奏设计 MA 与动量窗口，用 MA10/60/120 和 20/60/120 日动量识别强弱，并用最短持有期、排名缓冲和小换仓过滤降低双周相位风险。",
        "signals": ["双周节奏", "MA10/60/120", "状态确认", "排名缓冲", "最短持有"],
        "default_frequency": "biweekly",
        "default_params": {
            "rebalance_frequency": "biweekly",
            "top_k": 2,
            "top_k_uptrend": 2,
            "top_k_range": 2,
            "top_k_downtrend": 1,
            "momentum_windows": [20, 60, 120],
            "momentum_weights": [0.25, 0.45, 0.3],
            "absolute_window": 20,
            "trend_fast_ma": 10,
            "trend_ma": 60,
            "vol_window": 20,
            "vol_penalty": 0.04,
            "regime_fast_ma": 10,
            "regime_slow_ma": 120,
            "regime_momentum_window": 60,
            "regime_up_threshold": 0.015,
            "regime_down_threshold": -0.025,
            "range_window": 20,
            "range_ma": 60,
            "range_vol_window": 20,
            "range_vol_penalty": 0.02,
            "defensive_codes": ["518880", "512890", "515100", "515300", "563020"],
            "defensive_window": 60,
            "defensive_ma": 120,
            "min_holding_days": 20,
            "rank_switch_buffer": 2,
            "rebalance_turnover_threshold": 0.18,
            "cash_entry_mode": "daily_when_cash",
            "cash_entry_confirmations": 2,
            "min_days_to_rebalance_for_cash_entry": 2,
        },
        "parameter_schema": COMMON_PARAMETER_SCHEMA
        + [
            {"key": "momentum_windows", "label": "双周倍数动量窗口", "type": "list"},
            {"key": "trend_fast_ma", "label": "快趋势均线", "type": "number"},
            {"key": "trend_ma", "label": "中期趋势均线", "type": "number"},
            {"key": "regime_fast_ma", "label": "状态快均线", "type": "number"},
            {"key": "regime_slow_ma", "label": "状态慢均线", "type": "number"},
            {"key": "regime_momentum_window", "label": "状态动量窗口", "type": "number"},
            {"key": "top_k_uptrend", "label": "上涨持仓数", "type": "number"},
            {"key": "top_k_range", "label": "震荡持仓数", "type": "number"},
            {"key": "top_k_downtrend", "label": "下跌防守持仓数", "type": "number"},
            {"key": "min_holding_days", "label": "最短持有交易日", "type": "number"},
            {"key": "rank_switch_buffer", "label": "排名缓冲", "type": "number"},
            {"key": "rebalance_turnover_threshold", "label": "小换仓过滤", "type": "number"},
        ],
    },
    "donchian_breakout_rotation": {
        "id": "donchian_breakout_rotation",
        "name": "唐奇安突破轮动",
        "family": "breakout",
        "status": "candidate",
        "description": "选择接近近期通道高点突破的 ETF，并用波动惩罚降低追高风险。",
        "signals": ["通道高点", "短期动量", "波动惩罚"],
        "default_frequency": "weekly",
        "default_params": {
            "rebalance_frequency": "weekly",
            "top_k": 2,
            "lookback": 60,
            "momentum_window": 20,
            "vol_window": 20,
            "breakout_buffer": 0.98,
            "cash_entry_mode": "daily_when_cash",
        },
        "parameter_schema": COMMON_PARAMETER_SCHEMA
        + [
            {"key": "lookback", "label": "突破回看", "type": "number"},
            {"key": "breakout_buffer", "label": "突破缓冲", "type": "number"},
        ],
    },
    "rsrs_timing_rotation": {
        "id": "rsrs_timing_rotation",
        "name": "RSRS 择时轮动",
        "family": "timing",
        "status": "experimental",
        "description": "用高低价回归斜率的标准分做择时门槛，再按动量排序。",
        "signals": ["RSRS标准分", "正动量"],
        "default_frequency": "weekly",
        "default_params": {
            "rebalance_frequency": "weekly",
            "top_k": 2,
            "rsrs_window": 18,
            "z_window": 120,
            "z_threshold": 0.7,
            "momentum_window": 60,
            "cash_entry_mode": "daily_when_cash",
        },
        "parameter_schema": COMMON_PARAMETER_SCHEMA
        + [
            {"key": "rsrs_window", "label": "RSRS窗口", "type": "number"},
            {"key": "z_threshold", "label": "标准分阈值", "type": "number"},
        ],
    },
    "chan_fractal_rotation": {
        "id": "chan_fractal_rotation",
        "name": "缠论分型轮动（简化）",
        "family": "chan",
        "status": "experimental",
        "description": "简化识别近期底分型，并用均线确认和回撤控制筛选 ETF。",
        "signals": ["底分型", "均线确认", "回撤控制"],
        "default_frequency": "weekly",
        "default_params": {
            "rebalance_frequency": "weekly",
            "top_k": 2,
            "lookback": 80,
            "ma": 20,
            "cash_entry_mode": "daily_when_cash",
        },
        "parameter_schema": COMMON_PARAMETER_SCHEMA
        + [
            {"key": "lookback", "label": "分型回看", "type": "number"},
            {"key": "ma", "label": "确认均线", "type": "number"},
        ],
    },
    "chan_center_breakout": {
        "id": "chan_center_breakout",
        "name": "缠论中枢突破（简化）",
        "family": "chan",
        "status": "experimental",
        "description": "用多段高低点重叠区近似中枢，再识别向上突破和低点抬高。",
        "signals": ["中枢重叠", "向上突破", "低点抬高"],
        "default_frequency": "weekly",
        "default_params": {
            "rebalance_frequency": "weekly",
            "top_k": 2,
            "segment": 20,
            "cash_entry_mode": "daily_when_cash",
        },
        "parameter_schema": COMMON_PARAMETER_SCHEMA
        + [{"key": "segment", "label": "分段长度", "type": "number"}],
    },
}


STRATEGY_DEFINITIONS: List[Dict[str, Any]] = list(STRATEGY_TEMPLATES.values())


def strategy_default_params(strategy_id: str, overrides: Dict[str, Any] | None = None) -> Dict[str, Any]:
    defaults = deepcopy(STRATEGY_TEMPLATES.get(strategy_id, {}).get("default_params", {}))
    defaults.update(overrides or {})
    return defaults


def strategy_default_frequency(strategy_id: str) -> str:
    definition = STRATEGY_TEMPLATES.get(strategy_id)
    return str(definition.get("default_frequency", "weekly")) if definition else "weekly"
