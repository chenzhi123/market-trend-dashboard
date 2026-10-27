"""宏观、情绪、估值信号。每个信号输出 -100~100 的得分与文字解读。"""
import numpy as np
import pandas as pd


def _clip(x: float, lo: float = -100, hi: float = 100) -> float:
    return float(np.clip(x, lo, hi))


def _last(s: pd.Series) -> tuple[float, pd.Timestamp]:
    s = s.dropna()
    return float(s.iloc[-1]), s.index[-1]


def _ago(s: pd.Series, days: int) -> float:
    """取 days 天前（按日历）的值"""
    s = s.dropna()
    target = s.index[-1] - pd.Timedelta(days=days)
    prev = s[s.index <= target]
    return float(prev.iloc[-1]) if len(prev) else float(s.iloc[0])


def _sig(key, name, value, score, note, asof, weight=1.0):
    return {"key": key, "name": name, "value": value, "score": round(_clip(score), 1), "note": note,
            "asof": pd.Timestamp(asof).strftime("%Y-%m-%d"), "weight": weight}


def _stale_months(asof: pd.Timestamp) -> float:
    return (pd.Timestamp.now() - pd.Timestamp(asof)).days / 30


# ---------------- 中国宏观 ----------------

def cn_macro_signals(m: dict) -> list[dict]:
    out = []
    if "cn_pmi" in m:
        v, d = _last(m["cn_pmi"]); c3 = v - _ago(m["cn_pmi"], 92)
        sc = 0.6 * _clip((v - 50) * 40, -80, 80) + 0.4 * _clip(c3 * 30)
        out.append(_sig("cn_pmi", "制造业PMI", f"{v:.1f}", sc,
                        f"{'扩张' if v >= 50 else '收缩'}区间，近3月{'+' if c3 >= 0 else ''}{c3:.1f}", d, 1.5))
    if "cn_ppi" in m:
        v, d = _last(m["cn_ppi"]); c3 = v - _ago(m["cn_ppi"], 92)
        sc = _clip(c3 * 25) * 0.7 + _clip(v * 8) * 0.3
        out.append(_sig("cn_ppi", "PPI同比", f"{v:+.1f}%", sc, f"近3月变化 {c3:+.1f}pct，反映工业品价格与企业盈利", d))
    if "cn_cpi" in m:
        v, d = _last(m["cn_cpi"]); c3 = v - _ago(m["cn_cpi"], 92)
        sc = (v - 0.8) * 40 + c3 * 30 if v < 2.5 else (3 - v) * 40
        out.append(_sig("cn_cpi", "CPI同比", f"{v:+.1f}%", sc,
                        "通缩压力" if v < 0.5 else "温和通胀" if v < 2.5 else "通胀偏高", d, 0.7))
    if "cn_m1" in m and "cn_m2" in m:
        v1, d = _last(m["cn_m1"]); v2, _ = _last(m["cn_m2"]); c3 = v1 - _ago(m["cn_m1"], 92)
        gap = v1 - v2
        sc = _clip(c3 * 20) * 0.6 + _clip(gap * 8) * 0.4
        out.append(_sig("cn_m1m2", "M1-M2剪刀差", f"{gap:+.1f}pct", sc,
                        f"M1同比 {v1:.1f}%（近3月 {c3:+.1f}），M2同比 {v2:.1f}%，衡量资金活化程度", d, 1.2))
    if "cn_tsf" in m:
        s = m["cn_tsf"].dropna()
        roll = s.rolling(12).sum()
        yoy = (roll / roll.shift(12) - 1) * 100
        if yoy.dropna().size and _stale_months(s.index[-1]) < 4:
            v, d = _last(yoy); c3 = v - _ago(yoy, 92)
            sc = _clip(v * 2, -60, 60) * 0.5 + _clip(c3 * 4) * 0.5
            out.append(_sig("cn_tsf", "社融12月滚动增量同比", f"{v:+.1f}%", sc, f"近3月变化 {c3:+.1f}pct，衡量信用扩张", d))
    if "cn10y" in m:
        v, d = _last(m["cn10y"]); c = (v - _ago(m["cn10y"], 91)) * 100
        sc = _clip(-c * 0.8, -50, 50)
        out.append(_sig("cn10y", "10年期国债收益率", f"{v:.2f}%", sc,
                        f"近3月 {c:+.0f}bp，{'利率下行，流动性宽松' if c < 0 else '利率上行，宽松预期降温'}", d, 0.8))
    return out


