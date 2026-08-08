# -*- coding: utf-8 -*-
"""
fetch_all_data.py — A股研究台 数据融合脚本（全模块聚合）
=====================================================
输入: config/watchlist.json
输出: data/report_data.json

对每只自选股融合 8 类数据：
  1 基础数据  fetch_data.tencent_quote + get_fundamental
  2 K线      fetch_data.get_kline（均线趋势）
  3 资金流    fetch_data.fund_flow_120d
  4 缠论      chan_analysis（笔/中枢/买卖点）
  5 因子      vibe_factor_score（Alpha Zoo 综合分 + Top3）
  6 新闻舆情  fetch_data.eastmoney_news + crawl_news（东财页面/公告/7x24）
  7 四大师    ai_berkshire（优先深度版 JSON，否则 Python 规则引擎镜像网页端）
  8 大盘      daily_stock_analysis market_review 解析（指数/涨跌/成交/板块）

潜力股筛选：综合评分 = 技术0.25 + 基本面0.2 + 因子0.2 + 四大师0.25 + 舆情0.1
  过滤：0<PE<70、ROE>5%（ROE数据缺失时不拦截，标注受限）、价>3元 → Top8 + 标签

用法: python fetch_all_data.py            # 全自选
"""
import os, sys, json, time, datetime, glob, re

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
for p in (os.path.join(ROOT, "_libs"), os.path.join(ROOT, "agent-reach")):
    if p not in sys.path:
        sys.path.insert(0, p)
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fetch_data            # noqa: E402
import crawl_news            # noqa: E402
import chan_analysis         # noqa: E402
import vibe_factor_score     # noqa: E402


def now_iso():
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


# ============================================================
# 7. 四大师（Python 规则引擎，镜像网页端 fourMasterDeep）
# ============================================================
IND_Q = {'白酒': 95, '银行': 70, '家电': 78, '汽车': 72, '电池': 74, '医疗器械': 80,
         '保险': 68, '医药': 82, '软件': 76, '证券': 65, '有色': 70, '旅游': 60,
         '电子': 78, '电力': 75, '光伏': 66, '食品': 80, '石油': 72}
IND_VERDICT = {'白酒': '对的生意：品牌即定价权、先款后货、存货随时间增值',
               '银行': '生意不错但有周期属性：高杠杆、赚息差', '家电': '生意不错：现金流好、格局清晰，成长性一般',
               '汽车': '生意中等偏上：重资产、竞争激烈，需精选龙头', '电池': '好生意但重资产：技术迭代快，龙头有壁垒',
               '医疗器械': '生意不错：壁垒高、需求刚性，关注集采', '保险': '生意一般偏上：负债经营，周期性强',
               '医药': '好生意：需求刚性、壁垒高，研发风险需甄别', '软件': '生意不错：轻资产高毛利，护城河需持续投入',
               '证券': '生意一般：强周期，赚市场beta', '有色': '生意中等：资源为王但强周期',
               '旅游': '生意一般：现金流尚可，依赖消费景气', '电子': '生意中等偏上：高成长高波动',
               '电力': '生意不错：现金流稳定、类债属性', '光伏': '生意中等偏下：供给过剩，右侧确认前谨慎',
               '食品': '对的生意：现金流好、需求刚性', '石油': '生意中等：现金流强但油价周期决定弹性'}
