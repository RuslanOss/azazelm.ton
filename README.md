# Skills — Портфельный аналитик

Набор модулей для анализа криптопортфеля, DEX-трейдинга и фьючерсных сигналов.

## Структура веток

| Ветка | Назначение |
|---|---|
| `main` | Базовая структура, README |
| `feature/portfolio-core` | Ядро портфельного анализатора (P&L, снапшоты, цены) |
| `feature/dex-analysis` | Анализ DEX-пулов (STON.fi, DeDust) |
| `feature/futures-signals` | Фьючерсные сигналы и точки входа/выхода |
| `feature/keeper-wallet` | Интеграция с Keeper Wallet |

## Быстрый старт

```bash
# Переключиться на нужную ветку
git checkout feature/portfolio-core

# Установка
pip install requests python-dotenv

# Настройка
cp .env.example .env
# Заполните API-ключи

# Запуск
python portfolio.py --wallet UQ... --api coingecko
```

## Модули

### portfolio-core
- `portfolio.py` — базовый анализатор (P&L, цены, снапшоты)
- `data/` — ежедневные снапшоты портфеля

### dex-analysis
- Анализ ликвидности пулов
- Отслеживание пар (GRAM/USDT, TON/USDT и др.)

### futures-signals
- Сигналы на вход/выход
- Мониторинг funding rate и open interest

### keeper-wallet
- Интеграция с торговым кошельком
- Синхронизация сделок

## Лицензия

MIT