# ---------------- 美国宏观 ----------------

def us_macro_signals(m: dict) -> list[dict]:
    out = []
    if "DFF" in m:
        v, d = _last(m["DFF"]); c = v - _ago(m["DFF"], 182)
        out.append(_sig("us_ffr", "联邦基金利率", f"{v:.2f}%", _clip(-c * 80, -80, 80),
                        f"近6月 {c * 100:+.0f}bp，{'降息周期' if c < -0.1 else '加息周期' if c > 0.1 else '利率按兵不动'}", d, 1.2))
    if "CPIAUCSL" in m:
        idx = m["CPIAUCSL"].dropna()
        yoy = (idx / idx.shift(12) - 1) * 100
        v, d = _last(yoy); c3 = v - _ago(yoy, 92)
        sc = (2.5 - v) * 25 - c3 * 40
        out.append(_sig("us_cpi", "美国CPI同比", f"{v:.1f}%", sc, f"近3月 {c3:+.1f}pct，通胀{'回落' if c3 < 0 else '回升'}", d))
    if "UNRATE" in m:
        u = m["UNRATE"].dropna()
        sahm = u.rolling(3).mean() - u.rolling(3).mean().rolling(12).min()
        v, d = _last(u); sv = float(sahm.iloc[-1])
        out.append(_sig("us_unrate", "失业率（萨姆规则）", f"{v:.1f}%", 20 - sv * 150,
                        f"萨姆指标 {sv:.2f}，≥0.5 历史上对应衰退", d, 1.2))
    if "DGS10" in m:
        v, d = _last(m["DGS10"]); c = (v - _ago(m["DGS10"], 91)) * 100
        sc = _clip(-c * 0.6, -60, 60) - max(v - 4.5, 0) * 40
        out.append(_sig("us10y", "10年期美债收益率", f"{v:.2f}%", sc, f"近3月 {c:+.0f}bp，高利率压制估值", d, 1.2))
    if "T10Y2Y" in m:
        v, d = _last(m["T10Y2Y"])
        out.append(_sig("us_curve", "美债10Y-2Y利差", f"{v:+.2f}pct", _clip(v * 40, -50, 40),
                        "收益率曲线倒挂" if v < 0 else "收益率曲线正常", d, 0.6))
    if "NFCI" in m:
        v, d = _last(m["NFCI"])
        out.append(_sig("us_nfci", "金融条件指数NFCI", f"{v:+.2f}", _clip(-v * 80, -80, 80),
                        "金融条件宽松" if v < 0 else "金融条件收紧", d))
    return out


def dxy_signal(dxy: pd.Series | None, weight: float) -> list[dict]:
    if dxy is None:
        return []
    v, d = _last(dxy); c = (v / _ago(dxy, 91) - 1) * 100
    return [_sig("dxy", "美元指数", f"{v:.1f}", _clip(-c * 12, -70, 70), f"近3月 {c:+.1f}%，强美元收紧全球流动性", d, weight)]


def oil_signal(wti: pd.Series | None, weight: float) -> list[dict]:
    if wti is None:
        return []
    v, d = _last(wti); c = (v / _ago(wti, 91) - 1) * 100
    s = wti.dropna()
    p = float((s[s.index >= s.index[-1] - pd.DateOffset(years=3)] <= v).mean() * 100)
    if c < -25:
        sc, note = -20, "油价暴跌，反映需求走弱"
    else:
        sc = _clip(-c * 2.2, -70, 50) - max(p - 85, 0) * 2
        note = "油价上涨推升通胀、压制利润" if c > 5 else "油价回落缓解通胀压力" if c < -5 else "油价平稳"
    return [_sig("oil", "WTI原油", f"${v:.1f}｜{p:.0f}%分位", sc, f"近3月 {c:+.1f}%，{note}（分位为近3年）", d, weight)]


# ---------------- 期权 ----------------