IND_DEATH = {'白酒': ['需求断崖：高端量价齐杀、批价跌破出厂价', '政策黑天鹅：消费税改革或限三公', '品牌危机：食品安全/假酒', '人口结构：饮酒人口萎缩'],
             '银行': ['资产质量恶化（地产/城投不良爆发）', '净息差长期收窄', '系统性金融风险', '监管加码资本约束'],
             '家电': ['地产下行拖累需求', '原材料涨价挤压毛利', '价格战重演', '渠道变革掉队'],
             '汽车': ['价格战盈利恶化', '技术路线颠覆（智能化掉队）', '补贴退坡', '新势力冲击'],
             '电池': ['技术路线颠覆（固态等）', '产能过剩价格战', '下游自研电池', '海外政策壁垒'],
             '医疗器械': ['集采降价超预期', '技术迭代落后', '医疗反腐/合规', '进口反扑'],
             '保险': ['利率下行利差损', '保费失速', '投资端暴雷', '竞争加剧'],
             '医药': ['集采/医保降价', '研发失败（管线归零）', '合规反腐', '技术颠覆'],
             '软件': ['技术路线被颠覆', '巨头降维打击', '客户预算收缩', '人才流失'],
             '证券': ['市场长期低迷', '佣金价格战', '投行风险暴露', '杠杆风险'],
             '有色': ['大宗周期下行', '资源枯竭/成本上升', '需求结构变化', '海外政治风险'],
             '旅游': ['消费降级', '政策/疫情黑天鹅', '新业态分流', '高租金侵蚀'],
             '电子': ['客户订单流失', '技术路线切换', '贸易摩擦/出口管制', '周期下行'],
             '电力': ['电价改革压低回报', '来水/燃料波动', '资本开支重', '碳约束'],
             '光伏': ['产能过剩价格战', '技术颠覆', '海外贸易壁垒', '融资收紧'],
             '食品': ['原材料涨价', '渠道变革掉队', '食品安全', '消费降级'],
             '石油': ['油价长期低迷', '能源转型压缩需求', '地缘政治', '资本开支失守']}
GENERIC_DEATH = ['行业景气下行', '技术/模式被颠覆', '政策与监管变化', '管理层战略失误']


def _clamp(x, a, b):
    return max(a, min(b, round(x)))


def four_master_py(code, name, industry, price, pe, pb, roe, mcap, guba, news_label, trend):
    q = IND_Q.get(industry, 65)
    verdict = IND_VERDICT.get(industry, '生意中等：需精选龙头')
    death = IND_DEATH.get(industry, GENERIC_DEATH)
    ns = {'偏多': 85, '偏空': 50}.get(news_label, 68)
    dyp = _clamp(q * 0.5 + guba * 0.3 + ns * 0.2, 30, 98)
    pe_s = 90 if (not pe or pe <= 10) else (80 if pe <= 20 else (70 if pe <= 30 else (58 if pe <= 40 else 45)))
    roe_s = 88 if (roe and roe >= 25) else (80 if (roe and roe >= 18) else (70 if (roe and roe >= 12) else (82 if q >= 85 else 68)))
    buf = _clamp(pe_s * 0.4 + roe_s * 0.35 + guba * 0.15 + ns * 0.1 - (8 if (pb and pb > 8) else (3 if (pb and pb > 5) else 0)), 30, 96)
    risk = (0 if trend == '多头排列(ma20>ma60)' else 10) + (8 if guba > 92 else 0)
    mun = _clamp(100 - risk - (100 - guba) * 0.1, 30, 90)
    lilu = _clamp(q * 0.55 + (15 if (mcap and mcap >= 1000) else (10 if (mcap and mcap >= 200) else 5)) + (8 if ns > 70 else 0) + 6, 30, 96)
    avg = round((dyp + buf + mun + lilu) / 4)
    rating = '通过' if avg >= 75 else ('观望' if avg >= 55 else '不通过')
    base = (price * 1.08) if (pe and pe <= 15) else (price if (pe and pe <= 25) else (price * 0.92))
    fair = '保守%d / 基准%d / 乐观%d' % (round(base * 0.9), round(base), round(base * 1.15))
    action = ('逢回调分批建仓，不追高' if avg >= 75 else ('观望为主，等回调或企稳' if avg >= 55 else '暂不参与'))
    position = ('底仓10-15%' if avg >= 75 else ('观察仓≤5%' if avg >= 55 else '0仓位'))
    return {"duan": {"score": dyp, "points": [verdict, '行业质量评分%d/100' % q], "concerns": ['需跟踪行业景气与经营数据']},
            "buffett": {"score": buf, "points": ['估值因子(PE/PB/ROE)综合', '千股千评%d分' % guba], "concerns": ['盈利持续性需验证'], "fair_value": fair},
            "munger": {"score": mun, "points": ['逆向审视：' + ('情绪未过热' if guba <= 92 else '预期已满')], "concerns": ['警惕共识', '管理层资本配置需核查'], "death_scenarios": death[:3]},
            "li": {"score": lilu, "points": [verdict, ('市值%d亿' % mcap) if mcap else ''], "concerns": ['长期逻辑需持续验证'], "outlook": '10年后大概率仍在，但增速与回报中枢需理性预期'},
            "synthesis": {"rating": rating, "action": action, "position": position}}


