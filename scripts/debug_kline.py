import sys, json, urllib.request, urllib.parse
UA = "Mozilla/5.0"
url = "https://finance.pae.baidu.com/selfselect/getstockquotation"
params = {"all":"1","isIndex":"false","isBk":"false","isBlock":"false","isFutures":"false","isStock":"true","newFormat":"1","group":"quotation_kline_ab","finClientType":"pc","code":"600519","start_time":"","ktype":"1"}
headers = {"User-Agent":UA,"Accept":"application/vnd.finance-web.v1+json","Origin":"https://gushitong.baidu.com","Referer":"https://gushitong.baidu.com/"}
req = urllib.request.Request(url+"?"+urllib.parse.urlencode(params), headers=headers)
raw = urllib.request.urlopen(req, timeout=12).read().decode("utf-8","ignore")
d = json.loads(raw)
print("top keys:", list(d.keys()))
R = d.get("Result")
print("Result type:", type(R).__name__)
if isinstance(R, list):
    print("Result len:", len(R))
    for i, item in enumerate(R[:2]):
        print(f"  Result[{i}] type={type(item).__name__}", list(item.keys()) if isinstance(item,dict) else item)
        if isinstance(item, dict):
            nm = item.get("newMarketData")
            print("    newMarketData type:", type(nm).__name__, list(nm.keys())[:8] if isinstance(nm,dict) else nm)
            if isinstance(nm, dict):
                md = nm.get("marketData") or ""
                print("    marketData sample:", md[:120])
                print("    keys:", nm.get("keys",[])[:12])
elif isinstance(R, dict):
    print("Result keys:", list(R.keys())[:12])
    nm = R.get("newMarketData")
    print("newMarketData type:", type(nm).__name__)
    if isinstance(nm, dict):
        print("marketData sample:", (nm.get("marketData") or "")[:120])
        print("keys:", nm.get("keys",[])[:12])
