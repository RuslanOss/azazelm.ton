#!/usr/bin/env python3
"""Portfolio Core — базовый анализатор криптопортфеля.

Использование:
    python portfolio.py --wallet <address> [--api polygon|coingecko]

Зависимости: requests, python-dotenv
"""

import os
import json
import argparse
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ── Конфиг ──────────────────────────────────────────────
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
COINGECKO_API = "https://api.coingecko.com/api/v3"

# ── Классы ──────────────────────────────────────────────

class Asset:
    """Актив портфеля."""
    def __init__(self, symbol: str, amount: float, entry_price: float):
        self.symbol = symbol.upper()
        self.amount = amount
        self.entry_price = entry_price
        self.current_price = 0.0

    @property
    def entry_value(self) -> float:
        return self.amount * self.entry_price

    @property
    def current_value(self) -> float:
        return self.amount * self.current_price

    @property
    def pnl(self) -> float:
        return self.current_value - self.entry_value

    @property
    def pnl_pct(self) -> float:
        if self.entry_value == 0:
            return 0.0
        return (self.pnl / self.entry_value) * 100

    def __repr__(self) -> str:
        return f"<Asset {self.symbol}: {self.amount} @ ${self.current_price:.2f}>"


class Portfolio:
    """Портфель активов."""
    def __init__(self, name: str = "Main"):
        self.name = name
        self.assets: list[Asset] = []
        self.created_at = datetime.utcnow()

    def add(self, asset: Asset) -> None:
        self.assets.append(asset)

    @property
    def total_entry(self) -> float:
        return sum(a.entry_value for a in self.assets)

    @property
    def total_current(self) -> float:
        return sum(a.current_value for a in self.assets)

    @property
    def total_pnl(self) -> float:
        return self.total_current - self.total_entry

    @property
    def total_pnl_pct(self) -> float:
        if self.total_entry == 0:
            return 0.0
        return (self.total_pnl / self.total_entry) * 100

    def summary(self) -> dict:
        return {
            "name": self.name,
            "assets": len(self.assets),
            "entry_value": round(self.total_entry, 2),
            "current_value": round(self.total_current, 2),
            "pnl": round(self.total_pnl, 2),
            "pnl_pct": round(self.total_pnl_pct, 2),
            "updated": datetime.utcnow().isoformat(),
        }

    def __repr__(self) -> str:
        return f"<Portfolio {self.name}: {len(self.assets)} assets, PnL ${self.total_pnl:.2f}>"


# ── Ценовые провайдеры ──────────────────────────────────

def price_from_coingecko(symbol: str) -> float:
    """Получить текущую цену через CoinGecko."""
    import requests
    coin_map = {
        "BTC": "bitcoin", "ETH": "ethereum", "TON": "the-open-network",
        "USDT": "tether", "SOL": "solana", "XRP": "ripple",
    }
    coin_id = coin_map.get(symbol.upper())
    if not coin_id:
        return 0.0
    url = f"{COINGECKO_API}/simple/price?ids={coin_id}&vs_currencies=usd"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        return data.get(coin_id, {}).get("usd", 0.0)
    except Exception:
        return 0.0


def price_from_polygon(symbol: str) -> float:
    """Получить цену через Polygon.io (акции/ETF)."""
    import requests
    if not POLYGON_API_KEY:
        return 0.0
    url = f"https://api.polygon.io/v2/snapshot/locale/stocks?ticker={symbol}&apiKey={POLYGON_API_KEY}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        return float(data.get("results", [{}])[0].get("last", {}).get("close", 0))
    except Exception:
        return 0.0


# ── CLI ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Portfolio Core — анализ портфеля")
    parser.add_argument("--wallet", type=str, help="Адрес кошелька TON")
    parser.add_argument("--api", choices=["coingecko", "polygon"], default="coingecko")
    args = parser.parse_args()

    pf = Portfolio("Crypto Portfolio")

    # Пример активов (заглушка)
    pf.add(Asset("BTC", 0.5, 42000))
    pf.add(Asset("TON", 100, 1.2))
    pf.add(Asset("ETH", 2, 2200))

    # Обновляем цены
    price_fn = price_from_coingecko if args.api == "coingecko" else price_from_polygon
    for asset in pf.assets:
        asset.current_price = price_fn(asset.symbol)
        print(f"  {asset.symbol}: ${asset.current_price:.2f}")

    print(f"\n{'='*50}")
    print(f"  {pf.name}")
    print(f"{'='*50}")
    print(f"  Активов:      {len(pf.assets)}")
    print(f"  Вход:         ${pf.total_entry:>10.2f}")
    print(f"  Текущая:      ${pf.total_current:>10.2f}")
    print(f"  P&L:          ${pf.total_pnl:>+10.2f}")
    print(f"  P&L %:        {pf.total_pnl_pct:>+9.2f}%")
    print(f"{'='*50}")

    # Сохраняем снапшот
    os.makedirs("data", exist_ok=True)
    with open(f"data/snapshot_{datetime.utcnow().strftime('%Y%m%d')}.json", "w") as f:
        json.dump(pf.summary(), f, indent=2)
    print(f"  Снапшот сохранён")


if __name__ == "__main__":
    main()