def get_four_master(code, name, industry, price, pe, pb, roe, mcap, guba, news_label, trend):
    """优先深度版 JSON（WorkBuddy 手写），否则规则引擎。"""
    authored = os.path.join(ROOT, "data", "berkshire_analysis_%s.json" % code)
    if os.path.exists(authored):
        try:
            a = json.load(open(authored, encoding="utf-8"))
            return {"duan": {"score": a["duanyongping"]["score"],
                             "points": a["duanyongping"]["key_points"],
                             "concerns": a["duanyongping"]["concerns"]},
                    "buffett": {"score": a["buffett"]["score"],
                                "points": a["buffett"]["key_points"],
                                "concerns": a["buffett"]["concerns"],
                                "fair_value": json.dumps(a["buffett"]["fair_value_range"], ensure_ascii=False)},
                    "munger": {"score": a["munger"]["score"],
                               "points": a["munger"]["key_points"],
                               "concerns": a["munger"]["concerns"],
                               "death_scenarios": a["munger"]["death_scenarios"]},
                    "li": {"score": a["lilu"]["score"], "points": a["lilu"]["key_points"],
                           "concerns": a["lilu"]["concerns"], "outlook": a["lilu"]["ten_year_outlook"]},
                    "synthesis": {"rating": a["team_lead"]["overall_rating"],
                                  "action": a["team_lead"]["recommended_action"],
                                  "position": a["team_lead"]["position_suggestion"]}}
        except Exception:
            pass
    return four_master_py(code, name, industry, price, pe, pb, roe, mcap, guba, news_label, trend)


# ============================================================
# 8. 大盘（解析 daily_stock_analysis market_review）
# ============================================================
def get_market_overview():
    m = {"indices": [], "up_count": 0, "down_count": 0, "volume": "", "leading_sectors": []}
    drep = os.path.join(ROOT, "daily_stock_analysis", "reports")
    mrs = sorted(glob.glob(os.path.join(drep, "market_review_*.md")))
    if not mrs:
        return m
    txt = open(mrs[-1], encoding="utf-8").read()
    for row in re.findall(r"\|\s*(上证指数|深证成指|创业板指|科创50|上证50|沪深300)\s*\|\s*([\d.]+)\s*\|\s*[^\d|]*([+\-−\d.]+)%", txt):
        m["indices"].append({"name": row[0], "value": float(row[1]), "change": row[2] + "%"})
    up = re.search(r"上涨\s*/\s*下跌[^\d]*(\d+)\s*/\s*(\d+)", txt) or re.search(r"(\d+)\s*/\s*(\d+)\s*/\s*\d+", txt)
    if up:
        m["up_count"], m["down_count"] = int(up.group(1)), int(up.group(2))
    vol = re.search(r"成交额\s*\|\s*([\d.]+)\s*亿", txt)
    if vol:
        m["volume"] = vol.group(1) + "亿"
    sect = re.findall(r"\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*[^\d|]*([+\-−\d.]+)%", txt)
    m["leading_sectors"] = [{"rank": int(s[0]), "name": s[1].strip(), "change": s[2] + "%"} for s in sect[:5]]
    return m


# ============================================================
# 单股融合
# ============================================================
def _lexicon_score(texts):
    pos = sum(t.count(w) for t in texts for w in fetch_data.POS_WORDS)
    neg = sum(t.count(w) for t in texts for w in fetch_data.NEG_WORDS)
    tot = max(1, pos + neg + len(texts))
    return round((pos - neg) / tot * 50 + 50, 1)  # 0-100


