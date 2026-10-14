# ops/send_dashboard.ps1 - 串口推送 dashboard.bin（python 实现版）
# 原 PowerShell 115200 停等实现已退役（2026-09-24）：V2.5 提速固件以 921600 监听，
# 旧脚本固定 115200 探测 PING 不通（test/clear 命令自提速后一直失败的原因）。
# python 版波特率自动协商（921600/512B 优先、115200/128B 兜底）+ USB 换口 VID:PID 找回，
# 与页1-5 主链路（render 进程内推送）同一实现。
param(
    [string]$PortName = $env:EPD_SERIAL_PORT,
    [int]$BaudRate = 0,                # 兼容保留：0=自动协商（推荐）
    [Parameter(Mandatory = $true)]
    [string]$BinaryPath,
    [int]$TimeoutSeconds = 30          # 兼容保留（python 端自带刷新等待）
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

if (-not (Test-Path -LiteralPath $BinaryPath)) {
    throw "Binary not found: $BinaryPath"
}
$Root = Split-Path -Parent $PSScriptRoot

# 渲染/推送用 python：优先 EPD_PYTHON（需带 pyserial），否则使用 PATH 中的 python
$Py = "python"
if ($env:EPD_PYTHON) {
    if (-not (Test-Path -LiteralPath $env:EPD_PYTHON)) { throw "EPD_PYTHON does not exist: $env:EPD_PYTHON" }
    $Py = $env:EPD_PYTHON
}
if (-not $Py) { $Py = "python" }

$code = @"
import sys
sys.path.insert(0, r'$Root')
from epd_dashboard.push import push_with_retry
push_with_retry(binary_path=r'$BinaryPath', port=r'$PortName', retries=3)
"@
& $Py -c $code
exit $LASTEXITCODE
