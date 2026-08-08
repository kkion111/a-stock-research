# -*- coding: utf-8 -*-
"""
crawl_news.py — A股研究台 第6模块：Crawl4AI 网页舆情抓取增强
==================================================
引擎：Crawl4AI (AsyncWebCrawler, headless Chromium) 为主；
     若 crawl4ai 导入失败或浏览器不可用，自动降级 requests(UA) 直抓，
     保证「至少一个网站能抓到有效内容」。

统一输出（每个抓取函数）：
{
  "source": "eastmoney_news | cls_telegraph | xueqiu | cninfo_announcements",
  "fetched_at": "2026-08-08T17:20:00+08:00",
  "code": "600519", "name": "贵州茅台",
  "items": [{"title","url","publish_time","summary","source_site"}],
  "engine": "crawl4ai | requests", "note": "抓取/提取说明"
}

用法：
    python crawl_news.py 600519                # 抓全部 4 源
    python crawl_news.py 600519 --only cls     # 只抓财联社
"""
import os, sys, json, re, time, asyncio, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
for p in (os.path.join(ROOT, "_libs"),):
    if p not in sys.path:
        sys.path.insert(0, p)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
SLEEP = 1.5  # 反爬：源间请求间隔(秒)
_JUNK = ("举报中心", "违法和违规", "与本站立场无关", "传播更多信息",
         "东方财富网发布此信息", "cookie", "使用条款", "隐私政策", "广告服务")


def now_iso():
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def _clean(s):
    s = re.sub(r"<script[\s\S]*?</script>", " ", s)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _wrap(source, code, name, items, engine, note=""):
    return {"source": source, "fetched_at": now_iso(), "code": code,
            "name": name, "items": items, "engine": engine, "note": note}


def fetch_page(url, headers=None, timeout=20):
    """返回 (html, engine) 或 (None, reason)。Crawl4AI 优先。"""
    h = headers or {"User-Agent": UA, "Referer": "https://www.baidu.com/"}
    # 引擎1: Crawl4AI
    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
        async def _crawl():
            async with AsyncWebCrawler(verbose=False) as crawler:
                cfg = CrawlerRunConfig(headless=True, user_agent=UA,
                                       page_timeout=15000, delay_between_requests=1.0)
                res = await crawler.arun(url=url, config=cfg)
                return (res.html or "") if res.success else ""
        html = asyncio.run(_crawl())
        if html and len(html) > 200:
            return html, "crawl4ai"
    except Exception:
        pass
    # 引擎2: requests
    try:
        import requests
        r = requests.get(url, headers=h, timeout=timeout)
        r.encoding = r.apparent_encoding or "utf-8"
        if r.status_code == 200 and len(r.text) > 100:
            return r.text, "requests"
        return None, "requests status=%s len=%d" % (r.status_code, len(r.text))
    except Exception as e:
        return None, "requests %s: %s" % (type(e).__name__, str(e)[:80])


# ============================================================
# 功能1：东方财富个股新闻（页面抓取）
# ============================================================
def eastmoney_news(code, name=""):
    src = "eastmoney_news"
    urls = [
        "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/Index?type=web&code=SH%s" % code,
        "https://finance.eastmoney.com/a/cywjh.html",   # 财经要闻汇总(静态可抓)
    ]
    items = []
    engine = ""
    for u in urls:
        time.sleep(SLEEP)
        html, eng = fetch_page(u)
        if not html:
            continue
        engine = engine or eng
        txt = _clean(html)
        # 1) 带 title 属性的链接（多数新闻链接）
        for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*title="([^"]{6,80})"', html):
            url, title = m.group(1), m.group(2).strip()
            if (url and title and not any(j in title for j in _JUNK)
                    and url not in [x["url"] for x in items]):
                items.append({"title": title, "url": url, "publish_time": "",
                              "summary": "", "source_site": "东方财富"})
        # 2) 纯文本里长度 12~60 且含常见新闻词的句子作为兜底标题
        for sent in re.findall(r"[\u4e00-\u9fff][\u4e00-\u9fff0-9A-Za-z%.\-（）()、，。]{12,60}", txt):
            if (re.search(r"(涨|跌|涨停|跌停|发布|公告|业绩|净利|增长|回购|分红|收购|签订|中标|预增|减持|增持|破发|创新高)", sent)
                    and len(sent) >= 14 and not any(j in sent for j in _JUNK)):
                if not any(x["title"] == sent for x in items):
                    items.append({"title": sent, "url": u, "publish_time": "",
                                  "summary": "", "source_site": "东方财富"})
            if len(items) >= 10:
                break
        if items:
            break
    if not items:
        return _wrap(src, code, name, [], engine or "none", note="页面未提取到新闻链接(可能JS渲染或反爬)")
    return _wrap(src, code, name, items[:10], engine)