def financial_metrics(code):
    """补抓 毛利率/净利率/资产负债率/ROE（akshare 东财财务摘要，最新一期）"""
    m = {"gross_margin": 0.0, "net_margin": 0.0, "debt_ratio": 0.0, "roe": 0.0}
    try:
        import akshare as ak
        df = ak.stock_financial_abstract(symbol=code)
        if len(df.columns) < 3 or "指标" not in df.columns:
            return m
        col = df.columns[2]  # 最新一期列（如 20260331）

        def pick(*keys):
            for k in keys:
                rows = df[df["指标"].astype(str).str.contains(k, na=False)]
                if len(rows):
                    try:
                        return round(float(rows.iloc[0][col]), 2)
                    except Exception:
                        return 0.0
            return 0.0
        m["gross_margin"] = pick("毛利率")
        m["net_margin"] = pick("净利率")
        m["debt_ratio"] = pick("资产负债率")
        m["roe"] = pick("净资产收益率")
    except Exception:
        pass
    return m


def build_stock(item):
    code, name, sector = item.get("code"), item.get("name", ""), item.get("sector", item.get("industry", ""))
    out = {"code": code, "name": name, "sector": sector, "price": 0, "change": "",
           "fundamental": {"pe": 0, "pb": 0, "roe": 0, "gross_margin": 0, "net_margin": 0, "debt_ratio": 0},
           "technical": {"signal": "", "chan_theory": {"bi_count": 0, "current_bi": "", "zs_count": 0,
                                                       "latest_signal": "", "buy_point": "", "score": 0, "suggestion": ""}},
           "factors": {"score": 0, "top_factors": []},
           "sentiment": {"news": [], "web_crawl": []},
           "ai_berkshire": None}
    try:  # 1 行情
        q = fetch_data.tencent_quote([code]).get(code, {})
        out["price"] = q.get("price", 0)
        out["change"] = ("%+.2f%%" % q.get("change_pct", 0)) if q.get("price") else ""
        out["fundamental"]["pe"] = q.get("pe_ttm", 0)
        out["fundamental"]["pb"] = q.get("pb", 0)
    except Exception:
        pass
    try:  # 基本面
        f = fetch_data.get_fundamental(code)
        if f.get("available"):
            out["fundamental"]["roe"] = f.get("roe", 0)
    except Exception:
        pass
    try:  # 1b 财务摘要（毛利率/净利率/负债率/ROE）
        fm = financial_metrics(code)
        out["fundamental"]["gross_margin"] = fm["gross_margin"]
        out["fundamental"]["net_margin"] = fm["net_margin"]
        out["fundamental"]["debt_ratio"] = fm["debt_ratio"]
        if not out["fundamental"]["roe"] and fm["roe"]:
            out["fundamental"]["roe"] = fm["roe"]
    except Exception:
        pass
    trend = "多头排列(ma20>ma60)"
    try:  # 2 K线 趋势
        kl = fetch_data.get_kline(code, 60)
        if kl.get("available") and len(kl["data"]) >= 30:
            closes = [float(x["close"]) for x in kl["data"]]
            ma20 = sum(closes[-20:]) / 20.0
            ma60 = sum(closes) / len(closes)
            trend = "多头排列(ma20>ma60)" if ma20 > ma60 else "空头排列(ma20<ma60)"
            out["technical"]["signal"] = trend
    except Exception:
        pass
    try:  # 3 资金流
        ff = fetch_data.fund_flow_120d(code)
        if ff.get("available"):
            out["fundamental"]["capital_flow_20d_yi"] = ff.get("recent20_main_net_yi", 0)
    except Exception:
        pass
    try:  # 4 缠论
        c = chan_analysis.analyze(code, 160)
        if c.get("available"):
            bp = c.get("buy_sell_points") or []
            out["technical"]["chan_theory"] = {"bi_count": c.get("bi_count", 0), "current_bi": "",
                                               "zs_count": len(c.get("zs_list", [])),
                                               "latest_signal": "、".join(bp) if bp else "无",
                                               "buy_point": "、".join([x for x in bp if "买" in x]) or "",
                                               "score": 0,
                                               "suggestion": "买入区间关注" if any("买" in x for x in bp) else (
                                                   "风险提示" if any("卖" in x for x in bp) else "中枢震荡观望")}
    except Exception:
        pass
    try:  # 5 因子
        fv = vibe_factor_score.score(code, 300)
        if fv.get("available"):
            out["factors"]["score"] = fv.get("composite_score", 0)
            out["factors"]["top_factors"] = [{"id": t.get("id"), "direction": t.get("direction"),
                                              "percentile": t.get("percentile")} for t in fv.get("top3", [])]
    except Exception:
        pass
    try:  # 6 新闻舆情
        n = fetch_data.eastmoney_news(code, 10)
        if n.get("available"):
            out["sentiment"]["news"] = [x["title"] for x in n["items"][:8]]
        cw = crawl_news.eastmoney_news(code, name)
        out["sentiment"]["web_crawl"] = [x["title"] for x in cw.get("items", [])[:5]]
    except Exception:
        pass
    try:  # 7 四大师
        nl = "中性"
        if out["sentiment"]["news"]:
            sc = _lexicon_score(out["sentiment"]["news"])
            nl = "偏多" if sc > 55 else ("偏空" if sc < 45 else "中性")
        mcap = 0
        try:
            mcap = fetch_data.tencent_quote([code]).get(code, {}).get("mcap_yi", 0) or 0
        except Exception:
            pass
        out["ai_berkshire"] = get_four_master(code, name, sector, out["price"],
                                              out["fundamental"]["pe"], out["fundamental"]["pb"],
                                              out["fundamental"]["roe"], mcap, 60, nl, trend)
    except Exception:
        out["ai_berkshire"] = None
    return out


