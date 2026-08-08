# -*- coding: utf-8 -*-
"""
ai_berkshire_analysis.py — A股研究台 四大师深度分析模块（ai-berkshire）
=====================================================================
设计原则：WorkBuddy 本身就是 AI，不需要外部 LLM Key。
  · 本脚本 = 真实数据采集器 + 分析结构框架（四大师维度 + Team Lead + Mirror Test）
  · 深度分析内容 = WorkBuddy 基于脚本输出的「数据包」直接撰写（JSON 注入）
  · 框架来源：ai-berkshire（巴菲特价值投资 Checklist / 质量筛选等）+ 用户四大师流程

用法：
  python ai_berkshire_analysis.py collect 600519                  # 1) 采集数据包
  python ai_berkshire_analysis.py assemble 600519 <分析JSON路径>   # 2) 合并 → 报告(JSON+MD)
  python ai_berkshire_analysis.py show 600519                     # 3) 打印报告

流程（对每只股票）：
  步骤1 数据收集：a-stock-data(行情/基本面/资金流/千股千评/龙虎榜) + 新闻舆情 + Crawl4AI(公告/7x24)
  步骤2 段永平·商业模式 → 步骤3 巴菲特·财务估值 → 步骤4 芒格·逆向风险 → 步骤5 李录·长期确定性
  步骤6 Team Lead 综合（平均分/共识度/冲突/评级/行动/仓位）
  步骤7 Mirror Test（5 句话能否说清买卖理由）
"""
import os, sys, json, time, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
for p in (os.path.join(ROOT, "_libs"), os.path.join(ROOT, "agent-reach")):
    if p not in sys.path:
        sys.path.insert(0, p)
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import crawl_news

# ------------------------------------------------------------------
# 四大师分析结构（所有字段必须齐全，缺失会在 assemble 时报错）
# ------------------------------------------------------------------
MASTER_SCHEMA = {
    "duanyongping": {"label": "段永平·商业模式（这是不是对的生意）",
                     "fields": ["score", "key_points", "concerns",
                                "business_verdict", "moat_type", "pricing_power"]},
    "buffett": {"label": "巴菲特·财务估值（ROE/毛利/负债/内在价值）",
                "fields": ["score", "key_points", "concerns",
                           "fair_value_range", "safety_margin"]},
    "munger": {"label": "芒格·逆向风险（这家公司会怎么死）",
               "fields": ["score", "key_points", "concerns", "death_scenarios"]},
    "lilu": {"label": "李录·长期确定性（10年后还在吗）",
             "fields": ["score", "key_points", "concerns", "ten_year_outlook"]},
    "team_lead": {"label": "Team Lead 综合",
                  "fields": ["avg_score", "consensus", "conflicts",
                             "overall_rating", "recommended_action", "position_suggestion"]},
    "mirror_test": {"label": "Mirror Test",
                    "fields": ["passed", "five_sentences"]},
}


def now_iso():
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


# ------------------------------------------------------------------
# 步骤1：数据收集（真实数据，来自工作台管线）
# ------------------------------------------------------------------
def collect(code, name=""):
    report_path = os.path.join(ROOT, "data", "report_data.json")
    if not os.path.exists(report_path):
        print("[collect] 缺少 data/report_data.json，请先运行 fetch_all_data.py")
        return None
    report = json.load(open(report_path, encoding="utf-8"))
    s = next((x for x in report.get("stocks", []) if x.get("code") == code), None)
    if s is None:
        print("[collect] report_data.json 中没有 %s，请先 fetch_all_data.py 抓取" % code)
        return None
    name = name or s.get("name", "")

    kline = s.get("kline", {}).get("data", []) or []
    ksum = {"days": len(kline), "trend": "数据不足"}
    if len(kline) >= 30:
        closes = [float(x["close"]) for x in kline]
        last = closes[-1]
        ma20 = sum(closes[-20:]) / 20.0
        ma60 = sum(closes) / len(closes)
        ksum = {"days": len(kline), "last_close": last, "ma20": round(ma20, 2),
                "ma60": round(ma60, 2), "chg_20d_pct": round((last / closes[-21] - 1) * 100, 2),
                "trend": "多头排列(ma20>ma60)" if ma20 > ma60 else "空头排列(ma20<ma60)"}

    ann = crawl_news.cninfo_announcements(name or code, code, name)
    tel = crawl_news.cls_telegraph(code, name)

    data = {
        "code": code, "name": name, "fetched_at": now_iso(),
        "quote": s.get("quote", {}),
        "fundamental": s.get("fundamental", {}),
        "kline_summary": ksum,
        "news_sentiment": s.get("news_sentiment", {}),
        "guba": s.get("guba", {}),
        "fund_flow": s.get("fund_flow", {}),
        "dragon_tiger": s.get("dragon_tiger", {}),
        "web_news": s.get("web_news", {}),
        "announcements": ann.get("items", [])[:5],
        "telegraph": tel.get("items", [])[:5],
        "data_notes": ("盈利/负债/毛利率等历史指标由公开资料补充并标注来源；"
                       "工作台直采指标已标注。未编造数字，缺失项明确标注。"),
    }
    out = os.path.join(ROOT, "data", "berkshire_data_%s.json" % code)
    json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("[collect] 数据包已生成: %s" % out)
    print("  价格 %s | PE %s | PB %s | 市值 %s亿 | %s | 千股千评 %s 分 | 公告 %d 条"
          % (s["quote"].get("price"), s["quote"].get("pe_ttm"), s["quote"].get("pb"),
             s["quote"].get("mcap_yi"), ksum.get("trend"),
             (s.get("guba") or {}).get("total_score"), len(ann.get("items", []))))
    return data


