# -*- coding: utf-8 -*-
"""
feishu_notify.py — A股研究台 飞书推送（interactive card）
==========================================================
功能：读取 data/report_data.json → 生成飞书卡片 → Webhook 推送
支持模式：
    --mode full      每日复盘 + 完整潜力股日报（18:05 用）
    --mode morning   潜力股早报 Top3（08:30 用，精简版，读昨日报告）
    --mode test      测试消息

Webhook 读取顺序：
    1. 环境变量 FEISHU_WEBHOOK
    2. config/settings.json 的 feishu.webhook_url（支持 "${FEISHU_WEBHOOK}" 占位展开）
安全：Webhook 绝不硬编码；不在 .env 中保存明文。

用法：
    FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx python scripts/feishu_notify.py --mode test
"""
import os, sys, json, datetime, argparse

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
for p in (os.path.join(ROOT, "_libs"),):
    if p not in sys.path:
        sys.path.insert(0, p)
import requests  # noqa: E402


def get_webhook():
    """返回 webhook 或 None。环境变量优先，其次 settings.json（展开 ${ENV} 占位）。"""
    wh = os.getenv("FEISHU_WEBHOOK", "").strip()
    if wh:
        return wh
    try:
        cfg = json.load(open(os.path.join(ROOT, "config", "settings.json"), encoding="utf-8"))
        wh = (cfg.get("feishu") or {}).get("webhook_url", "") or ""
        # 展开 ${FEISHU_WEBHOOK}
        wh = re.sub(r"\$\{([^}]+)\}", lambda m: os.getenv(m.group(1), ""), wh)
        return wh.strip() or None
    except Exception:
        return None


def load_report():
    p = os.path.join(ROOT, "data", "report_data.json")
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def send(webhook, card):
    r = requests.post(webhook, json={"msg_type": "interactive", "card": card},
                      headers={"Content-Type": "application/json"}, timeout=15)
    return r.status_code, r.text[:200]


def _today():
    d = datetime.date.today()
    return "%d月%d日" % (d.month, d.day)


def _rating_advice(rating):
    if not rating:
        return "关注"
    if "通过" in rating:
        return "关注"
    if "不通过" in rating:
        return "回避"
    return "观察"


def _tag_str(p):
    return "、".join((p.get("factor_tags") or []) + (p.get("value_tags") or []) + (p.get("tech_tags") or [])) or "—"


# ============================================================
# 1. 每日复盘（18:05）
# ============================================================
def build_daily_review(report):
    mkt = report.get("market", {})
    elems = []
    indices = (mkt.get("indices") or [])[:4]
    if indices:
        md = "".join("**%s** %s (%s)\n" % (i.get("name"), i.get("value"), i.get("change")) for i in indices)
        elems.append({"tag": "div", "text": {"tag": "lark_md", "content": "**指数**\n" + md}})
    dr = report.get("daily_review", {})
    elems.append({"tag": "div", "text": {"tag": "lark_md",
                  "content": "**涨跌** 上涨 %s / 下跌 %s ｜ **成交** %s\n%s" % (
                      mkt.get("up_count"), mkt.get("down_count"), mkt.get("volume"),
                      dr.get("market_summary", "")[:80])}})
    sec = (mkt.get("leading_sectors") or [])[:3]
    if sec:
        elems.append({"tag": "div", "text": {"tag": "lark_md",
                      "content": "**领涨板块** " + "、".join("%s(%s)" % (s.get("name"), s.get("change")) for s in sec)}})
    events = (dr.get("key_events") or [])[:3]
    if events:
        elems.append({"tag": "div", "text": {"tag": "lark_md", "content": "**要闻**\n" + "\n".join("· " + e[:60] for e in events)}})
    elems.append({"tag": "note", "elements": [{"tag": "plain_text", "content": "A股研究台 · 每日 18:05 自动推送"}]})
    return {"config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "📋 每日复盘 - %s" % _today()}, "template": "blue"},
            "elements": elems}


