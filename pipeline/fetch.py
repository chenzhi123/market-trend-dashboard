"""数据抓取层。每个数据源抓取成功后写入 data/cache，失败时回退到缓存并标记为过期。"""
import io
import os
import re
import time
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

STATUS: list[dict] = []


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name)


def cached(name: str, label: str, fn, retries: int = 2) -> pd.DataFrame | None:
    """调用 fn 获取 DataFrame（需含 date 列）。失败则读取缓存。"""
    path = CACHE / f"{_safe_name(name)}.csv"
    err = None
    for attempt in range(retries + 1):
        try:
            df = fn()
            if df is None or len(df) == 0:
                raise ValueError("返回空数据")
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
            df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last")
            df.to_csv(path, index=False)
            STATUS.append({"name": label, "ok": True, "asof": df["date"].iloc[-1].strftime("%Y-%m-%d")})
            return df.reset_index(drop=True)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:120]}"
            time.sleep(1.5 * (attempt + 1))
    if path.exists():
        df = pd.read_csv(path, parse_dates=["date"])
        STATUS.append({"name": label, "ok": False, "stale": True, "error": err,
                       "asof": df["date"].iloc[-1].strftime("%Y-%m-%d")})
        return df
    STATUS.append({"name": label, "ok": False, "error": err})
    return None


# ---------------- 行情 ----------------

def _sina_daily(symbol: str) -> pd.DataFrame:
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol=symbol)
    return df[["date", "open", "high", "low", "close", "volume"]]


def _yf_daily(symbol: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.Ticker(symbol).history(period="20y", auto_adjust=False)
    df = df.reset_index().rename(columns={"Date": "date", "Open": "open", "High": "high",
                                          "Low": "low", "Close": "close", "Volume": "volume"})
    return df[["date", "open", "high", "low", "close", "volume"]].dropna(subset=["close"])


def price(source: str, symbol: str, label: str) -> pd.DataFrame | None:
    fn = {"sina": _sina_daily, "yf": _yf_daily}[source]
    return cached(f"px_{symbol}", f"行情·{label}", lambda: fn(symbol))


def yf_close(symbol: str, label: str) -> pd.Series | None:
    df = cached(f"px_{symbol}", label, lambda: _yf_daily(symbol))
    return None if df is None else df.set_index("date")["close"].astype(float)


# ---------------- 中国宏观 ----------------

def _cn_month(s: pd.Series) -> pd.Series:
    """'2026年09月份' / '202609' -> 月末日期"""
    digits = s.astype(str).str.replace(r"\D", "", regex=True).str[:6]
    return pd.to_datetime(digits, format="%Y%m") + pd.offsets.MonthEnd(0)


def _ak_monthly(func_name: str, col: str):
    def run():
        import akshare as ak
        df = getattr(ak, func_name)()
        return pd.DataFrame({"date": _cn_month(df["月份"]), "value": pd.to_numeric(df[col], errors="coerce")}).dropna()
    return run


def cn_macro() -> dict[str, pd.Series]:
    import akshare as ak
    specs = {
        "cn_pmi": ("中国制造业PMI", "macro_china_pmi", "制造业-指数"),
        "cn_cpi": ("中国CPI同比", "macro_china_cpi", "全国-同比增长"),
        "cn_ppi": ("中国PPI同比", "macro_china_ppi", "当月同比增长"),
        "cn_m1": ("中国M1同比", "macro_china_money_supply", "货币(M1)-同比增长"),
        "cn_m2": ("中国M2同比", "macro_china_money_supply", "货币和准货币(M2)-同比增长"),
        "cn_tsf": ("中国社融增量", "macro_china_shrzgm", "社会融资规模增量"),
    }
    out = {}
    for key, (label, fn, col) in specs.items():
        df = cached(key, label, _ak_monthly(fn, col))
        if df is not None:
            out[key] = df.set_index("date")["value"].astype(float)

    def bonds():
        df = ak.bond_zh_us_rate(start_date="20100101")
        return pd.DataFrame({"date": df["日期"], "cn10y": df["中国国债收益率10年"],
                             "us10y": df["美国国债收益率10年"], "us2y": df["美国国债收益率2年"]})
    df = cached("bond_rates", "中美国债收益率", bonds)
    if df is not None:
        df = df.set_index("date").astype(float).ffill()
        out["cn10y"], out["us10y_cn_src"] = df["cn10y"], df["us10y"]

    def margin():
        sh = ak.macro_china_market_margin_sh()[["日期", "融资余额"]].rename(columns={"日期": "date", "融资余额": "sh"})
        sz = ak.macro_china_market_margin_sz()[["日期", "融资余额"]].rename(columns={"日期": "date", "融资余额": "sz"})
        for d in (sh, sz):
            d["date"] = pd.to_datetime(d["date"])
        m = sh.merge(sz, on="date", how="inner")
        m["value"] = pd.to_numeric(m["sh"]) + pd.to_numeric(m["sz"])
        return m[["date", "value"]]
    df = cached("cn_margin", "两市融资余额", margin)
    if df is not None:
        out["cn_margin"] = df.set_index("date")["value"].astype(float)
    return out


# ---------------- 美国宏观（FRED） ----------------

FRED_SERIES = {
    "DFF": "联邦基金利率", "CPIAUCSL": "美国CPI指数", "UNRATE": "美国失业率",
    "BAMLH0A0HYM2": "美国高收益债利差", "T10Y2Y": "美债10Y-2Y利差", "NFCI": "芝加哥联储金融条件指数",
    "DGS10": "10年期美债收益率",
}


def _fred(series_id: str) -> pd.DataFrame:
    key = os.environ.get("FRED_API_KEY")
    if key:
        r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                         params={"series_id": series_id, "api_key": key, "file_type": "json",
                                 "observation_start": "2005-01-01"}, timeout=30)
        r.raise_for_status()
        obs = r.json()["observations"]
        df = pd.DataFrame(obs)[["date", "value"]]
    else:
        r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}", timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = ["date", "value"]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna()
    return df[pd.to_datetime(df["date"]) >= "2005-01-01"]


