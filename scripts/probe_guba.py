import sys, os, json, time, random
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "_libs"))
import requests
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

def probe(url, headers, label):
    try:
        r = requests.get(url, headers=headers, timeout=15)
        print(f"[{label}] status={r.status_code} len={len(r.text)}")
        print("   head:", r.text[:260].replace("\n", " "))
    except Exception as e:
        print(f"[{label}] ERR {type(e).__name__}: {str(e)[:100]}")
    time.sleep(1.2)

code = "600519"
# --- Candidate Guba (股吧) endpoints ---
probe(f"https://guba.eastmoney.com/api/command/{code}/fucus?pageNo=1&pageSize=5&type=0",
      {"User-Agent": UA, "Referer": "https://guba.eastmoney.com/"}, "guba_focus")
probe(f"https://guba.eastmoney.com/api/command/{code}/fucus?pageNo=1&pageSize=5",
      {"User-Agent": UA, "Referer": "https://guba.eastmoney.com/"}, "guba_focus2")
probe(f"https://guba.eastmoney.com/api/command/{code}/newlist?pageNo=1&pageSize=5",
      {"User-Agent": UA, "Referer": "https://guba.eastmoney.com/"}, "guba_newlist")

# --- Dragon-Tiger (datacenter) ---
DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"
trade_date = "2026-08-08"; start = "2026-07-09"
params = {
    "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW", "columns": "ALL",
    "filter": f"(TRADE_DATE>='{start}')(TRADE_DATE<='{trade_date}')(SECURITY_CODE=\"{code}\")",
    "pageNumber": "1", "pageSize": "50", "sortColumns": "TRADE_DATE", "sortTypes": "-1",
    "source": "WEB", "client": "WEB",
}
try:
    r = requests.get(DC, params=params, headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/"}, timeout=15)
    print(f"[dragon_tiger] status={r.status_code} len={len(r.text)}")
    print("   head:", r.text[:400].replace("\n", " "))
except Exception as e:
    print(f"[dragon_tiger] ERR {type(e).__name__}: {str(e)[:100]}")