# ============================================================
# 功能2：财联社 7x24 快讯
# ============================================================
def cls_telegraph(code="", name=""):
    """财联社 7x24 快讯。优先 CLS 官方接口(需签名)；失败回退 新浪7x24(免费无签名)。"""
    src = "cls_telegraph"
    items = []
    note = ""
    # 1) CLS 官方接口（社区公开的 md5 签名，可能失效）
    try:
        import requests, hashlib
        s = requests.Session(); s.headers.update({"User-Agent": UA})
        s.get("https://www.cls.cn/telegraph", timeout=12)
        time.sleep(1.0)
        base = {"app": "CailianpressWeb", "category": "", "hasFirstVipArticle": "1",
                "last_time": "", "os": "web", "refresh_type": "1", "rn": "10", "sv": "7.7.5"}
        path = "/v1/roll/get_roll_list"
        q = "&".join("%s=%s" % (k, v) for k, v in sorted(base.items()))
        base["sign"] = hashlib.md5(q.encode()).hexdigest()
        r = s.get("https://www.cls.cn" + path, params=base,
                  headers={"Referer": "https://www.cls.cn/telegraph", "Origin": "https://www.cls.cn"}, timeout=12)
        d = r.json()
        if d.get("errno") in (None, "0", 0, "0"):
            rolls = ((d.get("data") or {}).get("roll_data")) or []
            for it in rolls[:10]:
                items.append({"title": _clean(it.get("title") or it.get("brief") or ""),
                              "url": "https://www.cls.cn/detail/%s" % it.get("id", ""),
                              "publish_time": datetime.datetime.fromtimestamp(it.get("ctime") or 0).strftime("%Y-%m-%d %H:%M"),
                              "summary": _clean((it.get("content") or "")[:120]),
                              "source_site": "财联社"})
            if items:
                return _wrap(src, code, name, items, "requests(cls api)", note="CLS 官方接口")
        note = "财联社签名受限: %s" % (d.get("msg") or d.get("errno") or "")
    except Exception as e:
        note = "财联社接口异常: %s: %s" % (type(e).__name__, str(e)[:60])
    # 2) 回退：新浪 7x24 快讯（免费、无签名）
    try:
        import requests
        r = requests.get("https://zhibo.sina.com.cn/api/zhibo/feed",
                         params={"page": 1, "page_size": 10, "zhibo_id": 152,
                                 "tag_id": 0, "dire": "f", "dpc": 1},
                         headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn/7x24/"}, timeout=12)
        feed = ((r.json().get("result") or {}).get("data") or {}).get("feed") or {}
        for it in (feed.get("list") or [])[:10]:
            txt = _clean(it.get("rich_text") or it.get("text") or "")
            items.append({"title": txt[:60], "url": it.get("url") or "https://finance.sina.com.cn/7x24/",
                          "publish_time": (it.get("create_time") or "")[:16],
                          "summary": txt[:120], "source_site": "新浪7x24"})
        if items:
            return _wrap(src, code, name, items, "requests(sina7x24)",
                         note=note + "；财联社需签名不可用，已用新浪7x24替代")
    except Exception as e:
        note += "；新浪7x24也失败: %s" % str(e)[:60]
    # 3) 最后尝试页面抓取（Crawl4AI 渲染）
    time.sleep(SLEEP)
    html, engine = fetch_page("https://www.cls.cn/telegraph")
    if html:
        txt = _clean(html)
        for sent in re.findall(r"[\u4e00-\u9fff][\u4e00-\u9fff0-9A-Za-z%.\-（）()、，。]{16,90}", txt):
            if re.search(r"(涨|跌|亿|发布|宣布|央行|证监会|两市|板块|指数|股份|回购|增持|减持|涨停|跌停)", sent) and len(sent) >= 16:
                if not any(x["title"] == sent for x in items):
                    items.append({"title": sent, "url": "https://www.cls.cn/telegraph",
                                  "publish_time": "", "summary": "", "source_site": "财联社"})
            if len(items) >= 8:
                break
    if not items:
        return _wrap(src, code, name, [], engine or "none", note=note or "未取到快讯")
    return _wrap(src, code, name, items[:10], engine or "requests", note=note)


# ============================================================
# 功能3：雪球热帖（免登录尝试，反爬则跳过）
# ============================================================
def xueqiu(code, name=""):
    src = "xueqiu"
    time.sleep(SLEEP)
    html, engine = fetch_page("https://xueqiu.com/S/SH%s" % code,
                              headers={"User-Agent": UA, "Referer": "https://xueqiu.com/"})
    if not html:
        return _wrap(src, code, name, [], engine or "none",
                     note="雪球反爬: %s" % (engine or "无响应"))
    txt = _clean(html)
    items = []
    for sent in re.findall(r"[\u4e00-\u9fff][\u4e00-\u9fff0-9A-Za-z%.\-（）()、，。]{12,60}", txt):
        if re.search(r"(涨|跌|买入|卖出|抄底|加仓|清仓|利好|利空|复盘|持有|突破|回调)", sent) and len(sent) >= 14:
            items.append({"title": sent, "url": "https://xueqiu.com/S/SH%s" % code,
                          "publish_time": "", "summary": "", "source_site": "雪球"})
        if len(items) >= 5:
            break
    if not items:
        return _wrap(src, code, name, [], engine, note="雪球页面需登录/反爬，抓到壳但无帖子内容(已有 Agent-Reach 模块)")
    return _wrap(src, code, name, items[:5], engine)


# ============================================================
# 功能4：巨潮资讯网公告（关键词搜索）
# ============================================================
def cninfo_announcements(keyword, code="", name=""):
    """巨潮资讯公告：topSearch 找 orgId → hisAnnouncement 查公告（两步，POST）"""
    src = "cninfo_announcements"
    items = []
    try:
        import requests
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Referer": "http://www.cninfo.com.cn/new/index"})
        # 1) 找 orgId
        org = ""
        r1 = s.post("http://www.cninfo.com.cn/new/information/topSearch/query",
                    data={"keyWord": keyword or code, "maxNum": "5"}, timeout=15)
        for it in (r1.json() or []):
            if it.get("code") == code or it.get("zwjc") == keyword:
                org = it.get("orgId", "")
                break
        if not org and r1.json():
            org = r1.json()[0].get("orgId", "")
        if not org:
            return _wrap(src, code, name, [], "requests(api)", note="未找到股票 orgId")
        # 2) 查公告（column 按交易所）
        col = "sse" if code.startswith(("6", "9", "5")) else ("bse" if code.startswith(("8", "4")) else "szse")
        r2 = s.post("http://www.cninfo.com.cn/new/hisAnnouncement/query",
                    data={"pageNum": "1", "pageSize": "10", "column": col, "tabName": "fulltext",
                          "plate": "", "stock": "%s,%s" % (code, org), "searchkey": keyword or "",
                          "secid": "", "category": "", "trade": "", "seDate": "",
                          "sortName": "", "sortType": "", "isHLtitle": "true"}, timeout=15)
        ann = ((r2.json() or {}).get("announcements") or [])
        for it in ann[:6]:
            ts = it.get("announcementTime")
            items.append({"title": _clean(it.get("announcementTitle") or ""),
                          "url": "http://static.cninfo.com.cn/%s" % (it.get("adjunctUrl") or ""),
                          "publish_time": datetime.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M") if ts else "",
                          "summary": "公告类型: %s" % _clean(it.get("announcementTypeName") or "公告"),
                          "source_site": "巨潮资讯"})
        if items:
            return _wrap(src, code, name, items[:5], "requests(api)",
                         note="topSearch+hisAnnouncement 两步查询")
    except Exception as e:
        return _wrap(src, code, name, [], "none",
                     note="巨潮接口失败: %s: %s" % (type(e).__name__, str(e)[:80]))
    return _wrap(src, code, name, [], "requests(api)", note="巨潮接口无返回")


# ============================================================
# 汇总
# ============================================================
def run_all(code, name, only=None):
    out = {}
    jobs = [
        ("eastmoney_news", eastmoney_news, (code, name)),
        ("cls_telegraph", cls_telegraph, (code, name)),
        ("xueqiu", xueqiu, (code, name)),
        ("cninfo_announcements", cninfo_announcements, (name or code, code, name)),
    ]
    for key, fn, args in jobs:
        if only and key != only:
            continue
        try:
            out[key] = fn(*args)
        except Exception as e:
            out[key] = _wrap(key, code, name, [], "none",
                             note="异常: %s: %s" % (type(e).__name__, str(e)[:80]))
    return out


if __name__ == "__main__":
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    code = argv[0] if argv else "600519"
    name = argv[1] if len(argv) > 1 else ""
    only = None
    for a in sys.argv[1:]:
        if a.startswith("--only"):
            only = sys.argv[sys.argv.index(a) + 1] if sys.argv.index(a) + 1 < len(sys.argv) else None
    res = run_all(code, name, only)
    print(json.dumps(res, ensure_ascii=False, indent=2))
