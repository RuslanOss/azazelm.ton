# ============================================================
# CONTINUATION ENGINE v1.0 — Trend Following + Asset Rotation
# Generated: 2026-10-21 | Azazel👺
# ============================================================

"""
ДВИЖОК ПРОДЛЕНИЯ СДЕЛОК С АВТО-РОТАЦИЕЙ АКТИВОВ

Принцип работы:
1. Сделка достигла тейка → не закрываем, анализируем продолжение
2. Если вероятность продолжения > 40% → трейлим стоп, держим позицию
3. При подтверждении разворота → закрываем, переходим на следующий актив
4. Цикл повторяется пока есть подходящие активы из топ-5

Источники:
- Hidden divergence (continuation): altfins.com, coinbeacon.io
- Pyramiding: quantstrategy.io, win rate 40-45% trend-following
- Manipulation detection: mmflow.ai (anomaly scoring), cryptotradesignals.ai (Trap Score)
- Asset rotation: adapted from V4 multi-market scanning
"""

# ============================================================
# ИНДИКАТОРЫ ПРОДОЛЖЕНИЯ ТРЕНДА
# ============================================================
CONTINUATION_SIGNALS = {
    "hidden_divergence": {
        "name": "Скрытая дивергенция",
        "weight": 0.35,
        "description": "Цена делает higher low, а RSI — lower low (бычья). Или цена делает lower high, а RSI — higher high (медвежья).",
        "bullish": "price_higher_low AND rsi_lower_low",
        "bearish": "price_lower_high AND rsi_higher_high",
        "source": "altfins.com, coinbeacon.io",
    },
    "momentum_confirmation": {
        "name": "Подтверждение моментума",
        "weight": 0.25,
        "description": "MACD не пересекал сигнальную линию против тренда, гистограмма растёт в сторону тренда.",
        "bullish": "MACD_line > signal_line AND MACD_histogram > prev_histogram",
        "bearish": "MACD_line < signal_line AND MACD_histogram < prev_histogram",
    },
    "volume_trend": {
        "name": "Объём по тренду",
        "weight": 0.20,
        "description": "Объём на свечах продолжения выше, чем на откатных свечах (соотношение > 1.3x).",
        "bullish": "avg_volume_up_candles > avg_volume_down_candles * 1.3",
        "bearish": "avg_volume_down_candles > avg_volume_up_candles * 1.3",
    },
    "ema_structure": {
        "name": "EMA-структура",
        "weight": 0.20,
        "description": "EMA5 > EMA13 > EMA50 (бычий веер) или наоборот. Без пересечений против тренда.",
        "bullish": "EMA5 > EMA13 > EMA50 AND no_cross_against_trend(20 bars)",
        "bearish": "EMA5 < EMA13 < EMA50 AND no_cross_against_trend(20 bars)",
    },
}

# ============================================================
# ИНДИКАТОРЫ РАЗВОРОТА (СТОП-СИГНАЛЫ)
# ============================================================
REVERSAL_SIGNALS = {
    "regular_divergence": {
        "name": "Обычная дивергенция",
        "weight": 0.30,
        "description": "Цена делает higher high, а RSI — lower high (медвежья). Или цена делает lower low, а RSI — higher low (бычья).",
        "source": "coinbeacon.io",
    },
    "volume_climax": {
        "name": "Кульминация объёма",
        "weight": 0.25,
        "description": "Объём > 3x среднего на свече ПРОТИВ тренда — крупный игрок выходит.",
    },
    "ema_cross": {
        "name": "EMA-кросс против тренда",
        "weight": 0.20,
        "description": "EMA5 пересекла EMA13 против направления позиции.",
    },
    "support_resistance_rejection": {
        "name": "Отказ от уровня",
        "weight": 0.15,
        "description": "Цена коснулась ключевого уровня (HVN, round number) и развернулась с объёмом.",
    },
    "funding_flip": {
        "name": "Переворот фандинга",
        "weight": 0.10,
        "description": "Фандинг сменил знак против позиции — толпа переобувается.",
    },
}

