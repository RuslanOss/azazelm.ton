# ============================================================
# MULTI-TIMEFRAME SCALPING FRAMEWORK v2.0
# Generated: 2026-10-21 | Azazel👺
# ============================================================

"""
СКАЛЬПИНГ-СТРАТЕГИИ ДЛЯ WALT PERPS (30s / 1m / 5m / 1h / 1d / 1w)

Топ-5 рынков по объёму (Walt, 21.10.2026):
  1. BTC   — $871M/сут, спред <0.01%, макс плечо 50x
  2. ETH   — $356M/сут, спред <0.01%, макс плечо 50x
  3. SOL   — $69.5M/сут, спред ~0.01%, макс плечо 25x
  4. US100 — $49.2M/сут, спред ~0.02%, макс плечо 30x
  5. ZEC   — $47.0M/сут, спред ~0.03%, макс плечо 20x

Источники:
- 30s/1m momentum: manifoldbt.com, win rate 39-55%, ROI +11.2% (6431 trades)
- Order flow scalping: xerogravity.com, win rate 64-68%
- ATR + Bollinger: cryptoprofitcalc.com, win rate 60-65%
- ROI by account size: secret-terminal.com (2026)
"""

# ============================================================
# ТОП-5 РЫНКОВ ДЛЯ СКАЛЬПИНГА
# ============================================================
TOP5_MARKETS = {
    "BTC": {
        "volume_24h": 871_328_938,
        "spread_pct": 0.01,
        "max_leverage": 50,
        "min_size_usd": 0.00007,
        "atr_14_pct": 2.1,
        "funding_hourly": 0.0,
        "scalp_leverage": 10,
        "best_timeframes": ["30s", "1m", "5m"],
    },
    "ETH": {
        "volume_24h": 355_747_373,
        "spread_pct": 0.01,
        "max_leverage": 50,
        "min_size_usd": 0.002,
        "atr_14_pct": 2.8,
        "funding_hourly": 0.0096,
        "scalp_leverage": 10,
        "best_timeframes": ["30s", "1m", "5m"],
    },
    "SOL": {
        "volume_24h": 69_513_022,
        "spread_pct": 0.02,
        "max_leverage": 25,
        "min_size_usd": 0.05,
        "atr_14_pct": 3.5,
        "funding_hourly": 0.0096,
        "scalp_leverage": 5,
        "best_timeframes": ["1m", "5m"],
    },
    "US100": {
        "volume_24h": 49_153_770,
        "spread_pct": 0.02,
        "max_leverage": 30,
        "min_size_usd": 0.01,
        "atr_14_pct": 1.5,
        "funding_hourly": 0.0032,
        "scalp_leverage": 10,
        "best_timeframes": ["1m", "5m", "15m"],
    },
    "ZEC": {
        "volume_24h": 47_026_599,
        "spread_pct": 0.03,
        "max_leverage": 20,
        "min_size_usd": 0.005,
        "atr_14_pct": 4.8,
        "funding_hourly": 0.0096,
        "scalp_leverage": 5,
        "best_timeframes": ["1m", "5m"],
    },
}

# ============================================================
# ТРИ ТИРА ДЕПОЗИТОВ
# ============================================================
DEPOSIT_TIERS = {
    "micro": {
        "name": "Микро",
        "range": "$50 – $200",
        "max_trades_per_day": 10,
        "max_concurrent": 1,
        "margin_per_trade_pct": 20,
        "daily_loss_limit_pct": 10,
        "weekly_loss_limit_pct": 20,
        "scalp_only": True,
        "expected_monthly_roi": "3% – 8%",
        "expected_monthly_usd": "$1.50 – $16",
        "recommended_markets": ["BTC", "ETH"],
        "strategy": "RSI(7) Divergence (1m) — низкий риск, высокий винрейт",
    },
    "medium": {
        "name": "Средний",
        "range": "$200 – $1,000",
        "max_trades_per_day": 20,
        "max_concurrent": 2,
        "margin_per_trade_pct": 15,
        "daily_loss_limit_pct": 8,
        "weekly_loss_limit_pct": 15,
        "scalp_only": False,
        "expected_monthly_roi": "8% – 15%",
        "expected_monthly_usd": "$16 – $150",
        "recommended_markets": ["BTC", "ETH", "SOL"],
        "strategy": "CVD + Volume Profile (1m) + ATR Squeeze (5m)",
    },
    "large": {
        "name": "Крупный",
        "range": "$1,000+",
        "max_trades_per_day": 30,
        "max_concurrent": 3,
        "margin_per_trade_pct": 10,
        "daily_loss_limit_pct": 5,
        "weekly_loss_limit_pct": 10,
        "scalp_only": False,
        "expected_monthly_roi": "10% – 20%",
        "expected_monthly_usd": "$100 – $2,000+",
        "recommended_markets": ["BTC", "ETH", "SOL", "US100", "ZEC"],
        "strategy": "Все 3 стратегии параллельно + свинг-позиции",
    },
}

