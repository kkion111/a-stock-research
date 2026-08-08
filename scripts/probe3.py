import sys, time, json
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

def fund_120d(code):
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    p = {"secid": ("1." if code.startswith("6") else "0.") + code,
         "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56,f57", "lmt": "120"}
    r = em_get(url, params=p, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"})
    d = r.json(); kls = d.get("data", {}).get("klines", [])
    return kls

for attempt in range(4):
    try:
        kls = fund_120d("600519")
        print(f"attempt {attempt+1}: fund_flow_120d rows={len(kls)} last={kls[-1] if kls else None}", flush=True)
        if kls:
            break
    except Exception as e:
        print(f"attempt {attempt+1} FAIL: {type(e).__name__} {str(e)[:90]}", flush=True)
        time.sleep(4)

# alternate: push2 minute fund flow
try:
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    p = {"secid": "1.600519", "klt": 1, "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56,f57"}
    r = em_get(url, params=p, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"})
    d = r.json(); kls = d.get("data", {}).get("klines", [])
    print("push2 minute rows:", len(kls), "last:", kls[-1] if kls else None, flush=True)
except Exception as e:
    print("push2 minute FAIL:", type(e).__name__, str(e)[:90], flush=True)
