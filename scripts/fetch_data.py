# -*- coding: utf-8 -*-
"""
fetch_data.py — A股研究分析工作台 · 数据获取脚本
=================================================
数据来源:
  · a-stock-data  (simonlin1212/a-stock-data, V3.6.0)  — 行情/腾讯、K线/mootdx、基本面、
    资金流/东财、新闻/东财、龙虎榜(datacenter) 等方法取自其 SKILL.md（直连 HTTP/TCP，零鉴权）。
  · daily_stock_analysis (ZhuLinsen/daily_stock_analysis) — 东财「千股千评」(经 akshare
    stock_comment_em，datacenter RPT_DMSK_TS_STOCKNEW) 作个股舆情信号；新闻情绪用内置词典法。
  · Agent-Reach   (Panniantong/Agent-Reach)            — 雪球(xueqiu) 舆情模块（本次按用户要求跳过）。

设计原则:
  · 每个数据维度都「先试主源，失败再回退可达的备用源」，并保证最终一定输出
    结构完整的 report_data.json（不会出现某个字段整体缺失）。
  · 由于本脚本常在「无 GUI / 无登录态」的环境运行，雪球需要登录 Cookie、
    东财 push2 资金流对部分 IP 有风控；这些维度在不可用时会在 JSON 中标记
    available=false + reason，绝不伪造数值。

用法:
    python fetch_data.py
    python fetch_data.py 600519 000001 002594 300750 000858
依赖: requests pandas stockstats mootdx  (pip install -r requirements.txt)
"""
import os, sys, json, re, time, socket, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)                      # ~/a_stock_research
for p in (os.path.join(ROOT, "_libs"), os.path.join(ROOT, "agent-reach")):
    if p not in sys.path:
        sys.path.insert(0, p)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
STOCKS_DEFAULT = ["600519", "000001", "002594", "300750", "000858"]

