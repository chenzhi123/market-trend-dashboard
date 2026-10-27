"""把各维度信号按周期加权合成多空结论。"""
from datetime import date

import numpy as np
import pandas as pd

from . import technical as ta
from .events import applies

GROUP_NAMES = {"technical": "技术面", "macro": "宏观面", "sentiment": "情绪资金", "options": "期权",
               "valuation": "估值", "event": "事件"}


def quarter_window(today: date) -> dict[str, tuple[date, date]]:
    q_end = (pd.Timestamp(today) + pd.offsets.QuarterEnd(0)).date()
    nq_start = (pd.Timestamp(q_end) + pd.Timedelta(days=1)).date()
    nq_end = (pd.Timestamp(nq_start) + pd.offsets.QuarterEnd(0)).date()
    return {
        "short": (today, (pd.Timestamp(today) + pd.Timedelta(days=28)).date()),
        "current_q": (today, q_end),
        "next_q": (nq_start, nq_end),
    }


def quarter_label(d: date) -> str:
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def label_of(score: float, labels: list[dict]) -> dict:
    for item in labels:
        if score >= item["min"]:
            return {"label": item["label"], "cls": item["cls"]}
    return {"label": labels[-1]["label"], "cls": labels[-1]["cls"]}


def _wavg(signals: list[dict]) -> float | None:
    sig = [s for s in signals if s["score"] is not None and not np.isnan(s["score"])]
    if not sig:
        return None
    w = sum(s.get("weight", 1.0) for s in sig)
    return sum(s["score"] * s.get("weight", 1.0) for s in sig) / w


def technical_signals(ind: pd.DataFrame, sig: pd.DataFrame, weights: dict) -> list[dict]:
    row = ind.iloc[-1]
    out = []
    for key, w in weights.items():
        val, note = ta.describe(key, row)
        if key.startswith("mom"):
            n = int(key[3:])
            r = (ind["close"].iloc[-1] / ind["close"].iloc[-1 - n] - 1) * 100
            val, note = f"{r:+.1f}%", f"近{n}个交易日涨跌幅（已按波动率标准化打分）"
        score = sig[key].iloc[-1]
        out.append({"key": key, "name": ta.SIGNAL_NAMES[key], "value": val, "note": note,
                    "score": None if pd.isna(score) else round(float(score), 1), "weight": w,
                    "asof": ind.index[-1].strftime("%Y-%m-%d")})
    return out


def event_signals(events: list[dict], market: str, window: tuple[date, date]) -> tuple[list[dict], list[dict]]:
    lo, hi = window
    inside = [e for e in events if applies(e, market) and lo.isoformat() <= e["date"] <= hi.isoformat()]
    biased = [{"key": f"ev_{e['date']}", "name": e["title"], "value": e["date"], "score": float(e["bias"]),
               "note": e.get("note") or "手工设定的事件影响", "weight": 1.0 if e["importance"] == "high" else 0.5,
               "asof": e["date"]} for e in inside if e.get("bias") is not None]
    return biased, inside


def tech_history(sig: pd.DataFrame, weights: dict) -> pd.Series:
    cols = list(weights)
    w = pd.Series(weights)
    avail = sig[cols].notna().mul(w).sum(axis=1)
    hist = (sig[cols] * w).sum(axis=1) / avail
    return hist.where(avail >= 0.7 * w.sum())


def backtest(close: pd.Series, score: pd.Series, fwd: int, years: int = 8) -> dict:
    fr = close.shift(-fwd) / close - 1
    df = pd.DataFrame({"s": score, "r": fr}).dropna()
    if df.empty:
        return {"fwd_days": fwd, "samples": 0}
    df = df[df.index >= df.index[-1] - pd.DateOffset(years=years)]
    bull, bear = df[df["s"] >= 10], df[df["s"] <= -10]
    return {
        "fwd_days": fwd, "samples": int(len(df)),
        "bull_hit": None if bull.empty else round(float((bull["r"] > 0).mean() * 100), 1),
        "bear_hit": None if bear.empty else round(float((bear["r"] < 0).mean() * 100), 1),
        "bull_avg": None if bull.empty else round(float(bull["r"].mean() * 100), 2),
        "bear_avg": None if bear.empty else round(float(bear["r"].mean() * 100), 2),
        "base_up": round(float((df["r"] > 0).mean() * 100), 1),
    }


def combine(groups: dict[str, list[dict]], weights: dict, labels: list[dict],
            events_in_window: list[dict], horizon: str, stale: bool) -> dict:
    group_scores, used_w = {}, {}
    for g, sigs in groups.items():
        sc = _wavg(sigs)
        group_scores[g] = None if sc is None else round(sc, 1)
        if sc is not None and weights.get(g, 0) > 0:
            used_w[g] = weights[g]
    total_w = sum(used_w.values()) or 1
    score = sum(group_scores[g] * w for g, w in used_w.items()) / total_w

    # 置信度：分数强度 + 信号一致性 - 重大事件 - 数据过期
    agree_w = tot = 0.0
    for g, w in used_w.items():
        sigs = [s for s in groups[g] if s["score"] is not None]
        ws = sum(s.get("weight", 1) for s in sigs) or 1
        for s in sigs:
            share = w / total_w * s.get("weight", 1) / ws
            tot += share
            if np.sign(s["score"]) == np.sign(score) and abs(s["score"]) > 5:
                agree_w += share
    agreement = agree_w / tot if tot else 0.5
    high = [e for e in events_in_window if e["importance"] == "high"]
    penalty = min(len(high) * (6 if horizon == "short" else 2), 20)
    conf = 30 + abs(score) * 0.7 + (agreement - 0.5) * 60 - penalty - (10 if stale else 0)
    return {
        "score": round(score, 1), **label_of(score, labels),
        "confidence": int(np.clip(conf, 15, 90)), "agreement": round(agreement * 100),
        "groups": group_scores, "weights": {g: round(w / total_w, 3) for g, w in used_w.items()},
        "event_penalty": penalty, "key_events": high[:6],
    }
