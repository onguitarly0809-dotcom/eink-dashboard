# -*- coding: utf-8 -*-
"""Web 控制台的来源校验与数据面板测试（离线：真实动作一律打桩，不读运营缓存）。

覆盖 2026-11 审计的三项：
- 监听局域网却不校验请求来源：跨站 POST（CSRF）与 DNS 重绑定应被拒绝，
  本机热键服务那种直连请求必须照常放行；
- 数据看板的板块热点读的是缓存里早已无人更新的 markets.sectors 化石；
- 新闻列表拿精华行当键查摘要、拿标题和布尔值比置顶，摘要和角标从未显示。
"""
import importlib
import json
import os
import shutil
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: F401

REPO = Path(__file__).resolve().parent.parent
APP_JS = {"landscape": "dashboard_serial_landscape", "portrait": "dashboard_serial"}
JSON = {"Content-Type": "application/json"}

# 交给 node 执行的断言脚本：从标准输入拿到 app.js 源码，截出 newsListHtml() 单独验证
# （不加载整个页面脚本，也不让 JS 侧读任何文件）。
NEWS_LIST_HARNESS = r"""
const chunks = [];
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => chunks.push(chunk));
process.stdin.on('end', () => {
  const src = chunks.join('');
  const start = src.indexOf('function newsListHtml(');
  const end = src.indexOf('function renderData(', start);
  if (start < 0 || end < 0) {
    console.error('newsListHtml not found');
    process.exit(2);
  }
  const esc = s => String(s ?? '').replace(/[&<>"']/g,
    c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const newsListHtml = new Function('esc', src.slice(start, end) + '\nreturn newsListHtml;')(esc);
  let failed = 0;
  const check = (cond, label) => {
    console.log((cond ? 'PASS  ' : 'FAIL  ') + label);
    if (!cond) failed += 1;
  };
  const n = {
    domestic: ['合成置顶标题丙', '合成精华行甲', '合成原始标题乙'],
    domestic_pinned: true,
    domestic_badge: '价',
    domestic_items: [
      {title: '合成置顶标题丙', summary: '', pinned: true},
      {title: '合成原始标题甲', summary: '合成精华行甲', pinned: false},
      {title: '合成<b>原始</b>标题乙', summary: '', pinned: false},
    ],
  };
  const html = newsListHtml(n, 'domestic');
  check((html.match(/class="news-item/g) || []).length === 3, 'three items');
  check(html.split('class="news-item pin"').length - 1 === 1, 'exactly one pinned item');
  check(html.includes('<span class="badge">价</span>合成置顶标题丙'), 'pinned item shows the configured badge');
  check(html.includes('<div class="t">合成原始标题甲</div>\n        <div class="s">合成精华行甲</div>'),
    'original title followed by its summary line');
  check(html.includes('&lt;b&gt;'), 'title is html-escaped');
  check(!html.includes('<b>'), 'no raw markup injected');
  const legacy = newsListHtml({international: ['合成旧标题'], international_pinned: false}, 'international');
  check(legacy.includes('<div class="t">合成旧标题</div>') && !legacy.includes('badge'),
    'legacy payload renders plain titles');
  const legacyPin = newsListHtml({ai: ['合成旧甲', '合成旧乙'], ai_pinned: true, ai_badge: '价'}, 'ai');
  check(legacyPin.split('class="news-item pin"').length - 1 === 1 &&
    legacyPin.includes('<span class="badge">价</span>合成旧甲'), 'legacy payload marks the pinned first row');
  check(newsListHtml({}, 'ai') === '', 'missing band renders an empty list');
  check(newsListHtml({ai: 'not-a-list', ai_pinned: true}, 'ai') === '', 'corrupt band renders an empty list');
  check(newsListHtml({ai: 'not-a-list', ai_items: [null, 'x', {title: 'T'}]}, 'ai').includes('>T<'),
    'malformed entries do not throw');
  process.exit(failed ? 1 : 0);
});
"""


class _WebCase(unittest.TestCase):
    def setUp(self):
        # 合跑时别的用例会在运行期切换变体，这里每个用例都重新按横版取当前模块对象
        _env.force_variant("landscape")
        self.web = importlib.import_module("epd_dashboard.web")


