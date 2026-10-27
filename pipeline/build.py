"""主流程：抓数据 -> 计算信号 -> 合成结论 -> 输出 site/data/*.json

运行：python -m pipeline.build
"""
import json
import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yaml

from . import fetch, fundamental as fd, model, technical as ta
from .events import load_events

OUT = fetch.ROOT / "site" / "data"
CST = timezone(timedelta(hours=8))


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if math.isnan(o) or math.isinf(o) else round(float(o), 4)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (pd.Timestamp, datetime, date)):
        return o.strftime("%Y-%m-%d")
    return o


def _dump(name: str, obj) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(_clean(obj), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _series_points(s: pd.Series | None, since: str = "2016-01-01", weekly: bool = False):
    if s is None:
        return []
    s = s.dropna()
    s = s[s.index >= since]
    if weekly:
        s = s.resample("W").last().dropna()
    return [[d.strftime("%Y-%m-%d"), float(v)] for d, v in s.items()]


def _ret(close: pd.Series, n: int) -> float | None:
    return None if len(close) <= n else float(close.iloc[-1] / close.iloc[-1 - n] - 1) * 100


def main() -> None:
    idx_cfg = yaml.safe_load((fetch.ROOT / "config" / "indices.yaml").read_text(encoding="utf-8"))["indices"]
    mcfg = yaml.safe_load((fetch.ROOT / "config" / "model.yaml").read_text(encoding="utf-8"))
    now = datetime.now(CST)
    today = now.date()
    windows = model.quarter_window(today)
    hz_names = {
        "short": mcfg["horizons"]["short"]["name"],
        "current_q": f"本季度剩余（{model.quarter_label(today)}）",
        "next_q": f"下季度（{model.quarter_label(windows['next_q'][0])}）",
    }

    print("抓取宏观数据…")
    cn = fetch.cn_macro()
    us = fetch.us_macro()
    vix = fetch.yf_close("^VIX", "VIX恐慌指数")
    dxy = fetch.yf_close("DX-Y.NYB", "美元指数")
    wti = fetch.yf_close("CL=F", "WTI原油")
    brent = fetch.yf_close("BZ=F", "布伦特原油")
    print("抓取期权数据…")
    vix3m = fetch.yf_close("^VIX3M", "VIX3M")
    skew = fetch.yf_close("^SKEW", "SKEW指数")
    cboe = fetch.cboe_pcr()
    cn_opt = fetch.cn_option_pcr()
    events = load_events(today)

    us_macro = fd.us_macro_signals(us) + fd.dxy_signal(dxy, 0.6) + fd.oil_signal(wti, 1.0)
    cn_macro = fd.cn_macro_signals(cn) + fd.dxy_signal(dxy, 1.0) + fd.oil_signal(wti, 0.8)
    for s in us_macro:
        if s["key"] in ("us10y", "us_ffr"):
            cn_macro.append({**s, "name": s["name"] + "（外部）", "weight": 0.5})
    hy = fd.hy_signal(us.get("BAMLH0A0HYM2"))
    sent_base = {"US": hy, "CN": fd.margin_signal(cn.get("cn_margin")) + fd.vix_signal(vix, 0.5)}
    macro_by_mkt = {"CN": cn_macro, "US": us_macro}
    rf_by_mkt = {"CN": cn.get("cn10y"), "US": us.get("DGS10")}
    cboe_eq = None if cboe is None or "equity" not in cboe else cboe.set_index("date")["equity"]
    us_opt_base = (fd.term_signal(vix, vix3m) + fd.skew_signal(skew)
                   + fd.pcr_signal(cboe_eq, "CBOE个股认沽认购比", "全美个股期权成交量口径"))
    iv_cache: dict[str, pd.Series | None] = {"^VIX": vix}

    def option_signals(c: dict) -> list[dict]:
        o = c.get("options") or {}
        note = o.get("note")
        if c["market"] == "US":
            sym = o.get("iv")
            if sym and sym not in iv_cache:
                iv_cache[sym] = fetch.yf_close(sym, f"隐含波动率{sym}")
            iv = fd.iv_signal(iv_cache.get(sym), f"隐含波动率 {sym}", note) if sym else []
            return iv + us_opt_base
        out = []
        if o.get("qvix"):
            key = f"qvix_{o['qvix']}"
            if key not in iv_cache:
                iv_cache[key] = fetch.qvix(o["qvix"])
            out += fd.iv_signal(iv_cache[key], "期权波动率QVIX", note)
        if o.get("pcr"):
            out += fd.pcr_signal(fd.cn_pcr_series(cn_opt, [str(x) for x in o["pcr"]]),
                                 "ETF期权认沽认购比", "标的 " + "/".join(map(str, o["pcr"])) + " 成交量口径")
        return out

    summary_items = []
    for c in idx_cfg:
        print(f"处理 {c['name']}…")
        px = fetch.price(c["source"], c["symbol"], c["name"])
        if px is None or len(px) < 300:
            print(f"  跳过：行情数据不足")
            continue
        px = px.dropna(subset=["close"]).reset_index(drop=True)
        mkt = c["market"]
        ind = ta.indicators(px)
        sig = ta.signal_series(ind)
        val = fetch.valuation(c["valuation"], c["name"]) if c.get("valuation") else None
        val_sigs = fd.valuation_signals(val, rf_by_mkt[mkt], px, c.get("valuation", {}).get("note"))
        sent_sigs = sent_base[mkt] + fd.turnover_signal(px)
        opt_sigs = option_signals(c)
        last_date = ind.index[-1]
        stale = (pd.Timestamp(today) - last_date).days > 5

        horizons, tech_hist, backtests = {}, {}, {}
        for hz, fwd in (("short", 20), ("current_q", 60), ("next_q", 120)):
            tw = mcfg["technical_weights"][hz]
            ev_sigs, ev_in = model.event_signals(events, mkt, windows[hz])
            groups = {
                "technical": model.technical_signals(ind, sig, tw),
                "macro": macro_by_mkt[mkt],
                "sentiment": sent_sigs,
                "options": opt_sigs,
                "valuation": val_sigs,
                "event": ev_sigs,
            }
            res = model.combine(groups, mcfg["horizons"][hz]["weights"], mcfg["labels"], ev_in, hz, stale)
            res["signals"] = groups
            res["name"] = hz_names[hz]
            res["window"] = [windows[hz][0].isoformat(), windows[hz][1].isoformat()]
            horizons[hz] = res
            th = model.tech_history(sig, tw)
            tech_hist[hz] = th
            backtests[hz] = model.backtest(ind["close"], th, fwd)

        close = ind["close"]
        ytd_base = close[close.index < pd.Timestamp(last_date.year, 1, 1)]
        stats = {
            "close": float(close.iloc[-1]), "date": last_date, "stale": stale,
            "chg1d": _ret(close, 1), "chg5d": _ret(close, 5), "chg20d": _ret(close, 20),
            "chg_ytd": None if ytd_base.empty else float(close.iloc[-1] / ytd_base.iloc[-1] - 1) * 100,
            "high_52w": float(close.iloc[-250:].max()), "low_52w": float(close.iloc[-250:].min()),
            "rsi": float(ind["rsi"].iloc[-1]),
        }

        chart = ind.iloc[-750:]
        detail = {
            "id": c["id"], "name": c["name"], "market": mkt, "symbol": c["symbol"], "stats": stats,
            "horizons": horizons, "backtests": backtests,
            "chart": {
                "date": [d.strftime("%Y-%m-%d") for d in chart.index],
                "ohlc": chart[["open", "close", "low", "high"]].round(2).values.tolist(),
                "volume": chart["volume"].tolist(),
                "ma20": chart["ma20"].round(2).tolist(), "ma60": chart["ma60"].round(2).tolist(),
                "ma250": chart["ma250"].round(2).tolist(),
                "boll_up": chart["boll_up"].round(2).tolist(), "boll_dn": chart["boll_dn"].round(2).tolist(),
                "tech_short": tech_hist["short"].reindex(chart.index).round(1).tolist(),
                "tech_cq": tech_hist["current_q"].reindex(chart.index).round(1).tolist(),
                "tech_nq": tech_hist["next_q"].reindex(chart.index).round(1).tolist(),
            },
        }
        _dump(f"index_{c['id']}.json", detail)
        summary_items.append({
            "id": c["id"], "name": c["name"], "market": mkt, "stats": stats,
            "spark": [round(float(v), 2) for v in close.iloc[-120:]],
            "horizons": {hz: {k: h[k] for k in ("score", "label", "cls", "confidence", "groups")} for hz, h in horizons.items()},
        })

    macro_charts = {
        "CN": {"制造业PMI": _series_points(cn.get("cn_pmi")), "CPI同比": _series_points(cn.get("cn_cpi")),
               "PPI同比": _series_points(cn.get("cn_ppi")), "M1同比": _series_points(cn.get("cn_m1")),
               "M2同比": _series_points(cn.get("cn_m2")),
               "10年期国债": _series_points(cn.get("cn10y"), weekly=True),
               "融资余额(万亿)": _series_points(None if cn.get("cn_margin") is None else cn["cn_margin"] / 1e12, weekly=True)},
        "US": {"联邦基金利率": _series_points(us.get("DFF"), weekly=True),
               "CPI同比": _series_points(None if us.get("CPIAUCSL") is None else (us["CPIAUCSL"] / us["CPIAUCSL"].shift(12) - 1) * 100),
               "失业率": _series_points(us.get("UNRATE")), "10年期美债": _series_points(us.get("DGS10"), weekly=True),
               "10Y-2Y利差": _series_points(us.get("T10Y2Y"), weekly=True),
               "高收益债利差": _series_points(us.get("BAMLH0A0HYM2"), weekly=True),
               "VIX": _series_points(vix, weekly=True), "美元指数": _series_points(dxy, weekly=True),
               "WTI原油": _series_points(wti, weekly=True), "布伦特原油": _series_points(brent, weekly=True),
               "VIX/VIX3M": _series_points(None if vix3m is None else (vix / vix3m), since="2020-01-01"),
               "CBOE个股认沽认购比": _series_points(cboe_eq)},
    }
    macro_charts["CN"]["300ETF期权QVIX"] = _series_points(iv_cache.get("qvix_300etf"), since="2020-01-01")
    macro_charts["CN"]["300ETF认沽认购比"] = _series_points(fd.cn_pcr_series(cn_opt, ["510300", "159919"]))
    hs300_opt = option_signals(next(c for c in idx_cfg if c["market"] == "CN"))
    _dump("macro.json", {"signals": {"CN": cn_macro, "US": us_macro,
                                     "CN_sent": sent_base["CN"], "US_sent": sent_base["US"],
                                     "CN_opt": hs300_opt, "US_opt": fd.iv_signal(vix, "隐含波动率 ^VIX") + us_opt_base},
                         "charts": macro_charts})
    _dump("summary.json", {
        "generated_at": now.strftime("%Y-%m-%d %H:%M"), "today": today,
        "horizons": {hz: {"name": hz_names[hz], "window": [w[0].isoformat(), w[1].isoformat()],
                          "weights": mcfg["horizons"][hz]["weights"]} for hz, w in windows.items()},
        "group_names": model.GROUP_NAMES, "labels": mcfg["labels"],
        "indices": summary_items, "events": events, "status": fetch.STATUS,
    })
    print(f"完成：{len(summary_items)} 个指数，数据源 {sum(s['ok'] for s in fetch.STATUS)}/{len(fetch.STATUS)} 正常")


if __name__ == "__main__":
    main()