# ============================================================
# СТРАТЕГИЯ 1: MOMENTUM SCALPING (30s – 1m)
# ============================================================
STRATEGY_MOMENTUM = {
    "name": "Momentum Scalping",
    "timeframe": "30s – 1m",
    "source": "manifoldbt.com, 6431 trades, ROI +11.2%",
    "indicators": {
        "ema_fast": 5,
        "ema_slow": 13,
        "volume_ma": 20,
    },
    "long": {
        "condition": "EMA5 > EMA13 AND price > EMA5 AND volume > volume_ma * 1.5",
        "entry": "market при подтверждении 2 свечей подряд",
        "stop_loss_pct": -0.10,
        "take_profit_pct": 0.20,
        "max_hold_seconds": 120,
        "trailing": "0.08% за входом после +0.10%",
    },
    "short": {
        "condition": "EMA5 < EMA13 AND price < EMA5 AND volume > volume_ma * 1.5",
        "entry": "market при подтверждении 2 свечей подряд",
        "stop_loss_pct": 0.10,
        "take_profit_pct": -0.20,
        "max_hold_seconds": 120,
        "trailing": "0.08% за входом после -0.10%",
    },
    "filters": {
        "min_volume_24h": 50_000_000,
        "max_spread_pct": 0.03,
        "avoid_news": True,
        "avoid_funding": True,
    },
    "win_rate": 0.55,
    "avg_rr": 1.8,
    "best_markets": ["BTC", "ETH"],
}

# ============================================================
# СТРАТЕГИЯ 2: RSI DIVERGENCE (1m)
# ============================================================
STRATEGY_RSI = {
    "name": "RSI(7) Divergence",
    "timeframe": "1m",
    "source": "xerogravity.com, 312 trades, win rate 68%",
    "indicators": {
        "rsi_period": 7,
        "rsi_oversold": 20,
        "rsi_overbought": 80,
        "volume_ma": 10,
    },
    "long": {
        "condition": "RSI(7) < 20 AND volume > volume_ma * 1.3 AND price выше минимума предыдущих 5 баров",
        "entry": "market",
        "stop_loss_pct": -0.15,
        "take_profit_pct": 0.30,
        "max_hold_bars": 5,
    },
    "short": {
        "condition": "RSI(7) > 80 AND volume < volume_ma * 0.7 AND price ниже максимума предыдущих 5 баров",
        "entry": "market",
        "stop_loss_pct": 0.15,
        "take_profit_pct": -0.30,
        "max_hold_bars": 5,
    },
    "filters": {
        "min_volume_24h": 500_000,
        "max_spread_pct": 0.05,
        "best_regime": "боковик, низкая волатильность",
    },
    "win_rate": 0.68,
    "avg_rr": 2.0,
    "best_markets": ["BTC", "ETH", "SOL", "GRAM"],
}

# ============================================================
# СТРАТЕГИЯ 3: CVD + VOLUME PROFILE (1m)
# ============================================================
STRATEGY_CVD = {
    "name": "CVD + Volume Profile",
    "timeframe": "1m",
    "source": "xerogravity.com, win rate 64%, avg profit 0.8%",
    "indicators": {
        "cvd_lookback": 20,
        "volume_profile_period": "session",
        "delta_threshold": 2.0,
    },
    "long": {
        "condition": "price у LVA/поддержки AND CVD_divergence > 3 баров (цена падает, CVD растёт)",
        "entry": "limit на уровне LVA",
        "stop_loss": "за противоположной стороной LVA (мин 0.15%)",
        "take_profit": "ближайший HVN или +0.8%",
        "max_hold_bars": 10,
    },
    "short": {
        "condition": "price у LVA/сопротивления AND CVD_divergence > 3 баров (цена растёт, CVD падает)",
        "entry": "limit на уровне LVA",
        "stop_loss": "за противоположной стороной LVA (мин 0.15%)",
        "take_profit": "ближайший HVN или -0.8%",
        "max_hold_bars": 10,
    },
    "filters": {
        "min_cvd_divergence_bars": 3,
        "min_volume_at_level": 2.0,
    },
    "win_rate": 0.64,
    "avg_rr": 2.5,
    "best_markets": ["BTC", "ETH", "SOL"],
}