# ============================================================
# 2. 完整潜力股日报（18:05）
# ============================================================
def build_potential_full(report):
    pot = report.get("potential_stocks") or []
    elems = []
    if not pot:
        elems.append({"tag": "div", "text": {"tag": "lark_md", "content": "今日无满足筛选条件的潜力股"}})
    for p in pot[:8]:
        elems.append({"tag": "div", "text": {"tag": "lark_md", "content":
                      "**%d. %s** %s\n💰 %s ｜ ⭐ 综合 %.1f ｜ 🏷️ %s" % (
                          p.get("rank"), p.get("name"), p.get("code"),
                          p.get("price"), p.get("composite_score", 0), _tag_str(p))}})
        elems.append({"tag": "hr"})
    elems.append({"tag": "note", "elements": [{"tag": "plain_text", "content": "基于收盘数据，开盘请结合实时走势判断"}]})
    return {"config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "⭐ 潜力股日报 - %s" % _today()}, "template": "blue"},
            "elements": elems}


# ============================================================
# 3. 潜力股早报 Top3（08:30，精简）
# ============================================================
def build_morning_brief(report):
    pot = (report.get("potential_stocks") or [])[:3]
    elems = []
    if not pot:
        elems.append({"tag": "div", "text": {"tag": "lark_md", "content": "今日无满足筛选条件的潜力股"}})
    for p in pot:
        elems.append({"tag": "div", "text": {"tag": "lark_md", "content":
                      "**%d. %s** %s\n💰 %s  |  🏷️ %s\n👉 建议：%s" % (
                          p.get("rank"), p.get("name"), p.get("code"),
                          p.get("price"), _tag_str(p), _rating_advice(p.get("rating")) if p.get("rating") else "关注")}})
        elems.append({"tag": "hr"})
    elems.append({"tag": "note", "elements": [{"tag": "plain_text", "content": "基于昨日收盘数据，开盘请结合实时走势判断"}]})
    return {"config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "⭐ 今日潜力股早报 - %s" % _today()}, "template": "orange"},
            "elements": elems}


# ============================================================
# 4. 异动预警（预留）
# ============================================================
def build_alert(code, alert_type, message):
    return {"config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "🚨 异动预警 %s · %s" % (code, alert_type)}, "template": "orange"},
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": message}},
                         {"tag": "note", "elements": [{"tag": "plain_text", "content": "A股研究台自动监控"}]}]}


# ============================================================
# 推送函数
# ============================================================
def push_daily_review(webhook=None):
    wh = webhook or get_webhook()
    rep = load_report()
    if not rep:
        return "report_data.json 不存在，跳过"
    return send(wh, build_daily_review(rep))


def push_potential_full(webhook=None):
    wh = webhook or get_webhook()
    rep = load_report()
    if not rep:
        return "report_data.json 不存在，跳过"
    return send(wh, build_potential_full(rep))


def push_morning_brief(webhook=None):
    wh = webhook or get_webhook()
    rep = load_report()
    if not rep:
        return "report_data.json 不存在，跳过"
    return send(wh, build_morning_brief(rep))


def push_alert(webhook, code, alert_type, message):
    return send(webhook, build_alert(code, alert_type, message))


def main():
    ap = argparse.ArgumentParser(description="飞书推送（A股研究台）")
    ap.add_argument("--mode", choices=["full", "morning", "test"], default="full")
    ap.add_argument("--webhook", default=None, help="直接指定 Webhook（不指定则用环境变量/settings）")
    args = ap.parse_args()
    wh = args.webhook or get_webhook()
    if not wh:
        print("未找到 FEISHU_WEBHOOK（环境变量或 settings.json feishu.webhook_url）")
        return 1
    if args.mode == "test":
        card = {"config": {"wide_screen_mode": True},
                "header": {"title": {"tag": "plain_text", "content": "✅ 测试消息 - A股研究台"}, "template": "blue"},
                "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "飞书推送链路正常 ✅"}},
                             {"tag": "note", "elements": [{"tag": "plain_text", "content": "本消息由本地测试发送"}]}]}
        st, txt = send(wh, card)
        print("测试推送:", st, txt[:120])
        return 0 if st == 200 else 1
    if args.mode == "full":
        for name, fn in [("每日复盘", push_daily_review), ("潜力股日报", push_potential_full)]:
            st, txt = fn(wh)
            print("%s推送: %s %s" % (name, st, txt[:80]))
        return 0
    st, txt = push_morning_brief(wh)
    print("早报推送: %s %s" % (st, txt[:80]))
    return 0


if __name__ == "__main__":
    import re  # noqa: E402（用于 ${ENV} 展开）
    sys.exit(main())
