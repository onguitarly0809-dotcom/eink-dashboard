# 7.5 寸墨水屏串口仪表盘（dashboard_serial）

> **Version 2.0（2026-09-23 起实现收归仓库根共享包 `epd_dashboard/`：横竖共用一套代码，
> 竖版版面常量与配额在 `epd_dashboard/layouts/portrait.py`；本目录保留运行期文件/web 前端/
> 薄入口/固件。重构回退点：git 标签 `pre-refactor-20260923`）** — 原注：模块化重构版 — 模块化重构版 · 2026-08-26**

PC 抓取天气/额度/新闻/行情数据，渲染 480x800 竖屏画面并旋转为墨水屏原生 800x480，打包成 1bpp 二进制后经 USB 串口（115200）流式推送到 ESP8266 + 7.5 寸 V2 墨水屏。

## 五页轮播

计划任务 `EPD_Dashboard_Refresh` 每 20 分钟刷新一次并自动轮播（08:30-12:00 / 13:30-19:00，午休不刷），经 `epd_refresh_hidden.vbs` 以 SW_HIDE 拉起 powershell，全程无窗口（直接跑 `powershell.exe -WindowStyle Hidden` 的窗口是先创建再隐藏，每个周期都会闪一下黑框打断打字）：

- **页1 今日看板**：日期·天气（农历/节日倒计时/预警）· GLM Coding Plan 额度（分段电量条）· 工作计划（`plans.txt`，最多 5 条）
- **页2 三栏新闻**：国内 / 国际 / AI（每栏 5 条，源失败自动切换）
- **页3 行情**：我的关注 · 板块热点（akshare 概念板块，腾讯接口兜底）· 市场参考
- **页4 认知洞察解读**：每次通过热键、Web、CLI 或轮播触发页4都会按领域轮换生成一个新主题，领域覆盖脑科学知识、认知提升、情绪管理、心理学现象、学习方法、行为设计、决策与判断、专注与休息。页4采用紧凑版式：顶部一行醒目主题 + 所属领域，正文不再重复主题/领域小节，直接从核心知识开始，并按 22/20/18/16/14/12px 自适应放大内容。缓存 120 个历史主题做规范化去重，重复输出会自动重试，生成失败则取消渲染/推送。Web 控制台可查看领域、主题、正文、生成时间、Token 用量与去重数量。**每次生成新主题会同步归档一份 Markdown 笔记到 Obsidian Vault 的 `04-认知` 文件夹**（`config.py` 的 `INSIGHT_ARCHIVE_DIR`，文件名 `YYYY-MM-DD 主题.md`，带 created/domain/tags frontmatter；只在新生成时落盘，导出失败仅记 WARN 不影响刷新）。
- **页5 智谱AI今日走势分析**：同样模式盯单只自选股——智谱AI（hk02513）实时价 + AI指数/上证对照 + 公司动态与 AI 板块两路新闻标题，生成四小节归因（今日走势/消息面归因/AI板块联动/政策与国际环境；不再显示风险提示）。生成窗口对齐港股时段（至 16:05）；`stock` 命令强制重生成。报告字数按排版容量反推（页5使用 450 字预算与 18/16/15/14/12px 自适应排版，`config.py` 的 `ANALYSIS_*` 常量）；联网搜索（`ANALYSIS_WEB_SEARCH`）仅标准接口支持且需余额。

## 目录结构