# ============================================================
# СТРАТЕГИЯ 4: ATR + BOLLINGER SQUEEZE (5m)
# ============================================================
STRATEGY_BOLLINGER = {
    "name": "ATR + Bollinger Squeeze",
    "timeframe": "5m",
    "source": "cryptoprofitcalc.com, win rate 60-65%",
    "indicators": {
        "bollinger_period": 20,
        "bollinger_std": 2.0,
        "atr_period": 14,
        "squeeze_threshold": 0.3,
    },
    "long": {
        "condition": "полосы сжаты (ширина < ATR*0.3) минимум 5 баров AND цена закрылась выше верхней полосы AND объём > среднего",
        "entry": "market на пробое",
        "stop_loss": "1.5 * ATR(14) под входом",
        "take_profit": "3.0 * ATR(14) над входом",
        "trailing_stop": "1.0 * ATR(14)",
        "max_hold_bars": 20,
    },
    "short": {
        "condition": "полосы сжаты (ширина < ATR*0.3) минимум 5 баров AND цена закрылась ниже нижней полосы AND объём > среднего",
        "entry": "market на пробое",
        "stop_loss": "1.5 * ATR(14) над входом",
        "take_profit": "3.0 * ATR(14) под входом",
        "trailing_stop": "1.0 * ATR(14)",
        "max_hold_bars": 20,
    },
    "filters": {
        "min_squeeze_bars": 5,
        "atr_min_pct": 2.0,
    },
    "win_rate": 0.62,
    "avg_rr": 2.0,
    "best_markets": ["BTC", "ETH", "SOL", "ZEC", "US100"],
}

# ============================================================
# СВИНГ-СТРАТЕГИЯ (1h – 1d)
# ============================================================
STRATEGY_SWING_DAILY = {
    "name": "Swing Daily (V4 Rules)",
    "timeframe": "1h – 1d",
    "source": "Алгоритм v4, адаптировано",
    "indicators": {
        "supertrend_period": 10,
        "supertrend_multiplier": 3.0,
        "oi_change_threshold": 5.0,
        "funding_threshold": 0.008,
    },
    "long": {
        "condition": "SuperTrend бычий на 1h AND OI +5% AND funding < 0.008% AND BTC не в 2% от сопротивления",
        "entry": "limit у поддержки 1h",
        "stop_loss_pct": -3.0,
        "take_profit_pct": 9.0,
        "max_hold_hours": 72,
    },
    "short": {
        "condition": "SuperTrend медвежий на 1h AND OI +5% AND funding > 0.008% AND BTC_distance_to_resistance > 2%",
        "entry": "limit у сопротивления 1h",
        "stop_loss_pct": 3.0,
        "take_profit_pct": -9.0,
        "max_hold_hours": 72,
    },
    "win_rate": 0.55,
    "avg_rr": 3.0,
    "best_markets": ["BTC", "ETH", "SOL", "ZEC", "NEAR", "XMR"],
}

# ============================================================
# НЕДЕЛЬНАЯ СТРАТЕГИЯ (4h – 1w)
# ============================================================
STRATEGY_SWING_WEEKLY = {
    "name": "Swing Weekly (Macro)",
    "timeframe": "4h – 1w",
    "source": "Алгоритм v4, макро-адаптация",
    "indicators": {
        "ema_50": 50,
        "ema_200": 200,
        "btc_dominance_threshold": 59.0,
        "stablecoin_ratio_threshold": 2.5,
    },
    "long": {
        "condition": "EMA50 > EMA200 на 4h AND BTC.D < 59% AND stablecoin_ratio > 2.5 AND цена у поддержки 4h",
        "entry": "limit у поддержки 4h",
        "stop_loss_pct": -5.0,
        "take_profit_pct": 15.0,
        "max_hold_days": 14,
    },
    "short": {
        "condition": "EMA50 < EMA200 на 4h AND BTC.D > 59% AND цена у сопротивления 4h",
        "entry": "limit у сопротивления 4h",
        "stop_loss_pct": 5.0,
        "take_profit_pct": -15.0,
        "max_hold_days": 14,
    },
    "win_rate": 0.50,
    "avg_rr": 3.0,
    "best_markets": ["BTC", "ETH", "SOL"],
}