class RequestOriginTest(_WebCase):
    def test_only_plain_hosts_are_trusted(self):
        allowed = self.web._host_allowed
        for host in ("192.0.2.5:8080", "127.0.0.1:8080", "localhost:8080", "epd.local",
                     "DESKTOP-ABC:8080", "[::1]:8080", "10.0.0.2"):
            with self.subTest(host=host):
                self.assertTrue(allowed(host))
        for host in ("evil.example", "evil.example:8080", "epd.lan", "a.b", "localhost.evil.example",
                     "192.0.2.5.evil.example", "", None):
            with self.subTest(host=host):
                self.assertFalse(allowed(host))

    def test_env_switch_reopens_domain_hosts(self):
        with mock.patch.dict(os.environ, {"EPD_WEB_ALLOW_ANY_HOST": "1"}):
            self.assertTrue(self.web._host_allowed("epd.lan"))

    def test_same_origin_ignores_scheme_but_not_host_or_port(self):
        same = self.web._same_origin
        for origin, host, expected in (
                ("http://192.0.2.5:8080", "192.0.2.5:8080", True),
                ("https://192.0.2.5:8080", "192.0.2.5:8080", True),
                ("HTTP://LOCALHOST:8080", "localhost:8080", True),
                ("http://192.0.2.5:8081", "192.0.2.5:8080", False),
                ("http://192.0.2.6:8080", "192.0.2.5:8080", False),
                ("http://evil.example", "192.0.2.5:8080", False),
                ("null", "192.0.2.5:8080", False),
                ("", "192.0.2.5:8080", False),
                ("file://", "192.0.2.5:8080", False)):
            with self.subTest(origin=origin, host=host):
                self.assertIs(same(origin, host), expected)

    def test_post_rules(self):
        reject = self.web._post_rejection
        host = "192.0.2.5:8080"
        self.assertIsNone(reject({"Host": host, "Origin": f"http://{host}",
                                  "Content-Type": "application/json"}))
        self.assertIsNone(reject({"Host": host, "Content-Type": "application/json; charset=utf-8"}))
        self.assertIsNone(reject({"Host": host, "Content-Type": "APPLICATION/JSON"}))
        for headers in ({"Host": host, "Origin": "http://evil.example", "Content-Type": "application/json"},
                        {"Host": host, "Origin": "null", "Content-Type": "application/json"},
                        {"Host": host, "Origin": f"http://{host}", "Content-Type": "application/json",
                         "Sec-Fetch-Site": "cross-site"},
                        {"Host": host, "Content-Type": "text/plain"},
                        {"Host": host, "Content-Type": "application/x-www-form-urlencoded"},
                        {"Host": host, "Content-Type": "multipart/form-data; boundary=x"},
                        {"Host": host},
                        {"Host": host, "Origin": "http://evil.example"}):
            with self.subTest(headers=headers):
                self.assertIsNotNone(reject(headers))