def us_macro() -> dict[str, pd.Series]:
    out = {}
    for sid, label in FRED_SERIES.items():
        df = cached(f"fred_{sid}", label, lambda s=sid: _fred(s))
        if df is not None:
            out[sid] = df.set_index("date")["value"].astype(float)
    return out


# ---------------- 估值 ----------------

def valuation(cfg: dict, label: str) -> dict | None:
    import akshare as ak
    vtype, sym = cfg["type"], cfg["symbol"]
    if vtype == "lg_index":
        pe = cached(f"pe_{sym}", f"估值·{label}PE",
                    lambda: ak.stock_index_pe_lg(symbol=sym).rename(columns={"日期": "date", "滚动市盈率": "value"})[["date", "value"]])
        pb = cached(f"pb_{sym}", f"估值·{label}PB",
                    lambda: ak.stock_index_pb_lg(symbol=sym).rename(columns={"日期": "date", "市净率": "value"})[["date", "value"]])
        return {"type": vtype, "pe": None if pe is None else pe.set_index("date")["value"].astype(float),
                "pb": None if pb is None else pb.set_index("date")["value"].astype(float)}
    if vtype == "lg_market":
        def run():
            df = ak.stock_market_pe_lg(symbol=sym)
            return pd.DataFrame({"date": df.iloc[:, 0], "value": pd.to_numeric(df.iloc[:, -1], errors="coerce")}).dropna()
        pe = cached(f"mpe_{sym}", f"估值·{sym}整体PE", run)
        return {"type": vtype, "pe": None if pe is None else pe.set_index("date")["value"].astype(float), "pb": None}
    if vtype == "etf_pe":
        def run():
            import yfinance as yf
            pe = yf.Ticker(sym).info.get("trailingPE")
            if not pe:
                raise ValueError("无市盈率")
            return pd.DataFrame({"date": [pd.Timestamp(datetime.now().date())], "value": [float(pe)]})
        path = CACHE / f"etfpe_{_safe_name(sym)}.csv"
        old = pd.read_csv(path, parse_dates=["date"]) if path.exists() else None
        df = cached(f"etfpe_{sym}_today", f"估值·{sym}市盈率", run)
        if df is not None:
            hist = pd.concat([old, df]) if old is not None else df
            hist = hist.drop_duplicates("date", keep="last").sort_values("date")
            hist.to_csv(path, index=False)
            return {"type": vtype, "pe": hist.set_index("date")["value"].astype(float), "pb": None}
    return None
