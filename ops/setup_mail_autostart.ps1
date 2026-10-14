# setup_mail_autostart.ps1 — 把邮件监控守护进程设为开机(登录)自启（pythonw 隐藏后台）
# 用法:
#   powershell -ExecutionPolicy Bypass -File setup_mail_autostart.ps1
#   powershell -ExecutionPolicy Bypass -File setup_mail_autostart.ps1 -Remove
# 前提: 运营目录已创建 mail_config.json（QQ邮箱+授权码），否则守护进程启动即退出
param(
    [switch]$Remove,
    # 运营变体目录（自启指向该目录的 mail_monitor.py 入口）
    [string]$DataDir = ""
)
$ErrorActionPreference = "Stop"

$VbsName    = "EPD_Mail_Monitor_Start.vbs"
$StartupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$VbsPath    = Join-Path $StartupDir $VbsName

if (-not $DataDir) { $DataDir = Join-Path (Split-Path -Parent $PSScriptRoot) "dashboard_serial_landscape" }
$ScriptDir = $DataDir
$Pythonw = $null
if ($env:EPD_PYTHON) {
    $Pythonw = $env:EPD_PYTHON -replace "python\.exe$", "pythonw.exe"
    if (-not (Test-Path -LiteralPath $Pythonw)) { throw "EPD_PYTHON-derived pythonw.exe not found: $Pythonw" }
} else {
    $command = Get-Command pythonw -ErrorAction SilentlyContinue
    if ($command) { $Pythonw = $command.Source }
}
$MonitorPy = Join-Path $ScriptDir "mail_monitor.py"

if ($Remove) {
    if (Test-Path -LiteralPath $VbsPath) {
        Remove-Item -LiteralPath $VbsPath -Force
        Write-Host "已移除开机自启项: $VbsPath"
    } else {
        Write-Host "开机自启项不存在（无需移除）: $VbsPath"
    }
    exit 0
}

if (-not $Pythonw)                  { throw "找不到 pythonw.exe（可设 EPD_PYTHON 指定解释器目录）" }
if (-not (Test-Path -LiteralPath $MonitorPy)) { throw "找不到 mail_monitor.py: $MonitorPy" }
if (-not (Test-Path -LiteralPath (Join-Path $ScriptDir "mail_config.json"))) {
    Write-Host "提示: mail_config.json 尚未创建，自启已配置但监控会在登录后立即退出" -ForegroundColor Yellow
    Write-Host "       创建后可运行: wscript `"$VbsPath`" 手动拉起"
}

$line = 'CreateObject("WScript.Shell").Run """{0}"" ""{1}""", 0, False' -f $Pythonw, $MonitorPy
[System.IO.File]::WriteAllText($VbsPath, $line, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "已创建开机自启项: $VbsPath"
Write-Host "使用解释器: $Pythonw"
Write-Host "立即测试: wscript `"$VbsPath`"  （日志: $ScriptDir\mail_monitor.log）"
Write-Host "停用自启: powershell -ExecutionPolicy Bypass -File setup_mail_autostart.ps1 -Remove"
