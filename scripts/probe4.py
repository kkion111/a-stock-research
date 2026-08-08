import sys, time, json, re, urllib.request
UA = "Mozilla/5.0"
def get(url, params=None, headers=None, timeout=12):
    req = urllib.request.Request(url + (("?" + urllib.parse.urlencode(params)) if params else ""), headers=headers or {"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read()

print("== 百度股市通 K线 (600519) ==")
try:
    import urllib.parse
    url = "https://finance.pae.baidu.com/selfselect/getstockquotation"
    p = {"all":"1","isIndex":"false","isBk":"false","isBlock":"false","isFutures":"false","isStock":"true","newFormat":"1","group":"quotation_kline_ab","finClientType":"pc","code":"600519","start_time":"","ktype":"1"}
    h = {"User-Agent":UA,"Accept":"application/vnd.finance-web.v1+json","Origin":"https://gushitong.baidu.com","Referer":"https://gushitong.baidu.com/"}
    raw = get(url, p, h)
    d = json.loads(raw)
    md = d.get("Result",{}).get("newMarketData",{})
    rows = (md.get("marketData") or "").split(";")
    print("  baidu kline keys:", md.get("keys",[])[:10])
    print("  baidu kline rows:", len([r for r in rows if r]), "| last:", rows[-1] if rows else None)
except Exception as e:
    print("  baidu kline FAIL:", type(e).__name__, str(e)[:120])

print("\n== 同花顺一致预期EPS (basic.10jqka.com.cn/600519/worth.html) ==")
try:
    import urllib.parse
    url = "https://basic.10jqka.com.cn/new/600519/worth.html"
    raw = get(url, None, {"User-Agent":UA,"Referer":"https://basic.10jqka.com.cn/"}, timeout=12)
    txt = raw.decode("gbk","ignore")
    print("  status: reachable, len", len(txt), "| has EPS:", "EPS" in txt, "| has 一致预期:", "一致预期" in txt)
except Exception as e:
    print("  10jqka FAIL:", type(e).__name__, str(e)[:120])

print("\n== 新浪财报摘要 (money.finance.sina.com.cn) ==")
try:
    import urllib.parse
    url = "https://money.finance.sina.com.cn/corp/go.php/vFD_FinanceSummary/stockid/600519/displaytype/4.phtml"
    raw = get(url, None, {"User-Agent":UA,"Referer":"https://finance.sina.com.cn/"}, timeout=12)
    txt = raw.decode("gbk","ignore")
    print("  sina summary reachable, len", len(txt), "| has 净利润:", "净利润" in txt, "| has 净资产收益率:", "净资产收益率" in txt or "ROE" in txt)
except Exception as e:
    print("  sina FAIL:", type(e).__name__, str(e)[:120])
