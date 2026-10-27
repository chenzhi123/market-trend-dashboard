"""技术指标与技术面信号（全部向量化，便于计算历史得分并回测）。"""
import numpy as np
import pandas as pd


def _tanh_score(x: pd.Series, scale: float = 1.0) -> pd.Series:
    return 100 * np.tanh(x / scale)


def indicators(px: pd.DataFrame) -> pd.DataFrame:
    df = px.copy().set_index("date")
    c, h, l = df["close"], df["high"], df["low"]
    for n in (20, 60, 120, 250):
        df[f"ma{n}"] = c.rolling(n).mean()
    df["sigma"] = c.pct_change().rolling(60).std()

    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    df["dif"] = ema12 - ema26
    df["dea"] = df["dif"].ewm(span=9, adjust=False).mean()
    df["macd"] = 2 * (df["dif"] - df["dea"])

    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

    mid, std = c.rolling(20).mean(), c.rolling(20).std()
    df["boll_up"], df["boll_mid"], df["boll_dn"] = mid + 2 * std, mid, mid - 2 * std
    df["boll_pb"] = (c - df["boll_dn"]) / (df["boll_up"] - df["boll_dn"])

    up, dn = h.diff(), -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df["di_plus"] = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / 14, adjust=False).mean() / atr
    df["di_minus"] = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / 14, adjust=False).mean() / atr
    dx = 100 * (df["di_plus"] - df["di_minus"]).abs() / (df["di_plus"] + df["di_minus"]).replace(0, np.nan)
    df["adx"] = dx.ewm(alpha=1 / 14, adjust=False).mean()

    vol = df["volume"].where(df["volume"] > 0)
    df["vol_ratio"] = vol.rolling(10).mean() / vol.rolling(60).mean()
    return df


SIGNAL_NAMES = {
    "ma20": "20日均线", "ma60": "60日均线", "ma120": "120日均线", "ma250": "250日均线（年线）",
    "align": "均线排列", "macd": "MACD", "rsi": "RSI(14)", "boll": "布林带位置",
    "volume": "量价配合", "mom20": "20日动量", "mom60": "60日动量", "mom120": "120日动量", "adx": "趋势强度ADX",
}


def signal_series(df: pd.DataFrame) -> pd.DataFrame:
    """每个技术信号的逐日得分（-100~100）。"""
    c, sig = df["close"], df["sigma"]
    s = pd.DataFrame(index=df.index)

    for n in (20, 60, 120, 250):
        ma = df[f"ma{n}"]
        dev = (c / ma - 1) / (sig * np.sqrt(n / 2))
        k = max(n // 4, 5)
        slope = ma.pct_change(k) / (sig * np.sqrt(k))
        s[f"ma{n}"] = 0.5 * _tanh_score(dev) + 0.5 * _tanh_score(slope)

    mas = [df["ma20"], df["ma60"], df["ma120"], df["ma250"]]
    pairs = [(i, j) for i in range(4) for j in range(i + 1, 4)]
    s["align"] = sum(np.sign(mas[i] - mas[j]) for i, j in pairs) / len(pairs) * 100

    norm = c * sig
    s["macd"] = 0.5 * _tanh_score(df["dif"] / (3 * norm)) + 0.5 * _tanh_score(df["macd"] / norm)

    rsi = df["rsi"]
    base = ((rsi - 50) * 2.5).clip(-80, 80)
    base = base - ((rsi - 75).clip(lower=0) * 6) + ((25 - rsi).clip(lower=0) * 6)
    s["rsi"] = base.clip(-100, 100)

    pb = df["boll_pb"]
    s["boll"] = ((pb - 0.5) * 160).clip(-80, 80) - ((pb - 1.1).clip(lower=0) * 200)

    ret10 = c.pct_change(10) / (sig * np.sqrt(10))
    vr = df["vol_ratio"].clip(0.5, 1.6) / 1.6
    s["volume"] = _tanh_score(ret10) * vr

    for n in (20, 60, 120):
        s[f"mom{n}"] = _tanh_score(c.pct_change(n) / (sig * np.sqrt(n)), 1.5)

    s["adx"] = np.sign(df["di_plus"] - df["di_minus"]) * (df["adx"].clip(upper=50) / 50 * 100)
    return s.clip(-100, 100)


def describe(key: str, row: pd.Series) -> tuple[str, str]:
    """返回 (数值展示, 解读)"""
    c = row["close"]
    if key.startswith("ma") and key[2:].isdigit():
        ma = row[key]
        pct = (c / ma - 1) * 100
        return f"{ma:,.0f}", f"收盘{'高于' if pct >= 0 else '低于'}均线 {abs(pct):.1f}%"
    if key == "align":
        order = [n for n in (20, 60, 120, 250)]
        vals = [row[f"ma{n}"] for n in order]
        if vals == sorted(vals, reverse=True):
            return "多头排列", "短期均线全部在长期均线上方"
        if vals == sorted(vals):
            return "空头排列", "短期均线全部在长期均线下方"
        return "交织", "均线方向不一致"
    if key == "macd":
        state = "金叉" if row["dif"] > row["dea"] else "死叉"
        zone = "零轴上方" if row["dif"] > 0 else "零轴下方"
        return f"{row['macd']:+.1f}", f"{zone}{state}"
    if key == "rsi":
        r = row["rsi"]
        note = "超买" if r > 70 else "超卖" if r < 30 else "偏强" if r > 55 else "偏弱" if r < 45 else "中性"
        return f"{r:.1f}", note
    if key == "boll":
        pb = row["boll_pb"]
        return f"{pb * 100:.0f}%", "位于上轨附近" if pb > 0.8 else "位于下轨附近" if pb < 0.2 else "位于中轨附近"
    if key == "volume":
        vr = row["vol_ratio"]
        return ("-" if pd.isna(vr) else f"{vr:.2f}x"), "近10日成交量 / 近60日均量"
    if key.startswith("mom"):
        return "", ""
    if key == "adx":
        return f"{row['adx']:.0f}", ("趋势明显" if row["adx"] > 25 else "震荡市") + ("，多方主导" if row["di_plus"] > row["di_minus"] else "，空方主导")
    return "", ""