# ============================================================
# 0. 通用 HTTP 助手
# ============================================================
def _http_get(url, params=None, headers=None, timeout=12, encoding="utf-8"):
    req = urllib.request.Request(
        url + (("?" + urllib.parse.urlencode(params)) if params else ""),
        headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(encoding, errors="ignore")


# ============================================================
# 1. 行情 (腾讯财经 API, a-stock-data §1.2)
# ============================================================
def tencent_quote(codes):
    """批量拉取腾讯财经实时行情。返回 {code: {...88字段子集...}}。"""
    def prefix(c):
        c = c.lower()
        if c.startswith(("sh", "sz", "bj")):
            return c
        if c.startswith(("5", "6", "9")):
            return "sh" + c
        return "sz" + c
    prefixed = [prefix(c) for c in codes]
    key_of = {p: c for p, c in zip(prefixed, codes)}
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    raw = _http_get(url, headers={"User-Agent": UA}, encoding="gbk")
    out = {}
    for line in raw.strip().split(";"):
        if "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 50:
            continue
        code = key_of.get(key, key[2:])
        out[code] = {
            "name": vals[1], "price": _f(vals[3]), "prev_close": _f(vals[4]),
            "open": _f(vals[5]), "change_pct": _f(vals[32]), "change_amt": _f(vals[31]),
            "high": _f(vals[33]), "low": _f(vals[34]), "amount_wan": _f(vals[37]),
            "turnover_pct": _f(vals[38]), "pe_ttm": _f(vals[39]), "amplitude_pct": _f(vals[43]),
            "float_mcap_yi": _f(vals[44]), "mcap_yi": _f(vals[45]), "pb": _f(vals[46]),
            "limit_up": _f(vals[47]), "limit_down": _f(vals[48]), "pe_static": _f(vals[52]),
        }
    return out


def _f(s):
    try:
        return float(s)
    except Exception:
        return 0.0


# ============================================================
# 2. K线 (主源 mootdx §1.1；回退 百度股市通 §1.3)
# ============================================================
_TDX_SERVERS = [
    ('119.97.185.59', 7709), ('124.70.133.119', 7709), ('116.205.183.150', 7709),
    ('123.60.73.44', 7709),  ('116.205.163.254', 7709), ('121.36.225.169', 7709),
    ('123.60.70.228', 7709), ('124.71.9.153', 7709),    ('110.41.147.114', 7709),
    ('124.71.187.122', 7709),
]
def _tdx_probe(ip, port, timeout=2.0):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False
def _tdx_validate(client):
    try:
        df = client.bars(symbol='000001', frequency=9, offset=1)
        return df is not None and not df.empty
    except Exception:
        return False
_TDX_CLIENT_CACHE = {"client": None, "done": False}
def tdx_client(market='std'):
    if _TDX_CLIENT_CACHE["done"]:
        return _TDX_CLIENT_CACHE["client"]
    client = None
    for ip, port in _TDX_SERVERS:
        if not _tdx_probe(ip, port):
            continue
        try:
            c = Quotes.factory(market=market, server=(ip, port))
            if _validate(c):
                client = c
                break
        except Exception:
            continue
    if client is None:
        for kw in ({'bestip': True}, {}):
            try:
                c = Quotes.factory(market=market, **kw)
                if _validate(c):
                    client = c
                    break
            except Exception:
                continue
    _TDX_CLIENT_CACHE["client"] = client
    _TDX_CLIENT_CACHE["done"] = True
    return client

def kline_mootdx(code, days=60):
    try:
        global Quotes
        from mootdx.quotes import Quotes
        c = tdx_client()
        if c is None:
            return None
        df = c.bars(symbol=code, frequency=9, offset=days)
        if df is None or df.empty:
            return None
        rows = []
        for _, r in df.iterrows():
            rows.append({"date": str(r.get("datetime", "")), "open": _f(r.get("open")),
                         "close": _f(r.get("close")), "high": _f(r.get("high")),
                         "low": _f(r.get("low")), "volume": _f(r.get("vol")),
                         "amount": _f(r.get("amount"))})
        return rows
    except Exception as e:
        return None

def kline_sina(code, days=60):
    """备用源：新浪日K（scale=240 即日线，datalen=天数）。返回最新 days 根。"""
    try:
        symbol = ("sh" if code.startswith(("5", "6", "9")) else "sz") + code
        url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {"symbol": symbol, "scale": 240, "ma": "5", "datalen": days}
        headers = {"User-Agent": UA, "Referer": "https://finance.sina.com.cn/"}
        d = json.loads(_http_get(url, params, headers))
        if not d:
            return None
        out, cnt = [], 0
        for r in d:
            out.append({"date": r.get("day"), "open": _f(r.get("open")), "close": _f(r.get("close")),
                        "high": _f(r.get("high")), "low": _f(r.get("low")),
                        "volume": _f(r.get("volume")), "ma5": _f(r.get("ma_price5"))})
            cnt += 1
            if cnt >= days:
                break
        return out if out else None
    except Exception:
        return None

def get_kline(code, days=60):
    rows = kline_mootdx(code, days)
    if rows:
        return {"source": "mootdx", "available": True, "data": rows}
    rows = kline_sina(code, days)
    if rows:
        return {"source": "sina", "available": True, "data": rows}
    return {"source": None, "available": False, "data": [],
            "reason": "mootdx 返回空(海外/坏服务器) 且 新浪备用源不可用"}


# ============================================================
# 3. 基本面 (主源 mootdx finance §6.1；回退 同花顺一致预期EPS §2.2)
# ============================================================
def fundamental_mootdx(code):
    try:
        from mootdx.quotes import Quotes
        c = tdx_client()
        if c is None:
            return None
        pfx = ("sh" if code.startswith(("5", "6", "9")) else "sz") + code
        fin = c.finance(symbol=pfx)
        if fin is None or (hasattr(fin, "empty") and fin.empty):
            return None
        row = fin.iloc[0].to_dict() if hasattr(fin, "iloc") else {}
        return {"eps": _f(row.get("eps")), "roe": _f(row.get("roe")),
                "profit": _f(row.get("profit")), "income": _f(row.get("income")),
                "bvps": _f(row.get("bvps")), "total_shares": _f(row.get("zongguben"))}
    except Exception:
        return None

def fundamental_10jqka(code):
    """备用源：同花顺一致预期（worth.html，含 EPS/ROE/净利润 预测）。"""
    try:
        url = f"https://basic.10jqka.com.cn/new/{code}/worth.html"
        txt = _http_get(url, headers={"User-Agent": UA, "Referer": "https://basic.10jqka.com.cn/"}, encoding="gbk")
        def grab(pattern):
            m = re.search(pattern, txt)
            if m:
                try:
                    return float(m.group(1).replace(",", ""))
                except Exception:
                    return 0.0
            return 0.0
        eps = grab(r"一致预期.*?EPS.*?([\d.]+)")
        roe = grab(r"ROE.*?([\d.]+)%")
        profit = grab(r"净利润.*?([\d.]+)")
        return {"eps": eps, "roe": roe, "profit": profit, "income": 0.0, "bvps": 0.0, "total_shares": 0.0}
    except Exception:
        return None

def get_fundamental(code):
    d = fundamental_mootdx(code)
    if d:
        return {"source": "mootdx", "available": True, **d}
    d = fundamental_10jqka(code)
    if d and (d.get("eps") or d.get("roe") or d.get("profit")):
        return {"source": "10jqka", "available": True, **d}
    return {"source": None, "available": False, "eps": 0, "roe": 0, "profit": 0,
            "income": 0, "bvps": 0, "total_shares": 0,
            "reason": "mootdx 不可用 且 同花顺解析失败"}


# ============================================================
# 4. 资金面 (东财 push2his 个股资金流120日 §4.5)
# ============================================================
import requests
EM_SESSION = requests.Session(); EM_SESSION.headers.update({"User-Agent": UA})
_em_last = [0.0]
def em_get(url, params=None, headers=None, timeout=15):
    wait = 1.0 - (time.time() - _em_last[0])
    if wait > 0:
        time.sleep(wait + 0.2)
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout)
    finally:
        _em_last[0] = time.time()

DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_TOKEN = "894050c76af8597a853f5b408b759f5d"   # 东财千股千评公开 token（akshare 同款）

def eastmoney_datacenter(report_name, columns="ALL", filter_str="", page_size=50,
                         sort_columns="", sort_types="-1"):
    """东财数据中心统一查询（龙虎榜/千股千评等，已内置限流）。"""
    params = {"reportName": report_name, "columns": columns, "filter": filter_str,
              "pageNumber": "1", "pageSize": str(page_size), "sortColumns": sort_columns,
              "sortTypes": sort_types, "source": "WEB", "client": "WEB", "token": EM_TOKEN}
    r = em_get(DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []

def fund_flow_120d(code):
    try:
        secid = ("1." if code.startswith("6") else "0.") + code
        url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
        params = {"secid": secid, "fields1": "f1,f2,f3,f7",
                  "fields2": "f51,f52,f53,f54,f55,f56,f57", "lmt": "120"}
        headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
        d = em_get(url, params=params, headers=headers, timeout=15).json()
        kls = d.get("data", {}).get("klines", [])
        rows = []
        for line in kls:
            p = line.split(",")
            if len(p) < 6:
                continue
            rows.append({"date": p[0], "main_net": _f(p[1]), "small_net": _f(p[2]),
                         "mid_net": _f(p[3]), "large_net": _f(p[4]), "super_net": _f(p[5])})
        if not rows:
            return {"source": "eastmoney", "available": False, "data": [],
                    "reason": "东财 push2his 返回空（该 IP 可能被风控）"}
        recent = rows[-20:]
        total = sum(r["main_net"] for r in recent)
        return {"source": "eastmoney", "available": True, "data": rows,
                "recent20_main_net_yi": round(total / 1e8, 3)}
    except Exception as e:
        return {"source": "eastmoney", "available": False, "data": [],
                "reason": "东财 push2his 连接失败: %s" % type(e).__name__}


# ============================================================
# 5. 新闻 (东财个股新闻 §5.1)
# ============================================================
def eastmoney_news(code, page_size=10):
    try:
        cb = "jQuery_news"
        url = "https://search-api-web.eastmoney.com/search/jsonp"
        inner = json.dumps({"uid": "", "keyword": code, "type": ["cmsArticleWebOld"],
                            "client": "web", "clientType": "web", "clientVersion": "curr",
                            "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                                                           "pageIndex": 1, "pageSize": page_size,
                                                           "preTag": "", "postTag": ""}}}, separators=(',', ':'))
        r = em_get(url, params={"cb": cb, "param": inner},
                   headers={"User-Agent": UA, "Referer": "https://so.eastmoney.com/"})
        txt = r.text
        js = txt[txt.index("(") + 1: txt.rindex(")")]
        arts = json.loads(js).get("result", {}).get("cmsArticleWebOld", []) or []
        items = [{"title": re.sub(r"<[^>]+>", "", a.get("title", "")),
                  "content": re.sub(r"<[^>]+>", "", a.get("content", ""))[:200],
                  "time": a.get("date", ""), "source": a.get("mediaName", ""),
                  "url": a.get("url", "")} for a in arts]
        return {"source": "eastmoney", "available": bool(items), "items": items,
                "reason": "" if items else "东财返回空（该 IP 间歇风控）"}
    except Exception as e:
        return {"source": "eastmoney", "available": False, "items": [],
                "reason": "东财新闻接口失败: %s" % type(e).__name__}