def iv_signal(iv: pd.Series | None, name: str, note: str | None = None, weight: float = 1.5) -> list[dict]:
    if iv is None or len(iv.dropna()) < 120:
        return []
    s = iv.dropna(); v, d = _last(s)
    p = _pct_rank(s, 3); c = (v / _ago(s, 30) - 1) * 100
    sc = 0.6 * _clip((50 - p) * 1.2, -70, 70) + 0.4 * _clip(-c, -60, 60)
    if p > 95:
        sc += 35
    state = "恐慌极值，常见反弹窗口" if p > 95 else "隐含波动偏高，避险情绪浓" if p > 75 else "隐含波动偏低，市场平静" if p < 25 else "隐含波动正常"
    return [_sig("iv", name, f"{v:.1f}｜{p:.0f}%分位", sc,
                 (note + "；" if note else "") + f"近1月 {c:+.0f}%，{state}（分位为近3年）", d, weight)]


def term_signal(vix: pd.Series | None, vix3m: pd.Series | None) -> list[dict]:
    if vix is None or vix3m is None:
        return []
    df = pd.concat([vix, vix3m], axis=1, keys=["a", "b"]).dropna()
    ratio = df["a"] / df["b"]
    v, d = _last(ratio)
    return [_sig("term", "VIX期限结构", f"{v:.2f}", _clip((0.95 - v) * 300, -80, 50),
                 "VIX/VIX3M，" + ("倒挂：近端恐慌高于远端，短期避险强烈" if v > 1 else "正向结构：市场预期平稳" if v < 0.9 else "接近平坦，警惕情绪转弱"), d)]


def skew_signal(skew: pd.Series | None) -> list[dict]:
    if skew is None:
        return []
    v, d = _last(skew)
    return [_sig("skew", "SKEW尾部风险", f"{v:.0f}", _clip((140 - v) * 2, -40, 40),
                 "衡量深度虚值认沽需求，" + ("尾部对冲需求旺盛" if v > 145 else "尾部风险定价正常"), d, 0.5)]


def pcr_signal(pcr: pd.Series | None, name: str, note: str) -> list[dict]:
    """认沽/认购比：反向指标，过高代表恐慌、过低代表过度乐观。"""
    if pcr is None or len(pcr.dropna()) < 20:
        return []
    s = pcr.dropna().rolling(5, min_periods=3).mean().dropna()
    v, d = _last(s)
    if _stale_months(d) > 0.4:
        return []
    hist = s[s.index >= s.index[-1] - pd.DateOffset(years=1)]
    p = float((hist <= v).mean() * 100)
    return [_sig("pcr", name, f"{v:.2f}｜{p:.0f}%分位", _clip((p - 50) * 1.1, -55, 55),
                 f"{note}，5日均值在近一年（样本{len(hist)}日）的分位；" +
                 ("偏高：避险过度，逆向偏多" if p > 70 else "偏低：看涨情绪过热，逆向偏空" if p < 30 else "正常"), d)]


def cn_pcr_series(df: pd.DataFrame | None, codes: list[str]) -> pd.Series | None:
    if df is None:
        return None
    df = df.set_index("date")
    puts = [f"{c}_put" for c in codes if f"{c}_put" in df]
    calls = [f"{c}_call" for c in codes if f"{c}_call" in df]
    if not puts or not calls:
        return None
    return df[puts].sum(axis=1, min_count=len(puts)) / df[calls].sum(axis=1, min_count=len(calls)).replace(0, np.nan)


# ---------------- 情绪 ----------------

def vix_signal(vix: pd.Series | None, weight: float = 1.0) -> list[dict]:
    if vix is None:
        return []
    v, d = _last(vix); c = (v / _ago(vix, 30) - 1) * 100
    sc = _clip((20 - v) * 5, -70, 70) * 0.7 + _clip(-c, -50, 50) * 0.3
    if v > 35:
        sc += 30
    return [_sig("vix", "VIX恐慌指数", f"{v:.1f}", sc,
                 f"近1月 {c:+.0f}%，" + ("极度恐慌，常见反弹窗口" if v > 35 else "恐慌偏高" if v > 25 else "情绪平稳" if v > 15 else "情绪乐观"), d, weight)]


