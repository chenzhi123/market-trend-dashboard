"""个股计划：读取 config/watchlist.yaml，抓现价，按计划区间判定状态，输出 site/data/stocks.json。

单独运行：python -m pipeline.stocks
"""
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import yaml

from . import fetch, substack

CFG = fetch.ROOT / "config"
OUT = fetch.ROOT / "site" / "data" / "stocks.json"
CST = timezone(timedelta(hours=8))
NEAR_PCT = 5.0

BUY_TYPES = ("starter", "buy", "add", "deep")
SELL_TYPES = ("reassess", "trim")
STATUS = {
    "below_plan": {"label": "跌破计划区", "level": "alert"},
    "deep": {"label": "深度加仓区", "level": "alert"},
    "add": {"label": "加仓区", "level": "alert"},
    "buy": {"label": "主要买入区", "level": "alert"},
    "starter": {"label": "试探建仓区", "level": "alert"},
    "near": {"label": "接近买入区", "level": "near"},
    "watch": {"label": "观望", "level": "none"},
    "reassess": {"label": "重新评估区", "level": "sell"},
    "trim": {"label": "兑现区", "level": "sell"},
    "nodata": {"label": "无行情", "level": "none"},
}
ZONE_NAMES = {"starter": "试探/第一档", "buy": "主要买入", "add": "加仓", "deep": "深度加仓（需复核）",
              "reassess": "重新评估", "trim": "分批兑现"}


def _pct(a: float | None, b: float | None) -> float | None:
    return None if a is None or b in (None, 0) else (a / b - 1) * 100


def _history(symbol: str, name: str) -> pd.DataFrame | None:
    def run():
        import yfinance as yf
        df = yf.Ticker(symbol).history(period="2y", auto_adjust=False).reset_index()
        return df.rename(columns={"Date": "date", "Close": "close"})[["date", "close"]].dropna()
    return fetch.cached(f"stk_{symbol}", f"个股·{name}", run)


def classify(price: float, zones: list[dict]) -> tuple[str, dict | None]:
    """返回 (状态键, 命中的区间)。买入侧取价格已触及的最低一档；卖出侧取已触及的最高一档。"""
    buys = sorted((z for z in zones if z["type"] in BUY_TYPES), key=lambda z: -z["high"])
    sells = sorted((z for z in zones if z["type"] in SELL_TYPES), key=lambda z: z["low"])
    reached = [z for z in buys if price <= z["high"]]
    if reached:
        z = reached[-1]
        if z is buys[-1] and z.get("low") is not None and price < z["low"]:
            return "below_plan", z
        return z["type"], z
    hit = [z for z in sells if price >= z["low"]]
    if hit:
        return hit[-1]["type"], hit[-1]
    if buys and _pct(price, buys[0]["high"]) <= NEAR_PCT:
        return "near", buys[0]
    return "watch", None


def _prev_state() -> dict:
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
        return {s["ticker"]: s.get("status") or {} for s in old.get("stocks", [])}
    except Exception:  # noqa: BLE001
        return {}


def build(sync: dict | None = None) -> dict:
    wl = yaml.safe_load((CFG / "watchlist.yaml").read_text(encoding="utf-8")) or {}
    cats = yaml.safe_load((CFG / "categories.yaml").read_text(encoding="utf-8"))
    sync = sync or substack.sync()
    prev = _prev_state()
    now = datetime.now(CST)
    posts_by_slug = {p["slug"]: p for p in sync["posts"]}

    items = []
    for s in wl.get("stocks") or []:
        s = dict(s)
        zones = s.get("zones") or []
        for z in zones:
            z["name"] = ZONE_NAMES[z["type"]]
        for p in s.get("posts") or []:
            p.setdefault("url", (posts_by_slug.get(p["slug"]) or {}).get("url") or f"{substack.PUB}/p/{p['slug']}")

        df = _history(s["symbol"], s["name"])
        if df is None or df.empty:
            s["price"] = None
            key, zone = "nodata", None
        else:
            close = df.set_index("date")["close"].astype(float)
            last = float(close.iloc[-1])
            y1 = close[close.index >= close.index[-1] - pd.Timedelta(days=365)]
            s["price"] = {
                "last": last, "date": close.index[-1],
                "stale": (pd.Timestamp(now.date()) - close.index[-1]).days > 5,
                "chg1d": _pct(last, float(close.iloc[-2])) if len(close) > 1 else None,
                "chg5d": _pct(last, float(close.iloc[-6])) if len(close) > 5 else None,
                "chg20d": _pct(last, float(close.iloc[-21])) if len(close) > 20 else None,
                "high_52w": float(y1.max()), "low_52w": float(y1.min()),
            }
            s["chart"] = [[d.strftime("%Y-%m-%d"), round(float(v), 4)] for d, v in y1.items()]
            key, zone = classify(last, zones)

        old = prev.get(s["ticker"], {})
        if old.get("key") == key:
            since = old.get("since")
        else:
            since = now.strftime("%Y-%m-%d") if prev else None
        s["status"] = {**STATUS[key], "key": key, "zone": zone, "since": since,
                       "prev": old.get("key") if old.get("key") != key else old.get("prev")}

        last = (s["price"] or {}).get("last")
        buys = [z for z in zones if z["type"] in BUY_TYPES]
        top_buy = max((z["high"] for z in buys), default=None)
        t = s.get("targets") or {}
        s["metrics"] = {
            "dist_to_buy": _pct(last, top_buy),
            "upside_bear": _pct(t.get("bear"), last),
            "upside_base": _pct(t.get("base"), last),
            "upside_bull": _pct(t.get("bull"), last),
            "vs_ref": _pct(last, (s.get("ref") or {}).get("price")),
        }
        s["guards_hit"] = [g for g in s.get("guards") or [] if last is not None and last < g["below"]]
        items.append(s)

    result = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "near_pct": NEAR_PCT,
        "statuses": STATUS,
        "categories": cats,
        "stocks": items,
        "substack": {"ok": sync["ok"], "error": sync["error"], "count": len(sync["posts"]),
                     "pending": sync["pending"], "url": substack.PUB},
    }
    return result


def main() -> dict:
    from .build import _dump
    print("同步 Substack 帖子…")
    sync = substack.sync()
    print(f"  共 {len(sync['posts'])} 篇，待录入 {len(sync['pending'])} 篇" + ("" if sync["ok"] else f"（离线：{sync['error']}）"))
    print("计算个股计划状态…")
    res = build(sync)
    _dump(OUT.name, res)
    alerts = [s for s in res["stocks"] if s["status"]["level"] == "alert"]
    print(f"  {len(res['stocks'])} 只标的，{len(alerts)} 只处于买入/加仓区间："
          + "、".join(f"{s['ticker']}({s['status']['label']})" for s in alerts))
    return res


if __name__ == "__main__":
    main()