```
dashboard_serial/
├── render_dashboard.py        # 薄入口：设 EPD_VARIANT=portrait 后调共享包 cli
├── (实现已上移)               # 核心包在仓库根 epd_dashboard/，渲染器 renderers/portrait/
│   ├── config.py              #   常量集中：尺寸/布局/URL/路径/协议参数
│   ├── fonts.py               #   字体（思源黑体可变字重）与字号档位
│   ├── httpclient.py          #   HTTP 读取（重试/超时）
│   ├── util.py                #   通用工具
│   ├── calendar_cn.py         #   农历/法定节假日/节日倒计时/分市场交易状态
│   ├── placeholders.py        #   数据缺失时的占位数据
│   ├── datastore.py           #   dashboard_data.json 缓存（原子写）
│   ├── output.py              #   PNG/bin 落盘（原子写）
│   ├── obsidian_export.py     #   页4洞察 → Obsidian 04-认知 归档（Markdown 笔记）
│   ├── cli.py                 #   命令行装配逻辑
│   ├── fetchers/              #   数据抓取：weather / glm / news / markets / analysis
│   └── renderers/             #   页面渲染：common / page1_today / page2_news / page3_markets / page4_analysis / test_pattern
├── web/                       # Web 控制台页面资源（index.html + app.js）
├── dashboard_web.py           # Web 控制台服务（入口）
├── dashboard_hotkeys.py       # F13/F14/F15/F16 全局热键桥
├── dashboard_control.ps1      # CLI 总调度（跨进程互斥/渲染/推送/页码）
├── dashboard_menu.ps1         # 交互式菜单
├── send_dashboard.ps1         # 串口推送（128 字节停等协议）
├── setup_web_autostart.ps1    # Web+热键 开机自启安装/卸载
├── epd_refresh_hidden.vbs     # 计划任务无闪窗启动器（SW_HIDE 拉起 powershell）
├── dashboard_serial.ino       # ESP8266 固件（接收端状态机）
├── EPDSerial.h                # 7.5 寸 V2 屏驱动（软件 SPI）
├── plans.txt                  # 工作计划（每行一条）
└── docs/                      # CHANGELOG / 固件分析报告
```

## 日常使用

### 手动命令（CLI）

```powershell
.\dashboard_control.ps1 refresh      # 完整刷新（轮播到下一页）
.\dashboard_control.ps1 page1|page2|page3|page4|page5   # 指定页
.\dashboard_control.ps1 weather|plans|news|markets   # 单模块更新
.\dashboard_control.ps1 analysis     # 强制重新生成认知洞察并推送到页4
.\dashboard_control.ps1 preview -RenderMode insight -Page 4   # 仅预览页4，不推送、不强制生成
.\dashboard_control.ps1 stock        # 强制重新生成智谱AI走势归因并推送到页5
.\dashboard_control.ps1 plans -PlansText "事项A; 事项B"
.\dashboard_control.ps1 preview      # 只渲染不推送
.\dashboard_control.ps1 status       # 查看各模块状态
.\dashboard_menu.ps1                 # 交互菜单
```

所有渲染/推送动作由命名互斥体 `Global\EPD_Dashboard_Control` 保护：计划任务、Web、热键、手动 CLI 并发触发时，后到者直接让位并记日志，不会再互相覆盖缓存或抢占串口。

### Web 控制台（手机/平板）

`启动Web控制页.bat` 或开机自启（默认端口 8080）：页面切换与强制刷新 / 页4报告查看与预览 / 单模块更新 / 修改计划 / 测试图案 / 清屏 / 预览与日志。重复启动会检测端口占用并退出，日志在 `web_console.log`。

### 全局热键（Keychron M1/M2/M3 → F13/F14/F15）

后台 `dashboard_hotkeys.py`（含在开机自启内）触发 page1/2/3（F16 预留给 page4，可在 Keychron Launcher 把第四颗键映射为 F16），状态见 Web 控制台首页或 `hotkeys_status.json`。

## 渲染细节（给维护者）

- 换屏幕尺寸：改 `epd_dashboard/config.py`，`EPD_IMAGE_BYTES` 必须与 `send_dashboard.ps1` 的 `$ImageBytes`、固件 `EPDSerial.h` 的 `EPD_IMAGE_BYTES`（当前 48000）一致。
- 渲染输出原子写（tmp + rename），Web 端 `/preview.png` 不会读到半截文件。
- 缓存 `dashboard_data.json` 为唯一数据中转：各 fetcher 失败时保留旧值，全部失败才用占位数据。
- `import render_dashboard` 仍可用（test_news_sources.py 等脚本兼容），公共常量/函数已 re-export。

## 固件

Arduino IDE 板型 `NodeMCU 1.0 (ESP-12E Module)`，端口按 `EPD_SERIAL_PORT` 环境变量或设备管理器确认，上传 `dashboard_serial.ino`。
已知隐患与维护建议见 `docs/FIRMWARE_NOTES.md`。

## 安全提示

Web 控制台无鉴权，仅限可信局域网使用；如需暴露到不可信网络请自行加反向代理鉴权。

## 版本历史

见 `docs/CHANGELOG.md`（V1.0 起完整演进记录）。
