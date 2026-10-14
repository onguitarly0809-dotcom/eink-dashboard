# 配置说明

## 环境变量

| 变量 | 说明 |
|---|---|
| `EPD_SERIAL_PORT` | 串口设备名，按你的系统实际设备填写 |
| `EPD_WEATHER_LATITUDE` | 天气查询纬度 |
| `EPD_WEATHER_LONGITUDE` | 天气查询经度 |
| `EPD_PYTHON` | 可选，指定渲染端使用的 Python 解释器 |
| `GLM_KEY` | 智谱 GLM 访问凭证 |
| `GLM_ORG` | 智谱 GLM 组织标识 |
| `GLM_PROJ` | 智谱 GLM 项目标识 |
| `INSIGHT_ARCHIVE_DIR` | 可选，页4认知洞察 Markdown 归档目录（默认 `~/Documents/Obsidian Vault/04-认知`） |

## 本地文件

以下文件均被 `.gitignore` 忽略，不应提交：

- `dashboard_serial/plans.txt`
- `dashboard_serial/glm_usage.conf`
- `dashboard_serial/dashboard_data.json`
- `dashboard_serial/page_state.json`
- `dashboard_serial/hotkeys_status.json`
- `dashboard_serial/control.log`
- `dashboard_serial/web_console.log`
- `dashboard_serial/dashboard.bin`
- `dashboard_serial/dashboard_portrait.png`
- `dashboard_serial/dashboard_preview.png`

## 示例

```powershell
$env:EPD_SERIAL_PORT = "<你的串口>"
$env:EPD_WEATHER_LATITUDE = "<纬度>"
$env:EPD_WEATHER_LONGITUDE = "<经度>"
$env:GLM_KEY = "<访问凭证>"
$env:GLM_ORG = "<组织标识>"
$env:GLM_PROJ = "<项目标识>"
```

## 横版变体

`dashboard_serial_landscape/` 使用与竖版完全相同的环境变量（`EPD_SERIAL_PORT`、`EPD_WEATHER_LATITUDE/LONGITUDE`、`INSIGHT_ARCHIVE_DIR` 等），无需额外配置。

## 邮件提醒（可选）

新邮件到达时在当前页面上叠加"二级菜单"式弹窗卡片，10 分钟后自动收起并像素级还原
被覆盖页面；弹窗期间若轮播已切页则跳过还原。QQ 邮箱开启 IMAP/SMTP 并生成授权码即可
使用；Gmail 可在网页端设置自动转发到 QQ 邮箱接入同一链路。

1. 复制 `dashboard_serial_landscape/mail_config.example.json` 为同目录 `mail_config.json`，
   填入 `account`（邮箱地址）与 `auth_code`（16 位授权码）；
2. 运行 `powershell -ExecutionPolicy Bypass -File ops/setup_mail_autostart.ps1` 配置
   开机自启（同时会立即拉起守护进程）；
3. 日志见运营目录 `mail_monitor.log`。

弹窗停留时长（`overlay_seconds`）、防刷屏最小间隔（`min_push_gap_seconds`）、突发
合并窗口（`batch_window_seconds`）等参数均可在 `mail_config.json` 中调整。
`mail_config.json` 含凭据，已被 `.gitignore` 排除，请勿提交。
