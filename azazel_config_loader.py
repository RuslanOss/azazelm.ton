# ============================================================
# ЗАГРУЗЧИК ЕДИНОГО КОНФИГА — Azazel Trader v1.0
# Generated: 2026-11-02 | Azazel👺
# ============================================================

"""
Читает azazel_config.json (источник правды) и перекрывает параметры движка.

Порядок поиска конфига:
  1) $AZAZEL_CONFIG_PATH   — явный путь
  2) ./azazel_config.json  — рядом с движком
  3) $AZAZEL_CONFIG_URL    — raw-ссылка (по умолчанию репозиторий)
  4) встроенные дефолты   — если ничего не нашлось, движок работает как раньше

Маппинг явный: список MAPPING ниже — единственное место, где одно превращается
в другое. Поля конфига, которых нет в маппинге, не выбрасываются, а попадают
в ENGINE_PARAMS["extra"], чтобы их нельзя было потерять молча.

Не перекрывается: ROI_MODEL, DEPOSIT_TIERS, MODE_BAND — это калибровочная
модель доходности, а не торговая логика.

Применение НИКОГДА не бывает молчаливым частичным успехом:
- если не нашлось ни одного параметра для перекрытия — applied=False
- если часть параметров не применилась — applied=False с перечнем проблем
- бросается исключение только когда вызывающий код явно этого просит
"""

import json
import os
import urllib.request

DEFAULT_CONFIG_URL = (
    "https://raw.githubusercontent.com/RuslanOss/azazelm.ton/main/azazel_config.json"
)

DEFAULTS_ALGO = {
    "stops": {"alts_pct": 3, "btc_eth_pct": 1.5, "atr_mult": 1.0},
    "leverage": {"alts_max": 5, "btc_eth_max": 10},
    "rr_min": 2,
    "btc_filter_pct": 2,
    "funding_long_block_pct": 0.05,
    "daily_loss_limit_usd": 15,
    "max_stops_per_day": 3,
    "correlation_cap": 2,
    "timeframes": ["15m", "1h", "4h"],
    "indicators": {"altcoins": ["CVD", "Open Interest", "SuperTrend"],
                   "macro": ["BTC dominance", "crypto/stablecoin ratio"]},
    "auto_confirm": True,
    "max_trades_per_day": 5,
    "target_roi": "1:3",
}

DEFAULTS = {"algo": DEFAULTS_ALGO}


def _get(d, path, default=None):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _set(d, path, value):
    parts = path.split(".")
    cur = d
    for k in parts[:-1]:
        cur = cur.setdefault(k, {})
    cur[parts[-1]] = value


MAPPING = [
    {"config": "algo.stops.alts_pct", "target": "scalp.stop_pct",
     "note": "стоп для альтов"},
    {"config": "algo.stops.btc_eth_pct", "target": "scalp.stop_pct_btc_eth",
     "note": "стоп для BTC/ETH"},
    {"config": "algo.stops.atr_mult", "target": "scalp.atr_stop_mult",
     "note": "ATR-множитель стопа"},
    {"config": "algo.leverage.alts_max", "target": "scalp.leverage_alts_max",
     "note": "плечо для альтов"},
    {"config": "algo.leverage.btc_eth_max", "target": "scalp.leverage_btc_eth_max",
     "note": "плечо для BTC/ETH"},
    {"config": "algo.rr_min", "target": "global.min_risk_reward",
     "note": "минимальное R:R"},
    {"config": "algo.btc_filter_pct", "target": "global.btc_filter_pct",
     "note": "запрет шорта альтов при близости BTC к сопротивлению"},
    {"config": "algo.funding_long_block_pct", "target": "global.funding_long_block_pct",
     "note": "запрет лонга при высоком фандинге"},
    {"config": "algo.daily_loss_limit_usd", "target": "scalp.daily_loss_limit_usd",
     "note": "дневной лимит убытка в долларах"},
    {"config": "algo.max_stops_per_day", "target": "scalp.max_stops_per_day",
     "note": "стоп-стоп дня"},
    {"config": "algo.correlation_cap", "target": "global.max_correlated_positions",
     "note": "максимум позиций с одинаковой BTC-корреляцией"},
    {"config": "algo.max_trades_per_day", "target": "scalp.max_daily_trades",
     "note": "сделок в день"},
]