# ============================================================
# УПРАВЛЕНИЕ РИСКАМИ (V4 + СКАЛЬПИНГ)
# ============================================================
RISK_MANAGEMENT = {
    "global": {
        "max_total_margin_pct": 80,
        "max_correlated_exposure_pct": 50,
        "btc_filter_active": True,
    },
    "scalp": {
        "max_concurrent": 3,
        "max_daily_trades": 30,
        "daily_loss_limit_pct": 10,
        "cooldown_after_loss_min": 5,
        "cooldown_after_win_min": 2,
        "position_size_after_loss_pct": 25,
        "position_size_after_win_pct": 33,
    },
    "daily_swing": {
        "max_concurrent": 2,
        "max_weekly_trades": 10,
        "weekly_loss_limit_pct": 15,
    },
    "weekly_swing": {
        "max_concurrent": 1,
        "max_monthly_trades": 8,
        "monthly_loss_limit_pct": 20,
    },
}

# ============================================================
# СЕЛЕКТОР РЕЖИМА ТОРГОВЛИ
# ============================================================
TRADING_MODES = {
    "scalp_only": {
        "name": "Только скальпинг",
        "timeframes": ["30s", "1m", "5m"],
        "strategies": ["Momentum", "RSI", "CVD", "Bollinger"],
        "max_hold": "5 минут",
        "best_for": "Микро и средний депозит",
    },
    "scalp_daily": {
        "name": "Скальпинг + Дневные",
        "timeframes": ["30s", "1m", "5m", "1h", "4h"],
        "strategies": ["Momentum", "RSI", "CVD", "Bollinger", "Swing Daily"],
        "max_hold": "72 часа",
        "best_for": "Средний и крупный депозит",
    },
    "full_spectrum": {
        "name": "Полный спектр",
        "timeframes": ["30s", "1m", "5m", "1h", "4h", "1d", "1w"],
        "strategies": ["Momentum", "RSI", "CVD", "Bollinger", "Swing Daily", "Swing Weekly"],
        "max_hold": "14 дней",
        "best_for": "Крупный депозит",
    },
}

# ============================================================
# ROI КАЛЬКУЛЯТОР
# ============================================================
def calculate_roi(deposit, tier, mode, days=30):
    """Приблизительный ROI для выбранного тира и режима."""
    tier_config = DEPOSIT_TIERS[tier]
    
    if mode == "scalp_only":
        trades_per_day = tier_config["max_trades_per_day"]
        avg_win_rate = 0.62
        margin_per_trade = deposit * (tier_config["margin_per_trade_pct"] / 100)
        avg_profit_per_win = margin_per_trade * 0.003
        avg_loss_per_loss = margin_per_trade * 0.0015
        
        daily_wins = trades_per_day * avg_win_rate
        daily_losses = trades_per_day * (1 - avg_win_rate)
        daily_pnl = (daily_wins * avg_profit_per_win) - (daily_losses * avg_loss_per_loss)
        daily_commission = trades_per_day * margin_per_trade * 0.0018
        daily_net = daily_pnl - daily_commission
        
    elif mode == "scalp_daily":
        daily_net = deposit * 0.005
    else:
        daily_net = deposit * 0.007
    
    monthly_roi_pct = (daily_net * days / deposit) * 100
    monthly_usd = daily_net * days
    
    return {
        "daily_net_usd": round(daily_net, 2),
        "monthly_roi_pct": round(monthly_roi_pct, 1),
        "monthly_usd": round(monthly_usd, 2),
        "tier": tier_config["name"],
        "mode": TRADING_MODES[mode]["name"],
    }

# ============================================================
# ТЕКУЩАЯ СЕССИЯ
# ============================================================
CURRENT_SESSION = {
    "timestamp": "2026-10-21T23:30:00+03:00",
    "btc_price": 84296,
    "btc_resistance": 85204,
    "btc_distance_to_resistance_pct": 1.08,
    "btc_dominance": 59.5,
    "open_positions": [
        {"market": "GRAM", "side": "SHORT", "margin": 32.63, "leverage": 5, "pnl": 0.10},
        {"market": "MU", "side": "LONG", "margin": 29.72, "leverage": 5, "pnl": -2.31},
    ],
    "free_margin": 97.53,
    "total_equity": 159.98,
}
