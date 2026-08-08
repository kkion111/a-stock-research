# -*- coding: utf-8 -*-
"""
live_server.py — A股研究台 实时服务器
  · 静态托管 app/（index.html / report_data.json）
  · GET /api/7x24  → 服务端代理 新浪7x24 快讯（绕开浏览器 CORS）
  · 统一加 CORS: *，方便页面直连东财人气榜等允许跨域的接口
用法: python live_server.py [端口]   （默认 8088）
"""
import http.server, socketserver, urllib.request, urllib.parse, json, os, sys, shutil, threading

BASE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(BASE, "..", "app")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8088
_CHAN_LOCK = threading.Lock()
SINA = ("https://zhibo.sina.com.cn/api/zhibo/feed?"
        "page=1&page_size=12&zhibo_id=152&tag_id=0&dire=f&dpc=1")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=APP, **kw)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        p = self.path
        if p.startswith("/api/7x24"):
            try:
                req = urllib.request.Request(SINA, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=12) as r:
                    body = r.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(502)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return
        if p.startswith("/api/quote"):
            self.do_quote()
            return
        if p.startswith("/api/watchlist"):
            self.do_watchlist()
            return
        if p.startswith("/api/chan"):
            self.do_chan()
            return
        if p.startswith("/api/vibe"):
            self.do_vibe()
            return
        super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/watchlist"):
            self.do_watchlist()
            return
        self.send_response(404)
        self.end_headers()

    def do_watchlist(self):
        """GET /api/watchlist 读自选；POST /api/watchlist body={"items":[{code,name,industry}]} 写自选"""
        wl = os.path.join(BASE, "..", "config", "watchlist.json")
        try:
            data = json.load(open(wl, encoding="utf-8"))
        except Exception:
            data = []
        if self.command == "GET":
            body = json.dumps({"items": data}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            return
        # POST：保存 items
        try:
            ln = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(ln).decode("utf-8") or "{}")
            items = req.get("items")
            if not isinstance(items, list):
                raise ValueError("items 必须为数组")
            json.dump(items, open(wl, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "count": len(items)}).encode("utf-8"))
        except Exception as e:
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

    def do_quote(self):
        """腾讯行情代理：/api/quote?codes=600519,000001 → {codes:{code:{name,price,change_pct,pe_ttm,pb,...}}}"""
        import urllib.parse as up
        qs = up.parse_qs(up.urlparse(self.path).query)
        codes = (qs.get("codes") or [""])[0].split(",")
        prefixed = []
        for c in codes:
            c = c.strip().lower()
            if not c:
                continue
            if c.startswith(("sh", "sz", "bj")):
                prefixed.append(c)
            elif c.startswith(("5", "6", "9")):
                prefixed.append("sh" + c)
            else:
                prefixed.append("sz" + c)
        out = {}
        if prefixed:
            try:
                url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                raw = urllib.request.urlopen(req, timeout=10).read().decode("gbk", "ignore")
                for line in raw.strip().split(";"):
                    if "=" not in line or '"' not in line:
                        continue
                    key = line.split("=")[0].split("_")[-1]
                    v = line.split('"')[1].split("~")
                    if len(v) < 47:
                        continue
                    out[key] = {"name": v[1], "price": self._f(v[3]), "prev_close": self._f(v[4]),
                                "open": self._f(v[5]), "change_amt": self._f(v[31]),
                                "change_pct": self._f(v[32]), "high": self._f(v[33]),
                                "low": self._f(v[34]), "amount_wan": self._f(v[37]),
                                "turnover_pct": self._f(v[38]), "pe_ttm": self._f(v[39]),
                                "mcap_yi": self._f(v[45]), "pb": self._f(v[46])}
            except Exception as e:
                self.send_response(502)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                return
        body = json.dumps({"codes": out}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _f(s):
        try:
            return float(s)
        except Exception:
            return 0.0

    def do_chan(self):
        """GET /api/chan?code=600519 → 即时跑 czsc 缠论（新浪K线，约5-15秒），保存 data+app/chan_<code>.json"""
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = (qs.get("code") or [""])[0].strip()
        if not code or not code.isdigit() or len(code) != 6:
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "code 必须为6位数字"}).encode("utf-8"))
            return
        with _CHAN_LOCK:
            try:
                sys.path.insert(0, os.path.join(BASE, "..", "_libs"))
                if BASE not in sys.path:
                    sys.path.insert(0, BASE)
                import chan_analysis
                r = chan_analysis.analyze(code, 160)
                if r.get("available"):
                    fp = os.path.join(BASE, "..", "data", "chan_%s.json" % code)
                    json.dump(r, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                    shutil.copy2(fp, os.path.join(APP, "chan_%s.json" % code))
                body = json.dumps(r, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"code": code, "available": False,
                                             "reason": "%s: %s" % (type(e).__name__, str(e)[:100])}).encode("utf-8"))

    def do_vibe(self):
        """GET /api/vibe?code=600519 → 即时 Vibe-Trading 因子评分，保存 data+app/vibe_factor_<code>.json"""
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = (qs.get("code") or [""])[0].strip()
        if not code or not code.isdigit() or len(code) != 6:
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "code 必须为6位数字"}).encode("utf-8"))
            return
        with _CHAN_LOCK:
            try:
                sys.path.insert(0, os.path.join(BASE, "..", "_libs"))
                if BASE not in sys.path:
                    sys.path.insert(0, BASE)
                import vibe_factor_score
                r = vibe_factor_score.score(code, 300)
                if r.get("available"):
                    fp = os.path.join(BASE, "..", "data", "vibe_factor_%s.json" % code)
                    json.dump(r, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                    shutil.copy2(fp, os.path.join(APP, "vibe_factor_%s.json" % code))
                body = json.dumps(r, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"code": code, "available": False,
                                             "reason": "%s: %s" % (type(e).__name__, str(e)[:100])}).encode("utf-8"))

    def log_message(self, *a):
        pass


socketserver.TCPServer.allow_reuse_address = True
with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), H) as httpd:
    print("[live_server] port=%d dir=%s" % (PORT, APP), flush=True)
    httpd.serve_forever()
