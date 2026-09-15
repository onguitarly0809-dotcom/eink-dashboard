# E-Ink Dashboard

一个运行在 Windows 上的 7.5 英寸墨水屏信息看板，支持天气、新闻、行情、认知洞察和个股走势分析。项目包含 Python 渲染端、Web 控制台、全局热键、串口推送和 ESP8266 固件。

## 功能

- **页1 今日看板**：天气、额度、本地计划
- **页2 三栏新闻**：国内、国际、AI
- **页3 行情**：自选标的、板块热点、市场参考
- **页4 认知洞察**：脑科学、认知提升、情绪管理、心理学、学习方法、行为设计
- **页5 个股走势分析**：走势、消息面、板块联动、政策与国际环境

## 技术栈

- Python 3.11+
- Pillow
- pyserial
- lunar-python
- akshare（可选）
- PowerShell 5.1
- Arduino / ESP8266
- HTML / CSS / JavaScript

## 目录结构

```text
dashboard_serial/
├── epd_dashboard/
│   ├── fetchers/
│   ├── renderers/
│   ├── config.py
│   ├── fonts.py
│   └── ...
├── web/
├── docs/
├── dashboard_control.ps1
├── dashboard_web.py
├── dashboard_hotkeys.py
├── render_dashboard.py
├── send_dashboard.ps1
├── setup_web_autostart.ps1
├── dashboard_serial.ino
└── EPDSerial.h
```

## 快速开始

### 1. 安装依赖

```powershell
python -m pip install -r requirements.txt
```

### 2. 配置串口

```powershell
$env:EPD_SERIAL_PORT = "<你的串口>"
```

也可在运行命令中显式指定：

```powershell
.\dashboard_serial\dashboard_control.ps1 refresh -PortName <你的串口>
```

如需长期保存：

```powershell
setx EPD_SERIAL_PORT "<你的串口>"
```

### 3. 启动 Web 控制台

```powershell
python .\dashboard_serial\dashboard_web.py --port 8080
```

访问：

```text
http://127.0.0.1:8080
```

### 4. 推送到墨水屏

```powershell
cd .\dashboard_serial
.\dashboard_control.ps1 refresh
```

## 配置说明

详细环境变量见 `docs/CONFIGURATION.md`。

### 天气位置

```powershell
$env:EPD_WEATHER_LATITUDE = "<纬度>"
$env:EPD_WEATHER_LONGITUDE = "<经度>"
```

### AI 功能

页4和页5依赖智谱 GLM。未配置凭证时，相关模块会自动降级，不影响基础页面渲染。

```powershell
$env:GLM_KEY = "<访问凭证>"
$env:GLM_ORG = "<组织标识>"
$env:GLM_PROJ = "<项目标识>"
```

## 安全说明

- Web 控制台无鉴权，仅限可信局域网使用。
- 不要提交 `.env`、`plans.txt`、日志、缓存、预览图或生成的二进制文件。
- HTTP 出口采用主机白名单，降低 SSRF 风险。
- 所有访问凭证均通过环境变量或本地忽略文件读取。

## 许可证

本项目暂未指定开源许可证。
