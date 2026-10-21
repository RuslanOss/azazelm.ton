# Scalping Strategies for GRAM (Walt Perps)
# Generated: 2026-10-21 | Azazel👺

"""
ТРИ СКАЛЬП-СТРАТЕГИИ ДЛЯ GRAM (1-5 мин)

Источники:
- RSI-дивергенция: xerogravity.com, винрейт 68% (312 сделок BTC)
- CVD + Volume Profile: xerogravity.com, винрейт 64% (средний профит 0.8%)
- ATR + Bollinger Squeeze: cryptoprofitcalc.com, винрейт 60-65%

Адаптировано под GRAM: ATR ~$0.059 (4.4%), мин. размер 4 GRAM, комиссия 0.09%/сторона
"""

# ============================================================
# СТРАТЕГИЯ 1: RSI(7)-ДИВЕРГЕНЦИЯ (1 мин)
# ============================================================
STRATEGY_1 = {
    "name": "RSI(7) Divergence",
    "timeframe": "1m",
    "indicators": {
        "rsi_period": 7,
        "rsi_oversold": 20,
        "rsi_overbought": 80,
    },
    "long": {
        "condition": "RSI(7) < 20 AND volume > avg_volume_5m * 1.3",
        "entry": "market",
        "stop_loss_pct": -0.15,
        "take_profit_pct": 0.30,
        "max_hold_bars": 5,
    },
    "short": {
        "condition": "RSI(7) > 80 AND volume < avg_volume_5m * 0.7",
        "entry": "market",
        "stop_loss_pct": 0.15,
        "take_profit_pct": -0.30,
        "max_hold_bars": 5,
    },
    "filters": {
        "min_volume_24h": 500000,
        "avoid_during": "funding_time ± 2min",
        "max_spread_pct": 0.05,
    },
    "win_rate": 0.68,
    "best_in": "боковик, низкая волатильность",
}

# ============================================================
# СТРАТЕГИЯ 2: CVD + Volume Profile (1 мин)
# ============================================================
STRATEGY_2 = {
    "name": "CVD + Volume Profile",
    "timeframe": "1m",
    "indicators": {
        "cvd_lookback": 20,
        "volume_profile_period": "session",
    },
    "long": {
        "condition": "price у LVA/поддержки AND CVD растёт при падающей цене (бычья дивергенция)",
        "entry": "limit на уровне LVA",
        "stop_loss": "за противоположной стороной LVA",
        "take_profit": "ближайший HVN или +0.8%",
        "max_hold_bars": 10,
    },
    "short": {
        "condition": "price у LVA/сопротивления AND CVD падает при растущей цене (медвежья дивергенция)",
        "entry": "limit на уровне LVA",
        "stop_loss": "за противоположной стороной LVA",
        "take_profit": "ближайший HVN или -0.8%",
        "max_hold_bars": 10,
    },
    "filters": {
        "min_cvd_divergence_bars": 3,
        "min_volume_at_level": 2.0,
    },
    "win_rate": 0.64,
    "best_in": "любой рынок с достаточной ликвидностью",
}

# ============================================================
# СТРАТЕГИЯ 3: ATR + Bollinger Squeeze (3-5 мин)
# ============================================================
STRATEGY_3 = {
    "name": "ATR + Bollinger Squeeze",
    "timeframe": "3m-5m",
    "indicators": {
        "bollinger_period": 20,
        "bollinger_std": 2.0,
        "atr_period": 14,
        "squeeze_threshold": 0.3,
    },
    "long": {
        "condition": "полосы сжаты (ширина < ATR*0.3) AND цена закрылась выше верхней полосы AND объём > среднего",
        "entry": "market на пробое",
        "stop_loss": "1.5 * ATR(14) под входом",
        "take_profit": "3.0 * ATR(14) над входом",
        "trailing_stop": "1.0 * ATR(14)",
    },
    "short": {
        "condition": "полосы сжаты (ширина < ATR*0.3) AND цена закрылась ниже нижней полосы AND объём > среднего",
        "entry": "market на пробое",
        "stop_loss": "1.5 * ATR(14) над входом",
        "take_profit": "3.0 * ATR(14) под входом",
        "trailing_stop": "1.0 * ATR(14)",
    },
    "filters": {
        "min_squeeze_bars": 5,
        "atr_min_pct": 2.0,
    },
    "win_rate": 0.62,
    "best_in": "развороты после консолидации, пробои уровней",
}

# ============================================================
# ОБЩИЕ ПРАВИЛА (из Алгоритма v4)
# ============================================================
V4_RULES = {
    "btc_filter": {
        "description": "Шорты альтов запрещены при BTC в 2% от сопротивления",
        "check": "BTC_distance_to_resistance_pct > 2.0",
    },
    "stop_distance": {
        "alts_min_pct": 3.0,
        "btc_eth_min_pct": 1.5,
    },
    "entry_timing": {
        "no_entry_after_btc_reversal_min": 30,
    },
    "risk_per_trade": {
        "max_margin_pct": 33,
    },
    "multi_timeframe": {
        "required": ["15m", "1h", "4h"],
        "rule": "направление на 1h и 4h должно совпадать с направлением сделки",
    },
}

# ============================================================
# УПРАВЛЕНИЕ РИСКАМИ ДЛЯ СКАЛЬПИНГА
# ============================================================
SCALP_RISK = {
    "max_concurrent_trades": 3,
    "max_daily_trades": 15,
    "max_daily_loss_pct": 10,
    "cooldown_after_loss": 5,
    "cooldown_after_win": 2,
    "position_size": {
        "base_pct": 33,
        "after_win": 33,
        "after_loss": 25,
    },
}

# ============================================================
# СИГНАЛЫ ДЛЯ ТЕКУЩЕЙ СЕССИИ (GRAM, 21.10.2026)
# ============================================================
CURRENT_SESSION = {
    "market": "GRAM-USDC",
    "price": 1.36,
    "atr_14": 0.059,
    "atr_pct": 4.4,
    "support": 1.32,
    "resistance": 1.37,
    "funding_rate_hourly": 0.0096,
    "volume_24h": 1017096,
    "bias": "нейтральный с лёгким медвежьим уклоном",
    "signals": [
        {
            "id": 1,
            "strategy": "ATR + Bollinger Squeeze",
            "side": "SHORT",
            "reason": "Цена у сопротивления $1.37, фандинг положительный, ATR достаточный",
            "entry": 1.365,
            "stop": 1.375,
            "take": 1.345,
            "margin": 33,
            "leverage": 5,
            "risk_reward": "1:2",
        }
    ],
}