# ============================================================
# 潜力股筛选
# ============================================================
def potential_filter(stocks):
    cands = []
    for s in stocks:
        pe, roe, price = s["fundamental"]["pe"], s["fundamental"]["roe"], s["price"]
        if not (pe and 0 < pe < 70):
            continue
        if roe and roe <= 5:  # ROE 数据缺失(0)时按受限处理，不拦截
            continue
        if not (price and price > 3):
            continue
        chan = s["technical"]["chan_theory"]
        tech = 50 + (20 if any(x in (chan.get("buy_point") or "") for x in ["买"]) else 0) \
               - (15 if any(x in (chan.get("latest_signal") or "") for x in ["卖"]) else 0) \
               + (10 if "多头" in s["technical"].get("signal", "") else (-10 if "空头" in s["technical"].get("signal", "") else 0))
        tech = max(0, min(100, tech))
        fund = (80 if pe <= 15 else 70 if pe <= 30 else 55 if pe <= 50 else 40) + (15 if roe and roe >= 20 else 10 if roe and roe >= 15 else 0)
        fac = s["factors"]["score"]
        masters = s.get("ai_berkshire") or {}
        master = 50
        if masters.get("synthesis"):
            master = round((masters["duan"]["score"] + masters["buffett"]["score"] +
                            masters["munger"]["score"] + masters["li"]["score"]) / 4)
        sent = 50
        if s["sentiment"]["news"]:
            sent = _lexicon_score(s["sentiment"]["news"])
        composite = round(tech * 0.25 + fund * 0.2 + fac * 0.2 + master * 0.25 + sent * 0.1, 1)
        tags = []
        if pe <= 20 and roe and roe >= 15:
            tags.append("价值型")
        if sent >= 55 and pe < 40:
            tags.append("成长型")
        if "多头" in s["technical"].get("signal", "") or (chan.get("buy_point")):
            tags.append("技术型")
        if (s.get("fundamental") or {}).get("capital_flow_20d_yi", 0) and s["fundamental"]["capital_flow_20d_yi"] > 0:
            tags.append("资金型")
        if chan.get("buy_point"):
            tags.append("缠论型")
        cands.append({"rank": 0, "code": s["code"], "name": s["name"], "sector": s["sector"],
                      "price": s["price"], "change": s["change"], "composite_score": composite,
                      "factor_tags": [t for t in tags if t in ("成长型", "技术型", "资金型")],
                      "value_tags": [t for t in tags if t == "价值型"],
                      "tech_tags": [t for t in tags if t == "缠论型"],
                      "reason": "综合%.1f（技术%d 基本面%d 因子%.0f 四大师%d 舆情%.0f）" % (composite, tech, fund, fac, master, sent)})
    cands.sort(key=lambda x: -x["composite_score"])
    for i, c in enumerate(cands[:8]):
        c["rank"] = i + 1
    return cands[:8]


