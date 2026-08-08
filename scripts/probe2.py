import sys, socket, time, json
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent-reach"))

# ---- tdx_client() copied verbatim from a-stock-data SKILL.md ----
_TDX_SERVERS = [
    ('119.97.185.59', 7709), ('124.70.133.119', 7709), ('116.205.183.150', 7709),
    ('123.60.73.44', 7709),  ('116.205.163.254', 7709), ('121.36.225.169', 7709),
    ('123.60.70.228', 7709), ('124.71.9.153', 7709),    ('110.41.147.114', 7709),
    ('124.71.187.122', 7709),
]
def _probe(ip, port, timeout=2.0):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False
def _validate(client, market='std'):
    if market != 'std':
        return True
    try:
        df = client.bars(symbol='000001', frequency=9, offset=1)
        return df is not None and not df.empty
    except Exception:
        return False
def tdx_client(market='std'):
    for ip, port in _TDX_SERVERS:
        if not _probe(ip, port):
            continue
        try:
            c = Quotes.factory(market=market, server=(ip, port))
            if _validate(c, market):
                print("  tdx_client picked", ip)
                return c
        except Exception:
            continue
    for kwargs in ({'bestip': True}, {}):
        try:
            c = Quotes.factory(market=market, **kwargs)
            if _validate(c, market):
                return c
        except Exception:
            continue
    raise RuntimeError("all mootdx servers unreachable")

from mootdx.quotes import Quotes
print("== mootdx via tdx_client() ==")
try:
    c = tdx_client()
    bars = c.bars(symbol='600519', frequency=9, offset=60)
    print("bars(60d) rows:", len(bars))
    print("last bar:", bars.iloc[-1].to_dict() if hasattr(bars, 'iloc') else bars)
    fin = c.finance(symbol='sh600519')
    row = fin.iloc[0].to_dict() if hasattr(fin, 'iloc') else {}
    print("finance non-zero check -> eps:", row.get('eps'), "roe:", row.get('roe'), "profit:", row.get('profit'))
except Exception as e:
    print("mootdx FAIL:", type(e).__name__, str(e)[:160])

# ---- 东财 资金流120d (retry x3) ----
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

print("\n== 东财 资金流120d (retry) ==")
for attempt in range(3):
    try:
        url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
        p = {"secid": "1.600519", "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56,f57", "lmt": "120"}
        r = em_get(url, params=p, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"})
        d = r.json(); kls = d.get("data", {}).get("klines", [])
        print(f"  attempt {attempt+1}: rows={len(kls)} last={kls[-1] if kls else None}")
        if kls:
            break
    except Exception as e:
        print(f"  attempt {attempt+1} FAIL: {type(e).__name__} {str(e)[:80]}")
        time.sleep(3)

# also try push2 minute-level (klt=1) as alt signal
print("\n== 东财 资金流 分钟级 (push2) ==")
try:
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    p = {"secid": "1.600519", "klt": 1, "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56,f57"}
    r = em_get(url, params=p, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"})
    d = r.json(); kls = d.get("data", {}).get("klines", [])
    print("  minute rows:", len(kls), "last:", kls[-1] if kls else None)
except Exception as e:
    print("  minute FAIL:", type(e).__name__, str(e)[:100])
