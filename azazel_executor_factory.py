# -*- coding: utf-8 -*-
"""Фабрика исполнителей: создаёт исполнитель торговых планов.

Зачем фабрика, а не просто WaltExecutor:
  * биржа выбирается конфигом, а не правкой кода - переключение Walt/Lighter
    не должно требовать изменения модулей;
  * ключи читаются из окружения, а не зашиты;
  * без ключей фабрика не падает, а возвращает исполнитель в dry_run.
    Движок должен уметь отработать рыночную часть цикла и честно сказать,
    что торговлю выполнить нельзя;
  * выбор исполнителя деградирует: если Walt недоступен, а Lighter есть -
    можно использовать его. Но по умолчанию Lighter выключен флагом,
    потому что мы торгуем через Walt.

Фабрика ничего не торгует сама - она только создаёт объект.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from azazel_walt_executor import WaltExecutor
except Exception:
    WaltExecutor = None

try:
    from walt_client import WaltClient
except Exception:
    WaltClient = None


ENV_KEY = "WALT_API_KEY"
ENV_SECRET = "WALT_API_SECRET"
ENV_URL = "WALT_BASE_URL"
ENV_EXCHANGE = "AZAZEL_EXCHANGE"      # "walt" (по умолчанию) или "lighter"
ENV_DRY_RUN = "AZAZEL_DRY_RUN"        # "1"/"true" -> не отправлять ордера


def _env_flag(name, default=False):
    v = os.environ.get(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def exchange_name():
    """Какая биржа настроена: 'walt' или 'lighter'."""
    return (os.environ.get(ENV_EXCHANGE) or "walt").strip().lower()


def credentials_available():
    """Есть ли ключи Walt в окружении."""
    return bool((os.environ.get(ENV_KEY) or "").strip()
                and (os.environ.get(ENV_SECRET) or "").strip())


def make_client(key=None, secret=None):
    """Создать WaltClient. -> (client, error). error=None если всё хорошо.

    Явные key/secret имеют приоритет над окружением. Это нужно для
    per-user ключей: у каждого пользователя свой ключ, и в окружении
    их быть не может.
    """
    if WaltClient is None:
        return None, "модуль walt_client не импортируется"
    key = (key or os.environ.get(ENV_KEY) or "").strip()
    secret = (secret or os.environ.get(ENV_SECRET) or "").strip()
    if not key or not secret:
        return None, ("нет ключей Walt: задай %s и %s в окружении"
                      % (ENV_KEY, ENV_SECRET))
    url = (os.environ.get(ENV_URL) or "https://bot.mywellat.com").strip()
    try:
        return WaltClient(key, secret, base_url=url), None
    except Exception as e:
        return None, "не удалось создать клиент Walt: %s" % str(e)[:200]


def make_executor(dry_run=None, min_notional=None, key=None, secret=None):
    """Создать исполнитель торговых планов.

    Явные key/secret (per-user) имеют приоритет над окружением.

    -> (executor, info)
    executor может быть None, если исполнитель построить не удалось.
    info - dict с полями: exchange, dry_run, error, reason.
    """
    info = {"exchange": exchange_name(), "dry_run": False, "error": None,
            "reason": ""}

    ex = exchange_name()
    if ex == "lighter":
        # Lighter оставлен как запасной вариант, но по умолчанию выключен:
        # торговля идёт через Walt.
        try:
            from azazel_trading_v5 import LighterExecutor
        except Exception as e:
            info["error"] = "LighterExecutor недоступен: %s" % str(e)[:200]
            return None, info
        info["dry_run"] = bool(dry_run) if dry_run is not None else False
        info["reason"] = "исполнитель Lighter (запасной)"
        return LighterExecutor(client=None, market_index=None), info

    if WaltExecutor is None:
        info["error"] = "модуль azazel_walt_executor не импортируется"
        return None, info

    client, err = make_client(key, secret)
    if client is None:
        # Без ключей - dry_run, чтобы цикл отработал и не упал.
        info["dry_run"] = True
        info["error"] = err
        info["reason"] = ("без ключей Walt работаем в dry_run: планы считаются, "
                          "ордера не отправляются")
        if dry_run is False:
            # Явно попросили торговать, а ключей нет - исполнитель не создаём.
            return None, info
        return WaltExecutor(client=None, dry_run=True,
                             min_notional=min_notional), info

    if dry_run is None:
        dry_run = _env_flag(ENV_DRY_RUN, False)
    info["dry_run"] = bool(dry_run)
    info["reason"] = ("исполнитель Walt%s"
                      % (" (dry_run)" if dry_run else ""))
    return WaltExecutor(client=client, dry_run=bool(dry_run),
                         min_notional=min_notional), info
