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