class HttpBoundaryTest(_WebCase):
    """起一个真实的控制台实例（回环地址、临时端口）；触发动作的 run_action 打桩。"""

    def setUp(self):
        super().setUp()
        self.run_action = mock.Mock(return_value=True)
        patcher = mock.patch.object(self.web, "run_action", self.run_action)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.web.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)      # 清理按后进先出：先 shutdown 再关 socket
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_port
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 不走系统代理

    def _request(self, method, path, headers=None, body=None, host=None):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=body,
                                         method=method, headers=dict(headers or {}))
        if host is not None:
            request.add_unredirected_header("Host", host)
        try:
            with self.opener.open(request, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()

    def test_page_and_local_posts_are_served(self):
        status, body = self._request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", body.lower())
        for host in (f"localhost:{self.port}", "127.0.0.1", "epd.local"):
            with self.subTest(host=host):
                self.assertEqual(self._request("GET", "/app.js", host=host)[0], 200)
        # 热键服务的请求形态：直连 127.0.0.1、JSON 体、不带 Origin
        status, body = self._request("POST", "/api/action", JSON,
                                     json.dumps({"action": "clear"}).encode())
        self.assertEqual((status, json.loads(body)["ok"]), (200, True))
        self.run_action.assert_called_once_with("clear", pattern=None, force=False)
        # 浏览器同源请求：Origin 与访问地址一致
        lan = f"192.0.2.5:{self.port}"
        headers = dict(JSON, Origin=f"http://{lan}", **{"Sec-Fetch-Site": "same-origin"})
        status, body = self._request("POST", "/api/action", headers,
                                     json.dumps({"action": "page3", "force": True}).encode(), host=lan)
        self.assertEqual((status, json.loads(body)["ok"]), (200, True))
        self.run_action.assert_called_with("page3", pattern=None, force=True)
        status, body = self._request("POST", "/api/plans", JSON,
                                     json.dumps({"items": ["合成计划甲"]}).encode())
        self.assertEqual(status, 200)
        self.run_action.assert_called_with("plans", planstext="合成计划甲")

    def test_cross_site_posts_are_rejected_before_any_action_runs(self):
        action = json.dumps({"action": "clear"}).encode()
        lan = f"192.0.2.5:{self.port}"
        cases = {
            "foreign origin": (dict(JSON, Origin="http://evil.example"), None),
            "other port": (dict(JSON, Origin="http://192.0.2.5:3000"), None),
            "null origin": (dict(JSON, Origin="null"), None),
            "fetch-site cross-site": (dict(JSON, Origin=f"http://{lan}",
                                           **{"Sec-Fetch-Site": "cross-site"}), lan),
            "form post": ({"Content-Type": "application/x-www-form-urlencoded"}, None),
            "text body": ({"Content-Type": "text/plain"}, None),
            "no content type": ({}, None),
            "dns rebinding host": (dict(JSON, Origin="http://evil.example:8080"), "evil.example:8080"),
        }
        for label, (headers, host) in cases.items():
            with self.subTest(label):
                status, body = self._request("POST", "/api/action", headers, action, host=host)
                self.assertEqual(status, 403)
                self.assertFalse(json.loads(body)["ok"])
        self.run_action.assert_not_called()

    def test_reads_are_blocked_for_domain_hosts(self):
        status, body = self._request("GET", "/", host="evil.example")
        self.assertEqual((status, json.loads(body)["ok"]), (403, False))
        self.assertEqual(self._request("GET", "/api/nothing")[0], 404)
        self.assertEqual(self._request("POST", "/api/nothing", JSON, b"{}")[0], 404)

    def test_children_do_not_inherit_the_variant_setting(self):
        with mock.patch.dict(os.environ, {"EPD_VARIANT": "portrait", "EPD_BASE_DIR": "x",
                                          "EPD_KEEP": "1"}):
            env = self.web._child_env()
        self.assertEqual(env["EPD_KEEP"], "1")
        self.assertNotIn("EPD_VARIANT", env)
        self.assertNotIn("EPD_BASE_DIR", env)


class DataPanelTest(_WebCase):
    def _payload(self, cache):
        with mock.patch.object(self.web, "_read_cache", return_value=cache):
            return self.web.data_payload()

    def test_sector_hotspots_come_from_raw_sectors_not_the_fossil(self):
        payload = self._payload({"markets": {
            # 早期版本留下的化石字段：内容再"好看"也不能被采用
            "sectors": {"hot": [{"name": "化石板块", "pct": 9.99}],
                        "fall": [{"name": "化石板块", "pct": -9.99}]},
            "raw_sectors": [
                {"name": "甲", "zdf": "2.47"}, {"name": "乙", "zdf": "-0.56"},
                {"name": "丙", "zdf": "1.84%"}, {"name": "丁", "zdf": "--"},
                {"name": "戊", "zdf": 0.31}, {"name": "己", "zdf": "-1.2"},
                {"name": "庚", "zdf": "-0.02"}, {"name": "辛", "zdf": "0.4"}, "garbage",
            ],
        }})["markets"]
        self.assertEqual([s["name"] for s in payload["sectors"]["hot"]], ["甲", "丙", "辛"])
        self.assertEqual([s["pct"] for s in payload["sectors"]["hot"]], [2.47, 1.84, 0.4])
        self.assertEqual([s["name"] for s in payload["sectors"]["fall"]], ["己", "乙", "庚"])
        self.assertNotIn("化石板块", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn("raw_sectors", payload)                  # 带领涨股的原始大表不下发
        few = self._payload({"markets": {"raw_sectors": [{"name": "甲", "zdf": "1"}]}})["markets"]
        self.assertEqual(few["sectors"], {"hot": [{"name": "甲", "pct": 1.0}], "fall": []})
        self.assertEqual(self._payload({})["markets"]["sectors"], {"hot": [], "fall": []})

    def test_news_entries_carry_original_title_summary_and_pin(self):
        news = self._payload({"news": {
            "domestic": ["合成置顶标题丙", "合成精华行甲", "合成原始标题乙"],
            "domestic_pinned": True, "domestic_badge": "价",
            "ai": ["合成精华行甲", "合成标题丁"], "ai_pinned": False,
            "summaries": {"合成原始标题甲": "合成精华行甲", "出栏旧标题": "合成旧精华行"},
        }})["news"]
        self.assertEqual(news["domestic_items"], [
            {"title": "合成置顶标题丙", "summary": "", "pinned": True},
            {"title": "合成原始标题甲", "summary": "合成精华行甲", "pinned": False},
            {"title": "合成原始标题乙", "summary": "", "pinned": False},
        ])
        self.assertEqual(news["ai_items"], [
            {"title": "合成原始标题甲", "summary": "合成精华行甲", "pinned": False},
            {"title": "合成标题丁", "summary": "", "pinned": False},
        ])
        self.assertEqual(news["international_items"], [])
        # 旧字段原样保留（缓存里没有的置顶条目不会被误标），旧版页面脚本照常可用
        self.assertEqual(news["domestic"], ["合成置顶标题丙", "合成精华行甲", "合成原始标题乙"])
        self.assertIs(news["domestic_pinned"], True)

    def test_corrupt_cache_sections_do_not_break_the_panel(self):
        payload = self._payload({"news": "garbage", "markets": ["not", "a", "dict"]})
        self.assertEqual(payload["news"]["domestic_items"], [])
        self.assertEqual(payload["markets"]["sectors"], {"hot": [], "fall": []})


class NewsListHtmlTest(unittest.TestCase):
    def test_front_end_renders_titles_summaries_and_pins(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node 不在 PATH 中")
        for variant, folder in APP_JS.items():
            with self.subTest(variant=variant):
                source = (REPO / folder / "web" / "app.js").read_text(encoding="utf-8")
                result = subprocess.run(
                    [node, "-e", NEWS_LIST_HARNESS], input=source.replace("\r\n", "\n"),
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
