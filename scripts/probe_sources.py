import sys, socket, time, json, re
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent-reach"))

TDX = ('119.97.185.59', 7709)
t0 = time.time()
try:
    with socket.create_connection(TDX, timeout=3):
        print("TDX TCP probe: REACHABLE in %.1fs" % (time.time() - t0))
        TDX_OK = True
except Exception as e:
    print("TDX TCP probe: UNREACHABLE ->", type(e).__name__, str(e)[:60])
    TDX_OK = False

import urllib.request
def tquote(codes):
    prefixed = [("sh" if c.startswith(("5", "6", "9")) else "sz") + c for c in codes]
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10).read().decode("gbk")

print("\ntencent quote:", tquote(["600519"])[:90].replace("\n", " "))

UA = "Mozilla/5.0"
import requests
EM_SESSION = requests.Session(); EM_SESSION.headers.update({"User-Agent": UA})
_last = [0.0]
def em_get(url, params=None, headers=None, timeout=15):
    wait = 1.0 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout)
    finally:
        _last[0] = time.time()

print("\n-- 东财 资金流120d (600519) --")
try:
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    p = {"secid": "1.600519", "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56,f57", "lmt": "120"}
    r = em_get(url, params=p, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"})
    d = r.json(); kls = d.get("data", {}).get("klines", [])
    print("fund_flow rows:", len(kls), "| last:", kls[-1] if kls else None)
except Exception as e:
    print("fund_flow FAIL:", type(e).__name__, str(e)[:120])

print("\n-- 东财 个股新闻 (600519) --")
try:
    cb = "jQuery_news"
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    inner = json.dumps({"uid": "", "keyword": "600519", "type": ["cmsArticleWebOld"], "client": "web",
                        "clientType": "web", "clientVersion": "curr",
                        "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                                                       "pageIndex": 1, "pageSize": 5, "preTag": "", "postTag": ""}}},
                       separators=(',', ':'))
    r = em_get(url, params={"cb": cb, "param": inner}, headers={"User-Agent": UA, "Referer": "https://so.eastmoney.com/"})
    txt = r.text; js = txt[txt.index("(") + 1: txt.rindex(")")]; dd = json.loads(js)
    arts = dd.get("result", {}).get("cmsArticleWebOld", [])
    print("news count:", len(arts))
    for a in arts[:3]:
        print("  -", a.get("date", ""), "|", re.sub(r'<[^>]+>', '', a.get("title", "")), "|", a.get("mediaName", ""))
except Exception as e:
    print("news FAIL:", type(e).__name__, str(e)[:120])

if TDX_OK:
    print("\n-- mootdx bars + finance (600519) --")
    try:
        from mootdx.quotes import Quotes
        c = Quotes.factory(market='std', server=TDX)
        df = c.bars(symbol='600519', frequency=9, offset=5)
        print("bars rows:", len(df), "cols:", list(df.columns)[:6])
        fin = c.finance(symbol='sh600519')
        row = fin.iloc[0].to_dict() if hasattr(fin, 'iloc') else {}
        print("finance keys:", list(row.keys())[:20])
        for k in ("eps", "roe", "profit", "income", "bvps", "zongguben"):
            if k in row:
                print("   ", k, "=", row[k])
    except Exception as e:
        print("mootdx FAIL:", type(e).__name__, str(e)[:150])
else:
    print("\nmootdx skipped (TCP unreachable)")