# ============================================================
# ДЕТЕКТОР МАНИПУЛЯЦИЙ
# ============================================================
MANIPULATION_DETECTOR = {
    "spoofing": {
        "name": "Спуфинг (ложные стенки)",
        "check": "large_order_appears_and_disappears(within 5 seconds, size > 10x avg)",
        "action": "игнорировать уровень, ждать подтверждения реальным объёмом",
    },
    "wash_trading": {
        "name": "Вош-трейдинг",
        "check": "volume_spike_without_price_movement(volume > 3x avg, price_range < 0.1%)",
        "action": "пропустить сигнал, объём ненастоящий",
    },
    "stop_hunting": {
        "name": "Охота за стопами",
        "check": "price_wick_through_level_then_reversal(wick > 0.3%, reversal > 0.5% within 3 bars)",
        "action": "расширить стоп на 0.2% за уровнем, не закрывать на вике",
    },
    "anomaly_score": {
        "name": "Композитная аномалия",
        "threshold": 0.7,
        "components": ["spoofing", "wash_trading", "stop_hunting"],
        "action": "заморозить торговлю на 5 минут, перепроверить все сигналы",
    },
}

# ============================================================
# КАЛЬКУЛЯТОР ВЕРОЯТНОСТИ ПРОДОЛЖЕНИЯ
# ============================================================
def calculate_continuation_probability(signals_active):
    """
    signals_active: dict {signal_name: True/False}
    Возвращает: вероятность продолжения 0.0 – 1.0
    """
    total_weight = 0.0
    active_weight = 0.0
    
    for name, config in CONTINUATION_SIGNALS.items():
        total_weight += config["weight"]
        if signals_active.get(name, False):
            active_weight += config["weight"]
    
    if total_weight == 0:
        return 0.0
    
    return active_weight / total_weight


def calculate_reversal_probability(signals_active):
    """
    signals_active: dict {signal_name: True/False}
    Возвращает: вероятность разворота 0.0 – 1.0
    """
    total_weight = 0.0
    active_weight = 0.0
    
    for name, config in REVERSAL_SIGNALS.items():
        total_weight += config["weight"]
        if signals_active.get(name, False):
            active_weight += config["weight"]
    
    if total_weight == 0:
        return 0.0
    
    return active_weight / total_weight


# ============================================================
# ЛОГИКА ПРОДЛЕНИЯ ПОЗИЦИИ
# ============================================================
CONTINUATION_RULES = {
    "threshold": 0.40,
    "max_extensions": 5,
    "trailing_after_extension": {
        "extension_1": "0.5% за ценой",
        "extension_2": "0.4% за ценой",
        "extension_3": "0.3% за ценой",
        "extension_4": "0.2% за ценой",
        "extension_5": "0.15% за ценой",
    },
    "pyramiding": {
        "enabled": True,
        "max_additions": 3,
        "addition_size_pct": 50,
        "condition": "continuation_probability > 0.60 AND price_pulled_back_to_ema13",
    },
    "partial_take": {
        "enabled": True,
        "at_extension": 3,
        "size_pct": 50,
    },
}

# ============================================================
# ЛОГИКА РОТАЦИИ АКТИВОВ
# ============================================================
ASSET_ROTATION = {
    "scan_interval_minutes": 5,
    "min_volume_24h": 10_000_000,
    "max_positions": 3,
    "priority": [
        "continuation_probability",
        "volume_24h",
        "atr_pct",
        "funding_rate",
    ],
    "cooldown_after_rotation_minutes": 2,
    "blacklist": {
        "after_two_losses": True,
        "duration_minutes": 60,
    },
}