# ============================================================
# 5b. 东财个股舆情(千股千评) · 龙虎榜游资动向 · 新闻情绪分析
#     来源: a-stock-data §3.5/§3.9 龙虎榜; daily_stock_analysis 经 akshare
#     stock_comment_em 的千股千评(东财 datacenter，免费、无需 Cookie)
# ============================================================
def _latest_trade_date(days_back=0):
    """最近交易日 YYYY-MM-DD（周末顺延到周五）。"""
    import datetime
    d = datetime.date.today() - datetime.timedelta(days=days_back)
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def eastmoney_comment(code):
    """东财个股舆情·千股千评（datacenter RPT_DMSK_TS_STOCKNEW）。
    返回机构参与度/综合得分/关注指数/排名/主力成本等个股情绪信号。"""
    try:
        filt = "(SECURITY_CODE=" + '"' + code + '"' + ")"
        data = eastmoney_datacenter("RPT_DMSK_TS_STOCKNEW", page_size=10,
                                    filter_str=filt, sort_columns="SECURITY_CODE", sort_types="1")
        if not data:
            return {"source": "eastmoney(千股千评)", "available": False, "reason": "东财返回空"}
        row = data[0]
        def to_f(k):
            try:
                return float(row.get(k))
            except Exception:
                return 0.0
        return {"source": "eastmoney(千股千评/RPT_DMSK_TS_STOCKNEW)",
                "available": True,
                "trade_date": str(row.get("TRADE_DATE", ""))[:10],
                "org_participate": to_f("ORG_PARTICIPATE"),
                "participate_type": row.get("PARTICIPATE_TYPE", ""),
                "total_score": to_f("TOTALSCORE"),
                "rank": int(to_f("RANK")), "rank_up": int(to_f("RANK_UP")),
                "focus": to_f("FOCUS"),
                "main_cost": to_f("PRIME_COST"),
                "big_inflow": to_f("BIGDEAL_INFLOW"), "big_outflow": to_f("BIGDEAL_OUTFLOW"),
                "super_inflow": to_f("SUPERDEAL_INFLOW"), "super_outflow": to_f("SUPERDEAL_OUTFLOW"),
                "ratio": to_f("RATIO"), "ratio_3d": to_f("RATIO_3DAYS"), "ratio_50d": to_f("RATIO_50DAYS")}
    except Exception as e:
        return {"source": "eastmoney(千股千评)", "available": False,
                "reason": "千股千评接口失败: %s" % type(e).__name__}


def dragon_tiger_board(code, trade_date=None, look_back=30):
    """个股龙虎榜+买卖席位TOP5+机构动向（a-stock-data §3.5）。看大资金/游资态度。"""
    try:
        if trade_date is None:
            trade_date = _latest_trade_date(0)
        start_s = _latest_trade_date(look_back)
        filt = "(TRADE_DATE>=" + "'" + start_s + " 00:00:00'" + ")(TRADE_DATE<=" + "'" + trade_date + " 23:59:59'" + ")(SECURITY_CODE=" + '"' + code + '"' + ")"
        records = []
        data = eastmoney_datacenter("RPT_DAILYBILLBOARD_DETAILSNEW", filter_str=filt,
                                    page_size=50, sort_columns="TRADE_DATE", sort_types="-1")
        for row in data:
            records.append({"date": str(row.get("TRADE_DATE", ""))[:10],
                             "reason": row.get("EXPLANATION", ""),
                             "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
                             "turnover": round(float(row.get("TURNOVERRATE") or 0), 2)})
        seats = {"buy": [], "sell": []}
        institution = {"buy_amt": 0.0, "sell_amt": 0.0, "net_amt": 0.0}
        if records:
            latest = records[0]["date"]
            fb = "(TRADE_DATE=" + "'" + latest + " 00:00:00'" + ")(SECURITY_CODE=" + '"' + code + '"' + ")"
            buy_data = eastmoney_datacenter("RPT_BILLBOARD_DAILYDETAILSBUY", filter_str=fb,
                                            page_size=10, sort_columns="BUY", sort_types="-1")
            for row in buy_data[:5]:
                seats["buy"].append({"name": row.get("OPERATEDEPT_NAME", ""),
                                     "buy_wan": round((row.get("BUY") or 0) / 10000, 1),
                                     "sell_wan": round((row.get("SELL") or 0) / 10000, 1),
                                     "net_wan": round((row.get("NET") or 0) / 10000, 1)})
            sell_data = eastmoney_datacenter("RPT_BILLBOARD_DAILYDETAILSSELL", filter_str=fb,
                                             page_size=10, sort_columns="SELL", sort_types="-1")
            for row in sell_data[:5]:
                seats["sell"].append({"name": row.get("OPERATEDEPT_NAME", ""),
                                      "buy_wan": round((row.get("BUY") or 0) / 10000, 1),
                                      "sell_wan": round((row.get("SELL") or 0) / 10000, 1),
                                      "net_wan": round((row.get("NET") or 0) / 10000, 1)})
            for detail_data, side in [(buy_data, "buy"), (sell_data, "sell")]:
                for row in detail_data:
                    if str(row.get("OPERATEDEPT_CODE", "")) == "0":
                        amt = (row.get("BUY") or 0) if side == "buy" else (row.get("SELL") or 0)
                        if side == "buy":
                            institution["buy_amt"] += amt
                        else:
                            institution["sell_amt"] += amt
            institution["buy_amt"] = round(institution["buy_amt"] / 10000, 1)
            institution["sell_amt"] = round(institution["sell_amt"] / 10000, 1)
            institution["net_amt"] = round(institution["buy_amt"] - institution["sell_amt"], 1)
        return {"source": "eastmoney(datacenter)", "available": True,
                "trade_date": trade_date, "look_back": look_back,
                "records": records, "seats": seats, "institution": institution}
    except Exception as e:
        return {"source": "eastmoney(datacenter)", "available": False,
                "reason": "龙虎榜接口失败: %s" % type(e).__name__}