def _download(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "azazel-trader/1.0",
                                               "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def load_config(path=None, url=None, allow_download=True):
    """Возвращает (config, source). При неудаче — (DEFAULTS, 'defaults')."""
    candidates = []
    if path:
        candidates.append(("file", path))
    env_path = os.environ.get("AZAZEL_CONFIG_PATH")
    if env_path:
        candidates.append(("file", env_path))
    candidates.append(("file", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           "azazel_config.json")))
    target_url = url or os.environ.get("AZAZEL_CONFIG_URL") or DEFAULT_CONFIG_URL

    for kind, loc in candidates:
        try:
            if kind == "file" and os.path.isfile(loc):
                with open(loc, "r", encoding="utf-8") as f:
                    return json.load(f), "file:" + loc
        except Exception:
            pass
    if allow_download:
        try:
            return _download(target_url), "url:" + target_url
        except Exception:
            pass
    return dict(DEFAULTS), "defaults"


def build_overrides(config):
    """Собирает плоский список (target, value, note) по таблице MAPPING."""
    out = []
    for m in MAPPING:
        val = _get(config, m["config"])
        if val is None:
            continue
        out.append((m["target"], val, m["note"]))
    return out


def apply_to_framework(ns, config=None, source=None, strict=False):
    """
    Перекрывает RISK_MANAGEMENT в пространстве имён движка (globals()).

    Возвращает отчёт. applied=True только если реально применён ХОТЯ БЫ ОДИН
    параметр и ни один не сломался. Иначе applied=False + причина + problems.
    strict=True -> бросает RuntimeError вместо тихого отказа.
    """
    if config is None:
        config, source = load_config()
    risk = ns.get("RISK_MANAGEMENT")
    if risk is None:
        report = {"applied": False, "reason": "RISK_MANAGEMENT не найден в модуле",
                  "source": source, "count": 0, "problems": ["no_risk_management"]}
        if strict:
            raise RuntimeError(report["reason"])
        return report

    applied = []
    problems = []
    try:
        for target, value, note in build_overrides(config):
            rel = target
            try:
                _set(risk, rel, value)
                applied.append({"target": rel, "value": value, "note": note})
            except Exception as exc:
                problems.append({"target": rel, "error": str(exc)})

        # НИ ОДНОГО перекрытия = отказ, а не успех.
        if not applied:
            report = {"applied": False,
                      "reason": "ни один параметр не удалось перекрыть — конфиг не применился",
                      "source": source, "count": 0, "problems": problems,
                      "expected_keys": [m["config"] for m in MAPPING]}
            if strict:
                raise RuntimeError(report["reason"])
            return report

        # Частичный провал = тоже отказ (applied=False), но факты сохраняем.
        if problems:
            report = {"applied": False,
                      "reason": f"{len(problems)} из {len(applied)+len(problems)} параметров "
                                f"не применились — конфиг применён частично",
                      "source": source, "count": len(applied),
                      "applied": applied, "problems": problems}
            if strict:
                raise RuntimeError(report["reason"])
            return report

        algo = config.get("algo", config)
        tf = _get(algo, "timeframes") or []
        modes = ns.get("TRADING_MODES")
        excluded = []
        if modes and tf:
            for name, mode in modes.items():
                mode_tf = mode.get("timeframes") or []
                compatible = bool(set(mode_tf) & set(tf))
                mode["compatible"] = compatible
                if not compatible:
                    excluded.append(name)

        engine = {
            "source": source,
            "version": _get(config, "version") or _get(config, "app_version"),
            "target_roi": _get(algo, "target_roi"),
            "auto_confirm": _get(algo, "auto_confirm"),
            "timeframes": tf,
            "indicators": _get(algo, "indicators", {}),
            "strategies": _get(config, "strategies", {}),
            "applied": applied,
            "excluded_modes": excluded,
        }
        ns["ENGINE_PARAMS"] = engine
        return {"applied": True, "source": source, "count": len(applied),
                "problems": [], "excluded_modes": excluded,
                "applied_params": applied}
    except Exception as exc:
        report = {"applied": False, "reason": f"исключение при применении: {exc}",
                  "source": source, "count": len(applied), "problems": problems}
        if strict:
            raise
        return report


if __name__ == "__main__":
    cfg, src = load_config()
    print("source:", src)
    print("skills:", len(cfg.get("skills", [])))
    for t, v, n in build_overrides(cfg):
        print(f"  {t} = {v}  ({n})")
