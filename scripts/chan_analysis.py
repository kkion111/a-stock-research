# -*- coding: utf-8 -*-
"""
chan_analysis.py — A股研究台 缠论（czsc）技术分析模块
==================================================
基于 waditu/czsc（0.10.12）对个股日线K线做缠论结构分析：
  · 分型 / 笔（czsc CZSC 原生）
  · 中枢 ZG/ZD（自实现笔级别中枢：>=3笔重叠区间）
  · 买卖点信号（czsc 内置：一买/一卖/二买卖/三买卖/双中枢/MACD背驰）
  · 线段：czsc 0.10.x 未直接公开线段接口，以「笔+中枢」级别替代（已标注）

用法:
    python chan_analysis.py 600519 [days]
依赖: czsc, a-stock-data K线(get_kline, 主mootdx/备新浪)
输出: data/chan_<code>.json  + 控制台摘要（笔数量/中枢数量/最新信号）
"""
import os, sys, json, datetime, logging

logging.disable(logging.INFO)
BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
for p in (os.path.join(ROOT, "_libs"), os.path.join(ROOT, "agent-reach")):
    if p not in sys.path:
        sys.path.insert(0, p)
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from fetch_data import get_kline, kline_sina  # noqa: E402
from czsc import CZSC, RawBar, Freq  # noqa: E402


def _kline(code, days):
    """取K线：优先新浪（快，无 mootdx 探针等待），失败回退 get_kline。"""
    rows = kline_sina(code, days)
    if rows:
        return {"source": "sina", "available": True, "data": rows}
    return get_kline(code, days)


def bi_hl(b):
    """笔的高低点：优先 b.high/b.low，否则从 fx 推算。"""
    hi, lo = getattr(b, "high", None), getattr(b, "low", None)
    if hi is None or lo is None:
        pts = []
        for fx in (getattr(b, "fx_a", None), getattr(b, "fx_b", None)):
            if fx is not None:
                v = getattr(fx, "value", None)
                if v is None and hasattr(fx, "elements") and fx.elements:
                    v = getattr(fx.elements[-1], "close", None)
                if v is not None:
                    pts.append(float(v))
        if pts:
            hi, lo = max(pts), min(pts)
    return hi, lo


def calc_zs(bi_list):
    """笔级别中枢：>=3 笔的重叠区间，返回 [{zg, zd, bi_range, bi_count}]。"""
    zs, i, n = [], 0, len(bi_list)
    while i <= n - 3:
        seg = bi_list[i:i + 3]
        zz = max(bi_hl(b)[1] for b in seg)
        zg = min(bi_hl(b)[0] for b in seg)
        if zz < zg:
            j = i + 3
            while j < n:
                seg2 = bi_list[i:j + 1]
                zz2 = max(bi_hl(b)[1] for b in seg2)
                zg2 = min(bi_hl(b)[0] for b in seg2)
                if zz2 < zg2 and (bi_hl(seg2[-1])[0] > zg or bi_hl(seg2[-1])[1] < zz):
                    j += 1
                    zz, zg = zz2, zg2
                else:
                    break
            zs.append({"zg": round(zg, 2), "zd": round(zz, 2),
                       "bi_range": "%d-%d" % (i + 1, j), "bi_count": j - i})
            i = j
        else:
            i += 1
    return zs


# 缠论信号函数清单（czsc 内置；参数模板 {freq}_D{di}B_xxx）
SIGNAL_FNS = [
    ("一买", "cxt_first_buy_V221126"),
    ("一卖", "cxt_first_sell_V221126"),
    ("二买卖", "cxt_second_bs_V230320"),
    ("三买卖", "cxt_third_bs_V230319"),
    ("双中枢", "cxt_double_zs_V230311"),
    ("MACD一买卖(背驰)", "tas_macd_first_bs_V221201"),
    ("MACD二买卖(背驰)", "tas_macd_second_bs_V221201"),
]
_HIT_WORDS = ["满足", "出现", "一买", "一卖", "二买", "二卖", "三买", "三卖", "背驰"]


def run_signals(c):
    import czsc.signals as sig
    out, bs_points = {}, []
    for label, fn_name in SIGNAL_FNS:
        fn = getattr(sig, fn_name, None)
        if fn is None:
            continue
        try:
            r = fn(c)
            hit = {k: v for k, v in r.items() if any(w in v for w in _HIT_WORDS)}
            if hit:
                out[label] = hit
                for v in hit.values():
                    for w in ["一买", "二买", "三买", "一卖", "二卖", "三卖"]:
                        if w in v:
                            bs_points.append(w)
        except Exception as e:
            out[label] = {"error": "%s: %s" % (type(e).__name__, str(e)[:60])}
    return out, sorted(set(bs_points))


def analyze(code, days=120):
    res = _kline(code, days)
    if not res.get("available") or not res.get("data"):
        return {"code": code, "available": False, "reason": res.get("reason", "K线不可用")}
    k = res["data"]
    bars = [RawBar(symbol=code, id=i,
                   dt=datetime.datetime.strptime(x["date"], "%Y-%m-%d"),
                   freq=Freq.D, open=float(x["open"]), close=float(x["close"]),
                   high=float(x["high"]), low=float(x["low"]),
                   vol=float(x.get("volume") or 0), amount=float(x.get("amount") or 0))
            for i, x in enumerate(k)]
    c = CZSC(bars)
    bi_list = c.bi_list
    zs = calc_zs(bi_list)
    signals, bs_points = run_signals(c)
    last = k[-1]
    return {
        "code": code, "freq": "日线", "kline_source": res.get("source"),
        "bars": len(bars), "available": True,
        "bi_count": len(bi_list),
        "fx_count": len(bi_list) * 2 if bi_list else 0,
        "seg_note": "czsc 0.10.12 未直接公开线段接口，以笔级别中枢替代",
        "zs_list": zs,
        "signals": signals,
        "buy_sell_points": bs_points,
        "latest": {"date": last["date"], "close": last["close"], "high": last["high"], "low": last["low"]},
    }


def main():
    args = sys.argv[1:]
    code = args[0] if args else "600519"
    days = int(args[1]) if len(args) > 1 else 120
    r = analyze(code, days)
    out_path = os.path.join(ROOT, "data", "chan_%s.json" % code)
    json.dump(r, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("缠论分析 %s（日线，%d 根K线）" % (code, r.get("bars", 0)))
    print("  笔数量: %d | 分型(端点)数量: %d" % (r.get("bi_count", 0), r.get("fx_count", 0)))
    print("  线段: %s" % r.get("seg_note"))
    print("  中枢数量: %d" % len(r.get("zs_list", [])))
    for z in r.get("zs_list", []):
        print("    ZG %.2f / ZD %.2f（第%s笔，%d笔构成）" % (z["zg"], z["zd"], z["bi_range"], z["bi_count"]))
    sigs = r.get("signals", {})
    hits = {k: v for k, v in sigs.items() if "error" not in v}
    print("  买卖点信号: %s" % (r.get("buy_sell_points") or "无（当前无明确买/卖点）"))
    if hits:
        for k, v in hits.items():
            print("    [%s] %s" % (k, json.dumps(v, ensure_ascii=False)[:120]))
    elif sigs:
        print("  信号: 均未触发（%d 类信号检测无异常）" % len(sigs))
    print("  最新: %s 收 %.2f" % (r.get("latest", {}).get("date"), r.get("latest", {}).get("close")))
    print("已保存: %s" % out_path)


if __name__ == "__main__":
    main()