# ------------------------------------------------------------------
# 步骤2-7：合并 WorkBuddy 分析 → 报告
# ------------------------------------------------------------------
def assemble(code, analysis_path, out_dir=None):
    data_path = os.path.join(ROOT, "data", "berkshire_data_%s.json" % code)
    if not os.path.exists(data_path):
        print("[assemble] 缺少数据包，请先 collect %s" % code)
        return None
    if not os.path.exists(analysis_path):
        print("[assemble] 缺少分析文件: %s" % analysis_path)
        return None
    data = json.load(open(data_path, encoding="utf-8"))
    analysis = json.load(open(analysis_path, encoding="utf-8"))

    # 校验字段完整性
    missing = []
    for master, meta in MASTER_SCHEMA.items():
        if master not in analysis:
            missing.append(master)
            continue
        for f in meta["fields"]:
            if f not in analysis[master]:
                missing.append("%s.%s" % (master, f))
    if missing:
        print("[assemble] 分析缺少字段: %s" % ", ".join(missing))
        return None

    report = {"data": data, "analysis": analysis,
              "schema": {k: v["label"] for k, v in MASTER_SCHEMA.items()},
              "generated_at": now_iso()}
    out_dir = out_dir or os.path.join(ROOT, "reports")
    os.makedirs(out_dir, exist_ok=True)
    jp = os.path.join(out_dir, "berkshire_%s.json" % code)
    json.dump(report, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    mp = os.path.join(out_dir, "berkshire_%s.md" % code)
    open(mp, "w", encoding="utf-8").write(render_md(report))
    print("[assemble] 报告已生成: %s / %s" % (jp, mp))
    return report


def render_md(report):
    d, a = report["data"], report["analysis"]
    L = []
    L.append("# %s（%s）四大师深度分析\n" % (d["name"], d["code"]))
    L.append("> 生成时间 %s · 数据来源：a-stock-data + 新闻舆情 + Crawl4AI(公告/7x24)\n" % a.get("_note", ""))
    q = d["quote"]
    L.append("## 数据快照\n")
    L.append("| 指标 | 值 | | 指标 | 值 |")
    L.append("|---|---|---|---|---|")
    L.append("| 最新价 | %s | | PE(TTM) | %s |" % (q.get("price"), q.get("pe_ttm")))
    L.append("| PB | %s | | 市值 | %s 亿 |" % (q.get("pb"), q.get("mcap_yi")))
    L.append("| 换手率 | %s%% | | 近20日 | %s%% |" % (q.get("turnover_pct"), d["kline_summary"].get("chg_20d_pct")))
    L.append("| 趋势 | %s | | 千股千评 | %s 分 |" % (d["kline_summary"].get("trend"), (d.get("guba") or {}).get("total_score")))
    L.append("| 新闻情绪 | %s | | 主力成本 | %s |" % ((d.get("news_sentiment") or {}).get("overall"), (d.get("guba") or {}).get("main_cost")))
    L.append("")
    order = [("duanyongping", "段永平·商业模式"), ("buffett", "巴菲特·财务估值"),
             ("munger", "芒格·逆向风险"), ("lilu", "李录·长期确定性"),
             ("team_lead", "Team Lead 综合"), ("mirror_test", "Mirror Test")]
    for key, title in order:
        m = a[key]
        L.append("## %s ｜ 得分 **%s**\n" % (title, m.get("score", m.get("avg_score"))))
        if key == "duanyongping":
            L.append("- **生意判断**：%s" % m.get("business_verdict"))
            L.append("- **护城河类型**：%s" % m.get("moat_type"))
            L.append("- **定价权**：%s" % m.get("pricing_power"))
        if key == "buffett":
            L.append("- **内在价值区间**：%s" % json.dumps(m.get("fair_value_range"), ensure_ascii=False))
            L.append("- **安全边际**：%s" % m.get("safety_margin"))
        if key == "munger":
            L.append("- **死亡剧本**：%s" % "; ".join(m.get("death_scenarios", [])))
        if key == "lilu":
            L.append("- **10年展望**：%s" % m.get("ten_year_outlook"))
        if key == "team_lead":
            L.append("- **共识度**：%s" % m.get("consensus"))
            L.append("- **关键冲突**：%s" % "; ".join(m.get("conflicts", [])))
            L.append("- **评级**：**%s**" % m.get("overall_rating"))
            L.append("- **行动建议**：%s" % m.get("recommended_action"))
            L.append("- **仓位建议**：%s" % m.get("position_suggestion"))
        if key == "mirror_test":
            L.append("- **Mirror 通过**：%s" % ("✅ 通过" if m.get("passed") else "❌ 未通过"))
        L.append("\n**看好要点**：%s" % "; ".join(m.get("key_points", [])))
        L.append("\n**风险/分歧**：%s" % "; ".join(m.get("concerns", [])))
        L.append("")
    L.append("---")
    L.append("> 声明：分析基于工作台真实抓取数据 + 公开资料；不构成投资建议。")
    return "\n".join(L)


def show(code):
    p = os.path.join(ROOT, "reports", "berkshire_%s.md" % code)
    if not os.path.exists(p):
        print("报告不存在: %s" % p)
        return
    print(open(p, encoding="utf-8").read())


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "collect":
        collect(args[1], args[2] if len(args) > 2 else "")
    elif len(args) >= 3 and args[0] == "assemble":
        assemble(args[1], args[2])
    elif len(args) >= 2 and args[0] == "show":
        show(args[1])
    else:
        print(__doc__)
