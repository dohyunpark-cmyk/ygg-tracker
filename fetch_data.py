"""
YGG Competitor Tracker — daily data fetcher.

Outputs `data.json` consumed by the static HTML dashboard.

Sources:
- Prices, 52w range, market cap, 3-month sparkline: yfinance (free, no key)
- News: Finnhub /company-news (if FINNHUB_API_KEY set) → Yahoo Finance (fallback)

Run locally: `python fetch_data.py`
Schedule:    GitHub Actions, daily at 00:00 UTC (09:00 KST).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yfinance as yf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("ygg")

OUTPUT_PATH = Path(__file__).resolve().parent / "data.json"
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "").strip()
FINNHUB_BASE = "https://finnhub.io/api/v1"
NEWS_LOOKBACK_DAYS = 60
SPARKLINE_POINTS = 14  # ~weekly samples over a 3-month window

STOCKS = [
    {
        "id": "WEB",
        "ticker": "ASX:WEB",
        "yahoo": "WEB.AX",
        "finnhub": "WEB.AX",
        "name": "Web Travel Group",
        "subtitle": "WebBeds 단일 운영사 (호주 상장 B2B)",
        "currency": "AUD",
        "symbol": "A$",
    },
    {
        "id": "TBO",
        "ticker": "NSE:TBOTEK",
        "yahoo": "TBOTEK.NS",
        "finnhub": "TBOTEK.NS",
        "name": "TBO Tek",
        "subtitle": "인도 글로벌 B2B 트래블 플랫폼",
        "currency": "INR",
        "symbol": "₹",
    },
    {
        "id": "HBX",
        "ticker": "BME:HBX",
        "yahoo": "HBX.MC",
        "finnhub": "HBX.MC",
        "name": "HBX Group",
        "subtitle": "Hotelbeds·Bedsonline 모회사",
        "currency": "EUR",
        "symbol": "€",
    },
]


# ----------------------------- Formatting helpers -----------------------------

def format_market_cap(value, currency: str, symbol: str):
    """Format raw market cap into a readable, locale-aware string."""
    if not value or value <= 0:
        return None
    if currency == "INR":
        # Indian convention: Crore (10M)
        return f"₹{value / 1e7:,.0f} Cr"
    if value >= 1e9:
        return f"{symbol}{value / 1e9:.2f}B"
    if value >= 1e6:
        return f"{symbol}{value / 1e6:.0f}M"
    return f"{symbol}{value:,.0f}"


# ------------------------------ Price fetching --------------------------------

def fetch_price_block(yahoo_symbol: str):
    """Fetch price snapshot + 3-month sparkline via yfinance. Returns dict or None."""
    try:
        ticker = yf.Ticker(yahoo_symbol)
        hist = ticker.history(period="3mo", interval="1d", auto_adjust=False)
        if hist is None or hist.empty:
            log.warning("%s: empty 3-month history", yahoo_symbol)
            return None

        # .info can occasionally fail on yfinance — degrade gracefully
        try:
            info = ticker.info or {}
        except Exception as e:
            log.warning("%s: .info failed (%s) — proceeding without metadata", yahoo_symbol, e)
            info = {}

        closes = hist["Close"].dropna()
        if closes.empty:
            return None

        current = float(closes.iloc[-1])
        first = float(closes.iloc[0])
        change_3m_pct = ((current - first) / first * 100) if first > 0 else 0.0

        # Down-sample sparkline to ~SPARKLINE_POINTS evenly spaced points
        n = len(closes)
        if n <= SPARKLINE_POINTS:
            sample_idx = list(range(n))
        else:
            step = n / SPARKLINE_POINTS
            sample_idx = [int(i * step) for i in range(SPARKLINE_POINTS)]
            if sample_idx[-1] != n - 1:
                sample_idx.append(n - 1)

        sparkline = [
            {
                "date": closes.index[i].strftime("%Y-%m-%d"),
                "price": round(float(closes.iloc[i]), 4),
            }
            for i in sample_idx
        ]

        # 52-week range — prefer info, fall back to a 1-year history slice
        high_52w = info.get("fiftyTwoWeekHigh")
        low_52w = info.get("fiftyTwoWeekLow")
        if not (high_52w and low_52w):
            try:
                year_hist = ticker.history(period="1y", interval="1d")
                if not year_hist.empty:
                    high_52w = high_52w or float(year_hist["High"].max())
                    low_52w = low_52w or float(year_hist["Low"].min())
            except Exception as e:
                log.warning("%s: 1y fallback failed: %s", yahoo_symbol, e)

        return {
            "price": round(current, 2),
            "high_52w": round(float(high_52w), 2) if high_52w else None,
            "low_52w": round(float(low_52w), 2) if low_52w else None,
            "change_3m_pct": round(change_3m_pct, 1),
            "market_cap_raw": info.get("marketCap"),
            "sparkline": sparkline,
            "last_close_date": closes.index[-1].strftime("%Y-%m-%d"),
        }

    except Exception as e:
        log.error("%s: price fetch failed: %s", yahoo_symbol, e)
        return None


# ----------------------------- Sentiment classifier ---------------------------

NEG_KW = (
    "drop", "fall", "plunge", "slump", "audit", "investigation", "tax probe",
    "fraud", "miss", "downgrade", "cut", "concern", "lawsuit", "decline",
    "lower", "warn", "loss", "weak", "impair", "scandal",
    "하락", "세무조사", "감소", "약세", "하향", "소송", "실망", "손실",
)
INFO_KW = (
    "acquisition", "acquire", "merger", "buyback", "dividend",
    "spin-off", "redeem", "convertible", "capital raise", "ipo",
    "listing", "stake",
    "인수", "합병", "자사주", "배당", "전환사채", "자본",
)
POS_KW = (
    "surge", "beat", "record", "growth", "upgrade", "rally", "gain",
    "strong", "rise", "jump", "boost", "expand", "outperform",
    "상승", "강세", "실적호조", "상향", "성장", "확장", "돌파",
)


def classify_sentiment(headline: str, summary: str = "") -> str:
    text = f"{headline} {summary}".lower()
    if any(k in text for k in NEG_KW):
        return "negative"
    if any(k in text for k in INFO_KW):
        return "info"
    if any(k in text for k in POS_KW):
        return "positive"
    return "neutral"


# -------------------------------- News fetching -------------------------------

def fetch_finnhub_news(symbol: str, days: int = NEWS_LOOKBACK_DAYS):
    if not FINNHUB_API_KEY:
        return []

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)

    try:
        r = requests.get(
            f"{FINNHUB_BASE}/company-news",
            params={
                "symbol": symbol,
                "from": start.isoformat(),
                "to": end.isoformat(),
                "token": FINNHUB_API_KEY,
            },
            timeout=15,
        )
        if r.status_code == 401:
            log.error("Finnhub 401 — check FINNHUB_API_KEY")
            return []
        if r.status_code == 429:
            log.warning("Finnhub 429 (rate limit) — falling back to Yahoo")
            return []
        r.raise_for_status()
        items = r.json() or []
    except Exception as e:
        log.warning("%s: Finnhub fetch failed: %s", symbol, e)
        return []

    out = []
    for item in items[:15]:
        ts = item.get("datetime")
        if not ts:
            continue
        try:
            d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, OSError):
            continue
        headline = (item.get("headline") or "").strip()
        if not headline:
            continue
        out.append({
            "date": d,
            "headline": headline[:140],
            "sentiment": classify_sentiment(headline, item.get("summary", "")),
            "url": item.get("url", ""),
            "source": item.get("source", "Finnhub"),
        })
    return out


def fetch_yahoo_news(yahoo_symbol: str):
    try:
        items = yf.Ticker(yahoo_symbol).news or []
    except Exception as e:
        log.warning("%s: Yahoo news fetch failed: %s", yahoo_symbol, e)
        return []

    out = []
    for item in items[:15]:
        # Newer yfinance versions nest payload under 'content'
        content = item.get("content") or {}
        title = (item.get("title") or content.get("title") or "").strip()
        if not title:
            continue

        # Timestamp may arrive as Unix int or ISO string
        ts_raw = item.get("providerPublishTime") or content.get("pubDate")
        pub_dt = None
        if isinstance(ts_raw, (int, float)):
            try:
                pub_dt = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
            except (ValueError, OSError):
                pub_dt = None
        elif isinstance(ts_raw, str):
            try:
                pub_dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                pub_dt = None
        if pub_dt is None:
            continue

        url = (
            item.get("link")
            or (content.get("canonicalUrl") or {}).get("url")
            or (content.get("clickThroughUrl") or {}).get("url")
            or ""
        )
        publisher = (
            item.get("publisher")
            or (content.get("provider") or {}).get("displayName")
            or "Yahoo Finance"
        )
        summary = item.get("summary") or content.get("summary") or ""

        out.append({
            "date": pub_dt.strftime("%Y-%m-%d"),
            "headline": title[:140],
            "sentiment": classify_sentiment(title, summary),
            "url": url,
            "source": publisher,
        })
    return out


def fetch_news(stock: dict, max_items: int = 6):
    """Try Finnhub first, fall back to Yahoo. Sort newest first, dedupe."""
    items = fetch_finnhub_news(stock["finnhub"])
    used = "finnhub"
    if not items:
        items = fetch_yahoo_news(stock["yahoo"])
        used = "yahoo"

    log.info("%s news: %d raw items via %s", stock["id"], len(items), used)

    seen = set()
    unique = []
    for n in sorted(items, key=lambda x: x["date"], reverse=True):
        key = n["headline"].strip().lower()[:50]
        if key in seen:
            continue
        seen.add(key)
        unique.append(n)
    return unique[:max_items]


# ------------------------------------ Main ------------------------------------

def main() -> int:
    log.info("Starting fetch_data...")
    log.info(
        "Finnhub key: %s",
        "set" if FINNHUB_API_KEY else "not set (Yahoo-only news mode)",
    )

    out = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "stocks": [],
        "errors": [],
    }

    for stock in STOCKS:
        log.info("Fetching %s (%s)", stock["ticker"], stock["yahoo"])

        price = fetch_price_block(stock["yahoo"])
        if not price:
            err = f"{stock['ticker']}: price fetch failed"
            log.error(err)
            out["errors"].append(err)
            continue

        news = fetch_news(stock)
        market_cap = format_market_cap(
            price.get("market_cap_raw"),
            stock["currency"],
            stock["symbol"],
        )

        out["stocks"].append({
            "id": stock["id"],
            "ticker": stock["ticker"],
            "yahoo": stock["yahoo"],
            "name": stock["name"],
            "subtitle": stock["subtitle"],
            "currency": stock["currency"],
            "symbol": stock["symbol"],
            "price": price["price"],
            "high_52w": price["high_52w"],
            "low_52w": price["low_52w"],
            "change_3m_pct": price["change_3m_pct"],
            "market_cap": market_cap,
            "last_close_date": price["last_close_date"],
            "sparkline": price["sparkline"],
            "news": news,
        })

        time.sleep(0.5)  # Be nice to APIs

    OUTPUT_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(
        "Wrote %s — %d stocks ok, %d errors",
        OUTPUT_PATH.name, len(out["stocks"]), len(out["errors"]),
    )

    # Exit non-zero if we got nothing — useful for CI alerts
    return 0 if out["stocks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