def hy_signal(hy: pd.Series | None) -> list[dict]:
    if hy is None:
        return []
    v, d = _last(hy); c = (v - _ago(hy, 30)) * 100
    sc = _clip((4.5 - v) * 15, -60, 50) * 0.5 + _clip(-c * 0.8, -60, 60) * 0.5
    return [_sig("hy", "高收益债利差", f"{v:.2f}%", sc, f"近1月 {c:+.0f}bp，衡量信用风险偏好", d, 1.2)]


def margin_signal(mg: pd.Series | None) -> list[dict]:
    if mg is None:
        return []
    v, d = _last(mg); c = (v / _ago(mg, 28) - 1) * 100
    return [_sig("margin", "两市融资余额", f"{v / 1e12:.2f}万亿", _clip(c * 15, -80, 80),
                 f"近4周 {c:+.1f}%，杠杆资金{'流入' if c >= 0 else '流出'}", d, 1.2)]


def turnover_signal(px: pd.DataFrame) -> list[dict]:
    vol = px.set_index("date")["volume"].astype(float)
    vol = vol.where(vol > 0).dropna()
    if len(vol) < 300:
        return []
    avg = vol.rolling(20).mean()
    pct = float((avg.iloc[-250:] <= avg.iloc[-1]).mean() * 100)
    sc = (pct - 50) * 1.2 if pct <= 90 else 48 - (pct - 90) * 6
    return [_sig("turnover", "成交活跃度", f"{pct:.0f}%分位", sc,
                 "近20日均量在近一年的分位，" + ("过热，警惕回调" if pct > 90 else "交投活跃" if pct > 60 else "交投清淡" if pct < 30 else "正常"), vol.index[-1])]


# ---------------- 估值 ----------------

def _pct_rank(s: pd.Series, years: int = 10) -> float:
    s = s.dropna()
    s = s[s.index >= s.index[-1] - pd.DateOffset(years=years)]
    return float((s <= s.iloc[-1]).mean() * 100)


def valuation_signals(val: dict | None, rf: pd.Series | None, px: pd.DataFrame, note: str | None) -> list[dict]:
    out = []
    close = px.set_index("date")["close"]
    if val and val.get("pe") is not None and len(val["pe"].dropna()):
        pe = val["pe"].dropna()
        v, d = _last(pe)
        if len(pe) > 24:
            p = _pct_rank(pe)
            out.append(_sig("pe_pct", "市盈率历史分位", f"PE {v:.1f}｜{p:.0f}%", (50 - p) * 1.6,
                            (note + "；" if note else "") + "近10年分位，越低越便宜", d, 1.2))
        if rf is not None:
            rf_d = rf.dropna()
            erp_now = 100 / v - float(rf_d.iloc[-1])
            if len(pe) > 24:
                erp = (100 / pe - rf_d.reindex(pe.index, method="ffill")).dropna()
                p = _pct_rank(erp)
                out.append(_sig("erp", "股债性价比", f"{erp_now:+.2f}pct｜{p:.0f}%", (p - 50) * 1.4,
                                "盈利收益率减10年国债收益率，分位越高股票越有吸引力", d))
            else:
                out.append(_sig("erp", "股债性价比", f"{erp_now:+.2f}pct", _clip((erp_now - 1.0) * 30, -70, 70),
                                f"ETF市盈率 {v:.1f} 倒数减10年美债收益率，<0 说明股票相对债券偏贵", d))
    if val and val.get("pb") is not None and len(val["pb"].dropna()) > 24:
        pb = val["pb"].dropna(); v, d = _last(pb); p = _pct_rank(pb)
        out.append(_sig("pb_pct", "市净率历史分位", f"PB {v:.2f}｜{p:.0f}%", (50 - p) * 1.4, "近10年分位", d, 0.8))
    if len(close) > 1300:
        dev = np.log(close / close.rolling(750).mean()).dropna()
        p = _pct_rank(dev, 15)
        out.append(_sig("price_pct", "价格偏离3年均值分位", f"{p:.0f}%", (50 - p) * 0.8,
                        "价格相对3年均线的偏离在近15年中的分位，偏高意味着透支", close.index[-1], 0.6))
    return out
