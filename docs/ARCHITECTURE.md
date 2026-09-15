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

## 模块划分

- `dashboard_control.ps1`：CLI 总调度，负责渲染、推送、切页与状态查询。
- `dashboard_web.py`：Web 控制台，提供页面切换、预览与日志接口。
- `dashboard_hotkeys.py`：全局热键入口。
- `render_dashboard.py`：兼容入口，实际逻辑位于 `epd_dashboard` 包。
- `epd_dashboard/config.py`：集中配置屏幕尺寸、布局、数据源 URL 与环境变量。
- `epd_dashboard/fetchers/`：天气、新闻、行情、额度与 AI 分析数据获取。
- `epd_dashboard/renderers/`：五页看板与测试图案渲染。
- `epd_dashboard/push.py`：串口协议实现与自动协商。
- `web/`：Web 控制台前端。
- `dashboard_serial.ino` / `EPDSerial.h`：ESP8266 固件与墨水屏驱动。

## 缓存策略

看板运行时数据统一写入 `dashboard_data.json`。切页时若缓存仍在有效期内，将直接复用缓存，避免每次按键都触发网络请求。

## 固件协议

PC 端与 ESP8266 之间使用简单文本握手和二进制块传输协议，支持自动协商波特率与块大小。具体参数见 `epd_dashboard/config.py` 与 `dashboard_serial.ino`。