def news_sentiment(code, news_items):
    """新闻情绪分析（内置词典法，daily_stock_analysis 风格，免费、自动）。
    对东财个股新闻的标题+正文做看多/看空打分，输出整体情绪。"""
    texts = []
    for n in news_items:
        t = (n.get("title", "") or "") + " " + (n.get("content", "") or "")
        if t.strip():
            texts.append(t)
    if not texts:
        return {"source": "builtin_lexicon", "available": False, "reason": "无新闻文本可分析"}
    sm = build_sentiment_summary(texts, "news_lexicon")
    sm["source"] = "builtin_lexicon(news)"
    sm["available"] = True
    return sm


# ============================================================
# 6. 雪球舆情 (Agent-Reach xueqiu 模块)
# ============================================================
POS_WORDS = ["涨", "利好", "买入", "增持", "增长", "超预期", "突破", "看好", "盈利",
             "复苏", "新高", "乐观", "改善", "强", "稳", "扩产", "中标", "回购", "分红"]
NEG_WORDS = ["跌", "利空", "卖出", "减持", "下滑", "亏损", "爆雷", "退市", "风险",
             "看空", "承压", "下调", "低于", "疲软", "悲观", "违约", "调查", "处罚", "警示"]

def sentiment_of(text):
    pos = sum(text.count(w) for w in POS_WORDS)
    neg = sum(text.count(w) for w in NEG_WORDS)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"

def xueqiu_posts(code, limit=5):
    """调用 Agent-Reach 的 xueqiu 模块拉取该股票最新讨论。需登录 Cookie 时才返回数据。"""
    try:
        from agent_reach.channels.xueqiu import _get_json
    except Exception as e:
        return {"source": "xueqiu(agent-reach)", "available": False, "posts": [],
                "status": "module_import_failed", "reason": str(e)[:120]}
    try:
        # 雪球搜索该股票讨论（公开 API，需会话 Cookie）
        d = _get_json("https://xueqiu.com/statuses/search.json?q=%s&count=%d&sort=time" % (code, limit))
        lst = d.get("list") or []
        posts = []
        for it in lst[:limit]:
            p = it.get("text") or it.get("description") or ""
            p = re.sub(r"<[^>]+>", "", p)
            user = it.get("user") or {}
            posts.append({"id": it.get("id"), "title": it.get("title") or "",
                          "text": p[:200], "author": user.get("screen_name", ""),
                          "time": str(it.get("created_at", "")),
                          "url": "https://xueqiu.com/%s" % it.get("id", ""),
                          "sentiment": sentiment_of(p)})
        if posts:
            return {"source": "xueqiu(agent-reach)", "available": True, "status": "ok", "posts": posts}
        return {"source": "xueqiu(agent-reach)", "available": False, "status": "no_cookie",
                "posts": [], "reason": "雪球返回空：需配置登录 Cookie（config xueqiu_cookie 或 agent-reach configure --from-browser）"}
    except Exception as e:
        return {"source": "xueqiu(agent-reach)", "available": False, "status": "request_failed",
                "posts": [], "reason": "%s: %s" % (type(e).__name__, str(e)[:100])}


