# -*- coding: utf-8 -*-
"""
fetch_all_data.py — A股研究台 全量数据聚合（第6模块 Crawl4AI 融合）
==================================================
流程：
  1. 调 fetch_data.main() 生成基础 report_data.json（行情/K线/基本面/资金流/新闻/千股千评/龙虎榜）
  2. 调 crawl_news 抓网页舆情（东财页面新闻/财联社7x24/巨潮公告；雪球反爬则跳过）
  3. 在 report_data.json 增加：
       report["web_crawl"] = {"eastmoney_news":[...], "cls_telegraph":[...], "cninfo_announcements":[...]}
       每只股票 s["web_news"] = {"latest_headlines":[...], "key_events":[...]}
用法:
    python fetch_all_data.py 600519
    python fetch_all_data.py 600519 000001 002594 300750 000858
"""
import os, sys, json, time

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
for p in (os.path.join(ROOT, "_libs"), os.path.join(ROOT, "agent-reach")):
    if p not in sys.path:
        sys.path.insert(0, p)
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fetch_data
import crawl_news


def _dedupe(items, key="title"):
    seen, out = set(), []
    for it in items:
        k = (it.get(key) or "").strip()
        if k and k not in seen:
            seen.add(k)
            out.append(it)
    return out


def main():
    codes = sys.argv[1:] or fetch_data.STOCKS_DEFAULT
    path = os.path.join(ROOT, "data", "report_data.json")

    # 1) 基础数据（复用 fetch_data 全流程）
    print("==> 步骤1: fetch_data 全量数据 ...")
    fetch_data.main()

    # 2) 网页舆情抓取
    print("==> 步骤2: Crawl4AI 网页舆情抓取 ...")
    report = json.load(open(path, encoding="utf-8"))
    web_crawl = {"eastmoney_news": [], "cls_telegraph": [],
                 "cninfo_announcements": [], "xueqiu": []}
    try:
        cls = crawl_news.cls_telegraph()
        web_crawl["cls_telegraph"] = cls.get("items", [])
        print("  财联社快讯: %d 条 (engine=%s)" % (len(cls.get("items", [])), cls.get("engine")))
    except Exception as e:
        print("  财联社失败: %s" % str(e)[:80])
    time.sleep(1.0)

    for s in report.get("stocks", []):
        c, n = s.get("code", ""), s.get("name", "")
        em = crawl_news.eastmoney_news(c, n)
        cn = crawl_news.cninfo_announcements(n or c, c, n)
        xq = crawl_news.xueqiu(c, n)
        web_crawl["eastmoney_news"].extend(em.get("items", [])[:3])
        web_crawl["cninfo_announcements"].extend(cn.get("items", [])[:3])
        web_crawl["xueqiu"] = xq.get("note", "")
        s["web_news"] = {
            "latest_headlines": [x["title"] for x in em.get("items", [])[:5]],
            "key_events": [x["title"] for x in cn.get("items", [])[:3]],
        }
        print("  %s %s: 东财页面%d条/公告%d条/雪球:%s" % (
            c, n, len(em.get("items", [])), len(cn.get("items", [])),
            "有内容" if xq.get("items") else "跳过(反爬)"))
        time.sleep(1.0)

    web_crawl["eastmoney_news"] = _dedupe(web_crawl["eastmoney_news"])[:10]
    web_crawl["cninfo_announcements"] = _dedupe(web_crawl["cninfo_announcements"])[:6]
    report["web_crawl"] = web_crawl
    report["data_sources"]["web_crawl"] = (
        "Crawl4AI 网页抓取(东财页面/财联社/巨潮) + requests 兜底 (scripts/crawl_news.py)")
    report["notes"] += "；网页舆情由 Crawl4AI 模块抓取，雪球反爬时跳过(可用 Agent-Reach 补)。"

    json.dump(report, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n已生成(含 web_crawl): %s" % path)
    print("  web_crawl: 东财新闻%d 财联社%d 巨潮公告%d" % (
        len(web_crawl["eastmoney_news"]), len(web_crawl["cls_telegraph"]),
        len(web_crawl["cninfo_announcements"])))

    # 3) czsc 缠论分析：报告内股票 + config/watchlist.json 自选股（以后新增自选自动覆盖）
    print("\n==> 步骤3: czsc 缠论分析（自选股默认全跑）...")
    import shutil
    import chan_analysis
    codes_chan = [s.get("code") for s in report.get("stocks", [])]
    wl_path = os.path.join(ROOT, "config", "watchlist.json")
    if os.path.exists(wl_path):
        try:
            for w in json.load(open(wl_path, encoding="utf-8")):
                c = w.get("code")
                if c and c not in codes_chan:
                    codes_chan.append(c)
        except Exception:
            pass
    app_dir = os.path.join(ROOT, "app")
    for c in codes_chan:
        try:
            r = chan_analysis.analyze(c, 160)
            if r.get("available"):
                fp = os.path.join(ROOT, "data", "chan_%s.json" % c)
                json.dump(r, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                shutil.copy2(fp, os.path.join(app_dir, "chan_%s.json" % c))
                print("  缠论 %s: 笔%d 中枢%d 买卖点%s" % (
                    c, r.get("bi_count", 0), len(r.get("zs_list", [])),
                    r.get("buy_sell_points") or "无"))
        except Exception as e:
            print("  缠论 %s 失败: %s" % (c, str(e)[:60]))

    # 4) 大盘复盘同步：daily_stock_analysis/reports/market_review_*.md → app/market_review.md
    drep = os.path.join(ROOT, "daily_stock_analysis", "reports")
    if os.path.isdir(drep):
        import glob
        mrs = sorted(glob.glob(os.path.join(drep, "market_review_*.md")))
        if mrs:
            shutil.copy2(mrs[-1], os.path.join(app_dir, "market_review.md"))
            print("  大盘复盘已同步: %s" % os.path.basename(mrs[-1]))


if __name__ == "__main__":
    main()
