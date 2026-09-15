# 外发安全审计说明

## 审计范围

本项目发布前按“可公开外发”标准复核了源码、配置、脚本、文档和固件文件，并确认以下内容未进入仓库：

- 个人计划与运行时状态文件
- 日志、缓存、预览图和生成的二进制输出
- 环境变量文件与访问凭证
- 本机绝对路径与固定用户目录
- 历史调试记录和账号相关数据
- 厂商数据手册及未确认授权的资料

## 处理原则

1. **最小发布面**：仅保留核心源码、Web 控制台、固件、必要文档和示例配置。
2. **配置外部化**：串口、天气位置和 Python 解释器均通过环境变量传入。
3. **可选账号能力**：Agent Plan 集成默认关闭，需要显式设置环境变量才会启用。
4. **示例通用化**：自选标的与天气坐标均使用公开示例值，便于使用者替换。
5. **运行时隔离**：运行时产物统一由 `.gitignore` 排除。

## 已完成的安全改造

- 串口不再内置默认设备名，必须通过 `EPD_SERIAL_PORT` 或 `-PortName` 指定。
- 删除本机用户目录和解释器路径，Python 通过 `EPD_PYTHON` 或 `PATH` 查找。
- 删除历史文档中的本机调试路径、串口号和个人化描述。
- 将 Agent Plan 本地数据文件移动到发布目录内的忽略文件名。
- 将 GLM 凭据读取限定为环境变量或被忽略的本地配置文件。
- 使用公开示例替换个人自选标的列表。
- 保留 HTTP 出口主机白名单，降低 SSRF 风险。

## 验证记录

发布前已执行以下检查：

```powershell
python -m compileall -q dashboard_serial
node --check dashboard_serial/web/app.js
python -m py_compile dashboard_serial/dashboard_web.py dashboard_serial/render_dashboard.py dashboard_serial/dashboard_hotkeys.py
```

并对常见敏感信息模式进行了文本扫描，包括：

- 本机盘符与用户目录
- 串口设备名
- 访问凭证与密钥字段
- 个人标识字段
- 私人待办事项
- 历史调试路径

扫描未发现需要外发前处理的命中项。

## 后续维护建议

- 新增数据源时同步维护 `ALLOWED_HTTP_HOSTS`。
- 不将 Web 控制台直接暴露到公网。
- 不提交任何本地状态文件或生成的显示数据。
- 发布前按 `docs/RELEASE_CHECKLIST.md` 复查。