def build_sentiment_summary(texts, source_label):
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    for t in texts:
        counts[sentiment_of(t)] += 1
    total = max(1, sum(counts.values()))
    overall = "positive" if counts["positive"] > counts["negative"] else (
        "negative" if counts["negative"] > counts["positive"] else "neutral")
    return {"source": source_label, "counts": counts,
            "overall": overall, "score": round((counts["positive"] - counts["negative"]) / total, 3)}


# ============================================================
# 主流程
# ============================================================
def fetch_stock(code):
    print("  -> 处理 %s ..." % code, flush=True)
    rec = {"code": code}
    # 行情
    q = tencent_quote([code]).get(code, {})
    rec["quote"] = q
    rec["name"] = q.get("name", code)
    # K线
    rec["kline"] = get_kline(code, 60)
    # 基本面
    rec["fundamental"] = get_fundamental(code)
    # 资金面
    rec["fund_flow"] = fund_flow_120d(code)
    # 新闻（东财个股新闻）
    news = eastmoney_news(code, 10)
    rec["news"] = news
    # 东财个股舆情（千股千评，daily_stock_analysis 经 akshare 口径）
    rec["guba"] = eastmoney_comment(code)
    # 新闻情绪分析（内置词典，自动）
    rec["news_sentiment"] = news_sentiment(code, news.get("items", []))
    # 龙虎榜游资动向（a-stock-data §3.5）
    rec["dragon_tiger"] = dragon_tiger_board(code)
    # 雪球：按用户要求暂跳过，待配置 Cookie 后补回
    rec["xueqiu"] = {"skipped": True,
                     "reason": "按用户要求暂跳过 Agent-Reach 雪球，待配置 Cookie 后补回"}
    return rec


def main():
    codes = sys.argv[1:] or STOCKS_DEFAULT
    stocks = []
    for c in codes:
        stocks.append(fetch_stock(c))
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "data_sources": {
            "quote": "腾讯财经 qt.gtimg.cn (a-stock-data §1.2)",
            "kline": "mootdx / 新浪 (a-stock-data §1.1/§1.3)",
            "fundamental": "mootdx finance / 同花顺 (a-stock-data §6.1/§2.2)",
            "fund_flow": "东财 push2his 资金流 (a-stock-data §4.5)",
            "news": "东财 search-api 个股新闻 (a-stock-data §5.1)",
            "guba": "东财千股千评 datacenter RPT_DMSK_TS_STOCKNEW (daily_stock_analysis 经 akshare stock_comment_em)",
            "news_sentiment": "内置词典法 (daily_stock_analysis 风格)",
            "dragon_tiger": "东财 datacenter 龙虎榜 (a-stock-data §3.5)",
            "xueqiu": "Agent-Reach xueqiu（本次按用户要求跳过，待补 Cookie）",
        },
        "notes": "雪球需登录Cookie、东财push2资金流对部分IP有风控；不可用时标记 available=false，不伪造数值。东财股吧帖子公开接口在本环境被限制，故股吧舆情改用东财「千股千评」(同 daily_stock_analysis 经 akshare 的口径)作个股情绪信号；如需原始股吧帖子，需国内网络/带Cookie环境。",
        "stocks": stocks,
    }
    out_path = os.path.join(ROOT, "data", "report_data.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("\n已生成: %s  (共 %d 只股票)" % (out_path, len(stocks)))
    for s in stocks:
        g = s.get("guba", {}); ns = s.get("news_sentiment", {}); dt = s.get("dragon_tiger", {})
        print("  %s %s | 行情:%s PE:%.2f | K线:%s | 基本面:%s | 资金流:%s | 新闻:%d | 千股千评:%s | 新闻情绪:%s | 龙虎榜:%s | 雪球:跳过" % (
            s["code"], s["name"], "Y" if s["quote"].get("price") else "N", s["quote"].get("pe_ttm", 0),
            "Y" if s["kline"]["available"] else "N", "Y" if s["fundamental"]["available"] else "N",
            "Y" if s["fund_flow"]["available"] else "N", len(s["news"].get("items", [])),
            "Y" if g.get("available") else "N", "Y" if ns.get("available") else "N",
            "Y" if dt.get("available") else "N"))


if __name__ == "__main__":
    main()
