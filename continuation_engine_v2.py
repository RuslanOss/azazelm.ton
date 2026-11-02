# -*- coding: utf-8 -*-
# ============================================================
# CONTINUATION ENGINE v2.0 - совместимая обёртка
# Azazel Trader | 2026-11-02
# ============================================================
"""
Совместимость: ранние версии импортировали этот модуль.
Каноническая реализация теперь в continuation_engine.py (v3.0).

Этот файл - тонкая обёртка: реэкспортирует всё из канонического модуля
и добавляет алиасы под старые имена. Источник истины - один.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from continuation_engine import *          # noqa: F401,F403
    from continuation_engine import (           # noqa: F401
        __version__ as _canonical_version,
        load_config, norm, closes, volumes, avg,
        ema, rsi, macd, atr, atr_pct, supertrend, cvd,
        swing_lows, swing_highs,
        continuation_signals, reversal_signals,
        calculate_continuation_probability, calculate_reversal_probability,
        detect_manipulation,
        is_btc_eth, stop_for, leverage_for, target_from_stop,
        btc_filter_check, funding_block_check, correlation_cap_check,
        daily_limit_check, stop_count_check,
        decide_position, find_entries, engine_cycle,
        scan_top5_for_entry, open_position, partial_close, freeze_trading,
        is_frozen, trailing_stop_after_extension,
        CONTINUATION_SIGNALS, REVERSAL_SIGNALS, MANIPULATION_DETECTOR,
        CONTINUATION_RULES, ASSET_ROTATION, DEFAULT_CFG,
    )
except ImportError:
    # Канонический модуль недоступен - не падаем на импорте
    _canonical_version = "unavailable"

__version__ = "2.0"

# Исторические имена из v1-спецификации
TRADING_LOOP = """Цикл выполняет агент (не серверный код):
рынок -> мониторинг >5% -> позиции/баланс Walt -> точки входа ->
пост-анализ каждого закрытия -> запись в working memory.
Полное исполнение - в continuation_engine.py: engine_cycle(), find_entries(),
decide_position()."""

# Алиасы под возможные старые вызовы
scan_top5 = scan_top5_for_entry
open_trade = open_position
