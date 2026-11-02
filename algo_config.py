# -*- coding: utf-8 -*-
# Azazel Algo Bridge: единый конфиг -> профиль в Airtable.
# Источник правды по рискам - azazel_config.json.
# Airtable хранит профиль юзера; здесь мы показываем расхождения, а не молча перетираем.
import os

try:
    from azazel_config_loader import load_config, apply_to_framework
    import scalping_framework_v2 as FW
    _ADIR = os.path.dirname(os.path.abspath(__file__))
    ALGO_CFG, ALGO_SRC = load_config(path=os.path.join(_ADIR, 'azazel_config.json'))
    ALGO_APPLY = apply_to_framework(vars(FW), ALGO_CFG, ALGO_SRC)
    ALGO_RISK = getattr(FW, 'RISK_MANAGEMENT', {})
except Exception as _e:
    ALGO_CFG, ALGO_SRC = {}, 'none'
    ALGO_APPLY = {'applied': False, 'error': str(_e), 'count': 0}
    ALGO_RISK = {}

# config path -> поле профиля в Airtable
ALGO_FIELD_MAP = {
    'algo.stops.alts_pct': 'Стоп альты %',
    'algo.stops.btc_eth_pct': 'Стоп BTC/ETH %',
    'algo.stops.atr_mult': 'ATR-множитель',
    'algo.leverage.alts_max': 'Плечо альты',
    'algo.leverage.btc_eth_max': 'Плечо BTC/ETH',
    'algo.rr_min': 'Мин R:R',
    'algo.btc_filter_pct': 'BTC-фильтр %',
    'algo.funding_long_block_pct': 'Блок лонга фандинг %',
    'algo.daily_loss_limit_usd': 'Дневной лимит убытка $',
    'algo.max_stops_per_day': 'Стопов в день',
    'algo.correlation_cap': 'Correlation cap',
    'algo.max_trades_per_day': 'Сделок в день',
}


def cfg_get(path, default=None):
    cur = ALGO_CFG
    for k in path.split('.'):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def algo_defaults():
    d = {}
    for cpath, field in ALGO_FIELD_MAP.items():
        v = cfg_get(cpath)
        if v is not None:
            d[field] = v
    tf = cfg_get('algo.timeframes')
    if tf:
        d['Таймфреймы'] = ','.join(tf) if isinstance(tf, list) else str(tf)
    return d


def algo_drift(profile):
    out = []
    for cpath, field in ALGO_FIELD_MAP.items():
        cv = cfg_get(cpath)
        pv = profile.get(field)
        if cv is None or pv in (None, ''):
            continue
        try:
            if abs(float(cv) - float(pv)) > 1e-9:
                out.append((field, cv, pv))
        except (TypeError, ValueError):
            if str(cv) != str(pv):
                out.append((field, cv, pv))
    return out


def algo_drift_text(profile):
    d = algo_drift(profile)
    if not d:
        return chr(10) + '<i>Профиль совпадает с конфигом - расхождений нет.</i>'
    rows = chr(10).join('  - ' + str(f) + ': конфиг ' + str(c) + ' -> профиль ' + str(pv) for f, c, pv in d)
    return chr(10) * 2 + '<b>Расхождения конфиг/профиль:</b>' + chr(10) + rows


def algo_status_line():
    st = 'применён' if ALGO_APPLY.get('applied') else 'НЕ применён'
    return ('<i>Единый конфиг: ' + str(ALGO_SRC) + ' - ' + st
            + ' - риск-параметров: ' + str(len(ALGO_FIELD_MAP)) + '</i>')