# ============================================================
# ЦИКЛ ТОРГОВЛИ (ПСЕВДОКОД)
# ============================================================
TRADING_LOOP = """
while account.free_margin > min_trade_size:
    
    # Шаг 1: Проверить открытые позиции на продолжение
    for position in open_positions:
        if position.pnl_pct > take_profit_pct:
            cont_prob = calculate_continuation_probability(get_signals(position))
            rev_prob = calculate_reversal_probability(get_signals(position))
            
            if cont_prob > 0.40 and rev_prob < 0.30:
                # ПРОДЛЕВАЕМ
                extension_count += 1
                new_stop = calculate_trailing_stop(position, extension_count)
                update_stop_loss(position, new_stop)
                
                if cont_prob > 0.60 and pyramiding_allowed:
                    add_to_position(position, addition_size)
                    
            elif rev_prob > 0.50:
                # РАЗВОРОТ — ЗАКРЫВАЕМ
                close_position(position)
                log_trade(position)
                
                # Ротация: ищем следующий актив
                next_asset = scan_top5_for_best_signal()
                if next_asset:
                    open_position(next_asset)
                    
            else:
                # НЕОПРЕДЕЛЁННОСТЬ — фиксируем 50%
                partial_close(position, 0.50)
    
    # Шаг 2: Если есть свободное место — ищем новые входы
    if len(open_positions) < max_positions:
        new_signal = scan_top5_for_entry()
        if new_signal and new_signal.continuation_probability > 0.40:
            open_position(new_signal)
    
    # Шаг 3: Проверка на манипуляции
    if detect_manipulation():
        freeze_trading(5 минут)
        continue
    
    sleep(scan_interval)
"""

# ============================================================
# ПРИМЕНЕНИЕ К ТЕКУЩИМ ПОЗИЦИЯМ (21.10.2026)
# ============================================================
CURRENT_POSITIONS_ANALYSIS = {
    "SOL": {
        "position": "LONG 5x, entry $107.07, tp $108.00",
        "continuation_signals": {
            "hidden_divergence": False,
            "momentum_confirmation": True,
            "volume_trend": True,
            "ema_structure": True,
        },
        "continuation_probability": 0.65,
        "reversal_signals": {
            "regular_divergence": False,
            "volume_climax": False,
            "ema_cross": False,
            "support_resistance_rejection": False,
            "funding_flip": False,
        },
        "reversal_probability": 0.0,
        "verdict": "ПРОДЛЕВАТЬ — вероятность 65%, разворотных сигналов нет",
        "action": "При достижении $108 не закрывать, трейлить стоп на $107.50",
    },
    "GRAM": {
        "position": "SHORT 5x, entry $1.364, tp $1.345",
        "continuation_signals": {
            "hidden_divergence": False,
            "momentum_confirmation": True,
            "volume_trend": False,
            "ema_structure": True,
        },
        "continuation_probability": 0.45,
        "reversal_signals": {
            "regular_divergence": False,
            "volume_climax": False,
            "ema_cross": False,
            "support_resistance_rejection": True,
            "funding_flip": False,
        },
        "reversal_probability": 0.15,
        "verdict": "ПРОДЛЕВАТЬ осторожно — вероятность 45%, есть отскок от поддержки",
        "action": "При достижении $1.345 не закрывать, трейлить стоп на $1.355",
    },
    "MU": {
        "position": "LONG 5x, entry $916, tp $1000",
        "continuation_signals": {
            "hidden_divergence": False,
            "momentum_confirmation": False,
            "volume_trend": False,
            "ema_structure": False,
        },
        "continuation_probability": 0.0,
        "reversal_signals": {
            "regular_divergence": False,
            "volume_climax": False,
            "ema_cross": True,
            "support_resistance_rejection": False,
            "funding_flip": False,
        },
        "reversal_probability": 0.20,
        "verdict": "ДЕРЖАТЬ до стопа — вероятность продолжения 0%, но разворот слабый",
        "action": "Стоп $870 держит. При восстановлении выше $916 — переоценить.",
    },
}
