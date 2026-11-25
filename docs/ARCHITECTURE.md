# 架构说明

## 数据流

```text
数据源
  ↓
fetchers/
  ↓
dashboard_data.json
  ↓
renderers/
  ↓
dashboard_preview.png / dashboard_portrait.png
  ↓
dashboard.bin
  ↓
串口推送
  ↓
ESP8266 + 7.5 英寸墨水屏
```

## 目录结构（横竖共用一个核心包）

```text
epd_dashboard/                    # 共享核心包（横竖唯一的 Python 实现）
├── config.py                     #   变体解析(EPD_VARIANT/EPD_BASE_DIR) + 共享常量
├── layouts/                      #   横竖差异的版面常量与字数配额
├── fetchers/                     #   数据抓取与生成（天气/新闻/行情/额度/洞察/归因）
├── renderers/landscape/          #   横版 800x480 页面渲染器（页1-5 + 邮件弹窗层）
├── renderers/portrait/           #   竖版 480x800 页面渲染器（页1-5）
├── push.py                       #   串口推送（波特率自动协商 / 1-bit 与四灰双尺寸分流）
├── mail_monitor.py               #   IMAP IDLE 新邮件监控守护
└── cli.py / web.py / hotkeys.py  #   CLI / Web / 热键三个入口的实现
dashboard_serial_landscape/       # 横版运营目录（薄入口 + 字体资产 + Web 前端）
dashboard_serial/                 # 竖版运营目录（薄入口 + ESP8266 固件）
ops/                              # 横竖共用的 PS1 层（总调度 / 发送 / 自启安装）
tests/ tools/                     # 单元测试 / 离线全页渲染回归工具
```

各运营目录的入口脚本先设置 `EPD_VARIANT` 与 `EPD_BASE_DIR` 再导入 `epd_dashboard`；
运行期文件（缓存/计划/bin/预览/日志/页状态）全部锚定在运营目录，横竖两套互不干扰。

## 运行入口（共用 Global\EPD_Dashboard_Control 互斥锁）

| 入口 | 触发方式 | 链路 |
|---|---|---|
| Windows 计划任务 | 定时轮播 | vbs 无闪窗启动 → 变体目录 control 委托 → ops/control.ps1 |
| Web 控制台 / 全局热键 | 手动 | 薄入口 → epd_dashboard/web.py / hotkeys.py |
| 邮件监控守护 | IMAP IDLE 新邮件事件 | mail_monitor.py → control mail 弹窗层（按配置时长，默认 10 分钟后 mailoff 还原被覆盖页） |

## 容错与请求校验

- **退出码**：`ops/control.ps1` 0 成功 / 1 失败或让位 / 3 会话锁定 / 4 设备未连接。cli 在 `--push` 前只枚举串口做在线预检，设备不在就以 4 结束（不抓数、不耗模型额度）；邮件监控把 3、4 都当作"稍后重试"。
- **轮播连败**：refresh 失败不翻页（下一轮重试同一页），同一页连续失败 2 次后跳过它一圈；连败记录与页状态同存 `page_state.json`（`fail_page` / `fail_count`）。
- **上游熔断**：`epd_dashboard/net_breaker.py` 按数据源熔断，连续失败 3 次打开 30 分钟，冷却到期放行探测。
- **生成失败不冻结轮播**：页4 洞察生成失败沿用上一篇并标"历史"；页5 分析被内容安全拦截时去掉新闻标题重试一次，仍失败沿用旧值并标"历史"。
- **页5 报告**：港股时段内每次渲染本页都重新生成；小节超字数重试三次仍超时，把超限的那一节在标点处截短来用，而不是整篇丢弃。
- **邮件监控**：锁屏/设备离线时推送与收起按 20/30 秒推迟等待；IMAP UIDVALIDITY 变化自动重建水位基准；竖版运营时不启动。
- **Web 控制台**：所有请求校验 Host（只认 IP / localhost / *.local），POST 另要求 Origin 同源且 Content-Type 为 application/json；用自定义域名访问时设环境变量 `EPD_WEB_ALLOW_ANY_HOST=1`。
- **节假日表**：`HOLIDAY_PLAN` 只对 `HOLIDAY_PLAN_YEAR` 那一年有效，跨年后按常规规则判断并打 WARN。

## 缓存策略

看板运行时数据统一写入 `dashboard_data.json`。切页时若缓存仍在有效期内，将直接复用缓存，避免每次按键都触发网络请求。

## 固件协议

PC 端与 ESP8266 之间使用简单文本握手和二进制块传输协议，支持自动协商波特率与块大小。具体参数见 `epd_dashboard/config.py` 与 `dashboard_serial.ino`。