# ============================================================
# 主流程
# ============================================================
def main():
    wl = json.load(open(os.path.join(ROOT, "config", "watchlist.json"), encoding="utf-8"))
    print("==> 开始融合 %d 只自选股 ..." % len(wl))
    stocks = [build_stock(item) for item in wl]
    market = get_market_overview()
    potential = potential_filter(stocks)
    # daily_review
    cls = crawl_news.cls_telegraph()
    msum = ("盘面信号见 daily 大盘复盘（market_review）" if market["indices"] else "大盘数据待 daily_stock_analysis 运行后补齐")
    report = {
        "generated_at": now_iso(),
        "market": market,
        "stocks": stocks,
        "potential_stocks": potential,
        "daily_review": {"market_summary": msum,
                         "key_events": [x.get("title", "") for x in cls.get("items", [])[:6]],
                         "tomorrow_outlook": []},
    }
    out = os.path.join(ROOT, "data", "report_data.json")
    json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n已生成: %s" % out)
    s0 = stocks[0]
    print("\n===== stocks[0] 概要（%s %s）=====" % (s0["code"], s0["name"]))
    print("  价格 %s | 涨跌 %s | PE %s | PB %s | ROE %s" % (
        s0["price"], s0["change"], s0["fundamental"]["pe"], s0["fundamental"]["pb"], s0["fundamental"]["roe"]))
    ct = s0["technical"]["chan_theory"]
    print("  技术: %s | 缠论 笔%d/中枢%d/信号%s/建议%s" % (
        s0["technical"]["signal"], ct["bi_count"], ct["zs_count"], ct["latest_signal"], ct["suggestion"]))
    print("  因子: 综合%.1f | Top:%s" % (s0["factors"]["score"], [t.get("id") for t in s0["factors"]["top_factors"]]))
    print("  新闻 %d 条 | 网页舆情 %d 条" % (len(s0["sentiment"]["news"]), len(s0["sentiment"]["web_crawl"])))
    ab = s0["ai_berkshire"] or {}
    if ab.get("synthesis"):
        print("  四大师: 段%d 巴%d 芒%d 李%d | 评级%s | %s | %s" % (
            ab["duan"]["score"], ab["buffett"]["score"], ab["munger"]["score"], ab["li"]["score"],
            ab["synthesis"]["rating"], ab["synthesis"]["action"], ab["synthesis"]["position"]))
    print("\n市场: 指数%d项 涨%s/跌%s 成交%s 板块%d条" % (
        len(market["indices"]), market["up_count"], market["down_count"], market["volume"], len(market["leading_sectors"])))
    print("潜力股 Top%d: %s" % (len(potential), "、".join("%s(%.1f)" % (p["name"], p["composite_score"]) for p in potential)))

    # 飞书推送（feishu.enabled=true 且 webhook 存在时）
    try:
        import feishu_notify
        wh = feishu_notify.get_webhook()
        enabled = True
        try:
            cfg = json.load(open(os.path.join(ROOT, "config", "settings.json"), encoding="utf-8"))
            enabled = (cfg.get("feishu") or {}).get("enabled", True)
        except Exception:
            pass
        if wh and enabled:
            print("==> 飞书推送（每日复盘 + 潜力股Top5 + 缠论信号 + 异动预警）...")
            for name, fn in [("每日复盘", feishu_notify.push_daily_review),
                             ("潜力股Top5", feishu_notify.push_potential_stocks)]:
                st, txt = fn(wh)
                print("   %s: %s %s" % (name, st, txt[:60]))
            ch = feishu_notify.push_chan_alerts(wh, report)
            print("   缠论信号: %s" % (ch if ch else "无买点信号"))
            mv = feishu_notify.push_move_alerts(wh, report, threshold=5.0)
            print("   异动预警: %s" % (mv if mv else "无异动(阈值5%)"))
        else:
            print("==> 飞书推送未启用（feishu.enabled=false 或未配置 FEISHU_WEBHOOK）")
    except Exception as e:
        print("==> 飞书推送跳过: %s" % str(e)[:80])


if __name__ == "__main__":
    main()
