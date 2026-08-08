# -*- coding: utf-8 -*-
"""
vibe_factor_score.py — A股研究台 引擎1：Vibe-Trading Alpha 因子评分
==================================================================
CLI 说明（已探明）：`vibe-trading alpha` 子命令只有 list/show/bench/compare/export-manifest，
`alpha bench` 是整市场回测(csi300/sp500/btc-usdt)，**不能对单股评分**。
因此本脚本直接调用 Alpha Zoo 因子库：每个因子模块提供 `compute(panel: dict) -> DataFrame`，
对单股 OHLCV 面板计算因子值 → 历史百分位 → 综合分 + Top3 强信号因子。

用法:
    python vibe_factor_score.py 600519 [因子数]      # 默认取 alpha101 前20 + academic 6
激活环境: 内部自动注入 venv_vibe + Vibe-Trading/agent + _libs 到 sys.path
输出: data/vibe_factor_<code>.json + 控制台（综合分 / Top3因子）
"""
import os, sys, json, importlib, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
VT = os.path.join(ROOT, "Vibe-Trading")
for p in (os.path.join(ROOT, "_libs"), os.path.join(VT, "venv_vibe"),
          os.path.join(VT, "agent"), BASE):
    if p not in sys.path:
        sys.path.insert(0, p)

from fetch_data import kline_sina  # noqa: E402

# 因子清单（alpha101 全量 + academic 全量；横截面型因子在单股上会失败并跳过，能算的即时间序列型）
FACTOR_LIST = ([("alpha101", "alpha_%03d" % i) for i in range(1, 102)] +
               [("academic", m) for m in ["carhart_mom", "hml", "smb", "rmw", "cma", "mkt_rf"]])


def _desc(mod):
    """取因子描述：docstring 首行 + METADATA.notes"""
    d = (mod.__doc__ or "").strip().split("\n")[0][:60]
    meta = getattr(mod, "METADATA", {}) or {}
    notes = str(meta.get("notes", "") or "")[:40]
    return (d + ("｜" + notes if notes else "")).strip()


def score(code, days=300, max_factors=120):
    k = kline_sina(code, days)
    if not k:
        return {"code": code, "available": False, "reason": "新浪K线不可用"}
    import pandas as pd
    import numpy as np
    # 运行时补丁：修复 pandas3 下 src.factors.base._as_float 对 Series 的 dtypes.eq 兼容 bug
    try:
        import src.factors.base as _fbase
        def _as_float_patch(df):
            try:
                dt = df.dtypes
                if hasattr(dt, "eq"):
                    return df if bool(dt.eq(np.float64).all()) else df.astype(np.float64)
                return df if dt == np.float64 else df.astype(np.float64)
            except Exception:
                try:
                    return df.astype(np.float64)
                except Exception:
                    return df
        _fbase._as_float = _as_float_patch
    except Exception:
        pass
    df = pd.DataFrame(k)
    df.index = pd.to_datetime(df["date"])
    close = df["close"].astype(float)
    panel = {c: df[c].astype(float) for c in ("open", "close", "high", "low", "volume")}
    panel["amount"] = df["volume"].astype(float) * close          # 成交额≈量×价
    panel["vwap"] = (df["high"].astype(float) + df["low"].astype(float) + close) / 3.0  # 近似VWAP

    results = []
    errors = 0
    for family, mod_name in FACTOR_LIST[:max_factors]:
        try:
            mod = importlib.import_module("src.factors.zoo.%s.%s" % (family, mod_name))
            fn = getattr(mod, "compute", None)
            if fn is None:
                continue
            out = fn(panel)
            if isinstance(out, pd.DataFrame):
                s = out.iloc[:, -1]
            else:
                s = out
            s = pd.Series(s).dropna()
            if len(s) < 30:
                continue
            last = float(s.iloc[-1])
            pct = float(s.rank(pct=True).iloc[-1])  # 历史百分位 0-1
            strength = abs(pct - 0.5) * 200         # 0-100 信号强度
            results.append({"id": "%s_%s" % (family, mod_name.split("_")[-1] if family != "alpha101" else mod_name.replace("alpha_", "")),
                            "family": family, "desc": _desc(mod),
                            "value": round(last, 4), "percentile": round(pct * 100, 1),
                            "strength": round(strength, 1),
                            "direction": "强多" if pct >= 0.75 else ("偏多" if pct >= 0.55 else (
                                          "强空" if pct <= 0.25 else ("偏空" if pct <= 0.45 else "中性")))})
        except Exception as e:
            errors += 1
    if not results:
        return {"code": code, "available": False, "reason": "因子计算全部失败", "errors": errors}

    results.sort(key=lambda x: -x["strength"])
    top3 = results[:3]
    composite = round(sum(x["percentile"] for x in results) / len(results), 1)  # 平均百分位(50=中性)
    direction = "偏多" if composite > 55 else ("偏空" if composite < 45 else "中性")
    return {"code": code, "freq": "日线", "bars": len(k), "available": True,
            "composite_score": composite, "direction": direction,
            "factors_computed": len(results), "factors_errors": errors,
            "top3": top3, "all": results,
            "note": "因子值=最新日因子值；percentile=该因子在近%s日的历史百分位；composite=全部因子平均百分位(50中性,>55偏多,<45偏空)" % days}


def main():
    args = sys.argv[1:]
    code = args[0] if args else "600519"
    days = int(args[1]) if len(args) > 1 else 300
    r = score(code, days)
    out = os.path.join(ROOT, "data", "vibe_factor_%s.json" % code)
    json.dump(r, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    if not r.get("available"):
        print("因子评分失败:", r.get("reason"))
        return
    print("Vibe-Trading 因子评分 %s（%d根日线，计算%d个因子）" % (code, r["bars"], r["factors_computed"]))
    print("  综合因子分: %.1f（0-100，50中性）| 整体方向: %s" % (r["composite_score"], r["direction"]))
    print("  Top3 强信号因子:")
    for t in r["top3"]:
        print("    - %s %s | 值=%s | 百分位=%s%% | %s | %s" % (t["id"], t["direction"], t["value"], t["percentile"], t["desc"], "强度%.0f" % t["strength"]))
    print("已保存: %s" % out)


if __name__ == "__main__":
    main()
