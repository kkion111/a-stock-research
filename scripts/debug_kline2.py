import sys, json, urllib.request, urllib.parse
UA = "Mozilla/5.0"
def get(url, params=None, headers=None):
    req = urllib.request.Request(url + (("?" + urllib.parse.urlencode(params)) if params else ""),
                                 headers=headers or {"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=12).read().decode("utf-8", "ignore")

print("== 新浪日K (sh600519) ==")
try:
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    p = {"symbol": "sh600519", "scale": 240, "ma": "5", "datalen": 60}
    h = {"User-Agent": UA, "Referer": "https://finance.sina.com.cn/"}
    raw = get(url, p, h)
    d = json.loads(raw)
    print("  rows:", len(d), "| sample:", d[0] if d else None, "| last:", d[-1] if d else None)
except Exception as e:
    print("  新浪 FAIL:", type(e).__name__, str(e)[:120])

print("\n== 腾讯日K (sh600519, web.ifzq.gtimg.cn) ==")
try:
    url = "https://web.ifzq.gtimg.cn/appstuff/app/fqkline/get"
    p = {"param": "sh600519,day,,,60,qfq"}
    h = {"User-Agent": UA, "Referer": "https://gu.qq.com/"}
    raw = get(url, p, h)
    d = json.loads(raw)
    node = d.get("data", {}).get("sh600519", {})
    klines = node.get("qfqday") or node.get("day") or []
    print("  keys:", list(node.keys())[:8], "| klines rows:", len(klines), "| sample:", klines[-1] if klines else None)
except Exception as e:
    print("  腾讯 FAIL:", type(e).__name__, str(e)[:120])
