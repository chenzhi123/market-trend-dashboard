"""宏观事件日历：手工配置 + 自动生成的周期性事件。"""
from datetime import date, timedelta

import pandas as pd
import yaml

from .fetch import ROOT


def _first_friday(y: int, m: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(4 - d.weekday()) % 7)
    return d + timedelta(days=7) if d.day == 1 and m == 1 else d


def _month_end(y: int, m: int) -> date:
    return (pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)).date()


def load_events(today: date, months_ahead: int = 6) -> list[dict]:
    cfg = yaml.safe_load((ROOT / "config" / "events.yaml").read_text(encoding="utf-8")) or {}
    events = []
    for e in cfg.get("events", []):
        d = e["date"] if isinstance(e["date"], date) else pd.Timestamp(e["date"]).date()
        events.append({**e, "date": d, "auto": False, "confirmed": e.get("confirmed", True)})

    start = pd.Timestamp(today.replace(day=1)) - pd.DateOffset(months=1)
    for i in range(months_ahead + 2):
        p = start + pd.DateOffset(months=i)
        y, m = p.year, p.month
        events.append({"date": _first_friday(y, m), "title": "美国非农就业报告", "market": "ALL",
                       "importance": "high", "auto": True, "confirmed": False})
        events.append({"date": _month_end(y, m), "title": "中国官方制造业PMI", "market": "CN",
                       "importance": "medium", "auto": True, "confirmed": False})
        events.append({"date": date(y, m, 12), "title": "美国CPI（约在当月中旬）", "market": "ALL",
                       "importance": "high", "auto": True, "confirmed": False})
        events.append({"date": date(y, m, 10), "title": "中国CPI/PPI（约在当月上旬）", "market": "CN",
                       "importance": "medium", "auto": True, "confirmed": False})

    lo, hi = today - timedelta(days=14), today + timedelta(days=31 * months_ahead)
    events = [e for e in events if lo <= e["date"] <= hi]
    events.sort(key=lambda e: e["date"])
    for e in events:
        e["date"] = e["date"].isoformat()
        e.setdefault("note", "")
    return events


def applies(e: dict, market: str) -> bool:
    return e["market"] in ("ALL", market)
