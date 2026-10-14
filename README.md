# E-Ink Dashboard

一个面向 7.5 英寸墨水屏的多页信息看板，支持天气、新闻、行情、认知洞察、个股走势分析和新邮件提醒。项目包含 Python 渲染端、Web 控制台、全局热键、串口推送和 ESP8266 固件，横版（800×480，当前运营）与竖版（480×800）共用一套核心代码。

## 功能

- **页1 今日看板**：天气、GLM 额度、工作计划（横版含月历、节假日/调休标记与计划优先级标签）
- **页2 三栏新闻**：国内、国际、AI（AI 逐篇通读全文生成一行精华摘要）
- **页3 行情**：自选股、板块热点（含冷板块领跌个股）、市场参考
- **页4 认知洞察**：脑科学、认知提升、情绪管理、心理学、学习方法、行为设计等（逐节字数配额硬校验，新主题自动归档 Markdown 笔记到 Obsidian）
- **页5 智谱AI走势分析**：个股走势、消息面、板块联动、政策与国际环境
- **新邮件弹窗提醒**：IMAP IDLE 秒级感知新邮件，在当前页面上叠加"二级菜单"式弹窗卡片（发件人/主题/到点时间，最多 3 封），10 分钟后自动收起并像素级还原被覆盖页；突发多封合并推送、最小间隔防刷屏；QQ 邮箱授权码即用，Gmail 可经自动转发接入同一链路
- **四灰模式**（横版）：轮播/切页恒四灰推送，正文灰阶抗锯齿无锯齿；接受边框外围一圈浅灰（四灰固有特性），需要彻底重置时手动 `clear` 全白清屏

## 架构

横竖两个运营目录共用仓库根的核心包，差异全部收敛到版式模块：

```
epd_dashboard/                  共享核心包（config+layouts+fetchers+renderers+cli/web/hotkeys/mail_monitor）
├── layouts/landscape|portrait  横竖差异的唯一来源：版面锚点/字数配额/字重/默认方向
├── renderers/landscape|portrait  两套页面渲染器（V3 像素+宋体 / V2 黑体）
dashboard_serial_landscape/     横版运营目录：薄入口 + 字体/web 前端 + 运行期文件
dashboard_serial/               竖版运营目录：同构（含固件 dashboard_serial.ino）
ops/                            PS1 共享层：control/menu/send/setup（变体委托调用）
tools/ tests/                   离线全页渲染回归工具 / 单元与对拍测试
switch_orientation.py           横竖运营一键切换
```

四个入口（计划任务轮播 / Web 控制台 / 全局热键 / 手动 CLI）共用一把全局互斥锁；邮件监控等用户向动作遇轮播占锁时排队等待。

## 技术栈

- Python 3.11（Pillow / pyserial / lunar_python / akshare）
- PowerShell 5.1
- Arduino / ESP8266（NodeMCU 1.0 / ESP-12E）
- HTML / CSS / JavaScript

## 快速开始

### 1. 安装依赖

```powershell
python -m pip install -r requirements.txt
```

### 2. 配置串口

串口通过环境变量指定（驱动板为 CP210x 桥，USB 换口后可按 VID:PID 自动找回）：

```powershell
$env:EPD_SERIAL_PORT = "<你的串口>"
```

也可在运行命令中显式指定：

```powershell
.\dashboard_serial_landscape\dashboard_control.ps1 refresh -PortName <你的串口>
```

### 3. 启动 Web 控制台

```powershell
python .\dashboard_serial_landscape\dashboard_web.py --port 8080
```

访问 `http://127.0.0.1:8080`（手机/平板连同一 Wi-Fi 可远程控制）。修改 `web/index.html`
或 `web/app.js` 后需重启生效（页面资源启动时读入内存）。

### 4. 推送到墨水屏

```powershell
.\dashboard_serial_landscape\dashboard_control.ps1 refresh
```

计划任务每 20 分钟自动轮播（页1→页5 自然序）；热键 F13-F17 直切页面（M4/M5 强制全量更新）；`switch_orientation.py` 切换横竖运营。

### 5. 邮件提醒（可选）

QQ 邮箱网页版开启 IMAP/SMTP 服务并生成授权码（Gmail 在网页端设置自动转发到 QQ 邮箱即可接入同一链路）：

```powershell
Copy-Item dashboard_serial_landscape\mail_config.example.json dashboard_serial_landscape\mail_config.json
# 编辑 mail_config.json 填入 account 与 auth_code
powershell -ExecutionPolicy Bypass -File ops\setup_mail_autostart.ps1
```

守护进程开机自启并立即拉起，新邮件到达后秒级推屏弹窗；日志见运营目录 `mail_monitor.log`，
弹窗时长/防刷屏参数在 `mail_config.json` 中调整。

### 6. 回归验证

```powershell
python tools\render_all_pages.py landscape   # 离线渲染横版全部页面（排版调试/回归对比）
python tests\test_gray_pack.py               # 四灰编码对拍厂商 C 实现
python -m unittest discover tests            # 单元测试
```

## 安全说明

- 所有凭据均通过环境变量或本地被忽略的配置文件读取（含 GLM 凭据与邮箱授权码）。
- 运行日志、缓存、预览图、二进制输出和个人计划文件均不应提交。
- HTTP 出口采用主机白名单 + 公网 IP 校验，降低 SSRF 风险。
- Web 控制台无鉴权，仅限可信局域网使用。

## 许可证

本项目暂未指定开源许可证。
