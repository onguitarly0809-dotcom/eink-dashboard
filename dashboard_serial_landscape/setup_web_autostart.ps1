# setup_web_autostart.ps1 - 把墨水屏 Web 控制台和全局热键设为开机(登录)自启
# 用法:
#   powershell -ExecutionPolicy Bypass -File setup_web_autostart.ps1
#   powershell -ExecutionPolicy Bypass -File setup_web_autostart.ps1 -Remove
param([switch]$Remove)
$ErrorActionPreference = "Stop"

$VbsName    = "EPD_Web_Start.vbs"
$StartupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$VbsPath    = Join-Path $StartupDir $VbsName

# 路径自动推导：pythonw 沿用 EPD_PYTHON 或 PATH，脚本路径基于本文件位置，换机/挪目录不用改这里
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Pythonw = $null
if ($env:EPD_PYTHON) {
    $Pythonw = $env:EPD_PYTHON -replace "python\.exe$", "pythonw.exe"
    if (-not (Test-Path -LiteralPath $Pythonw)) { throw "EPD_PYTHON-derived pythonw.exe not found: $Pythonw" }
} else {
    $command = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($command) { $Pythonw = $command.Source }
}
$WebPy    = Join-Path $ScriptDir "dashboard_web.py"
$HotkeyPy = Join-Path $ScriptDir "dashboard_hotkeys.py"

if ($Remove) {
    if (Test-Path -LiteralPath $VbsPath) {
        Remove-Item -LiteralPath $VbsPath -Force
        Write-Host "已移除开机自启项: $VbsPath"
    } else {
        Write-Host "开机自启项不存在（无需移除）: $VbsPath"
    }
    exit 0
}

if (-not $Pythonw)                 { throw "找不到 pythonw.exe（可设 EPD_PYTHON 指定解释器目录）" }
if (-not (Test-Path -LiteralPath $WebPy))    { throw "找不到 dashboard_web.py: $WebPy" }
if (-not (Test-Path -LiteralPath $HotkeyPy)) { throw "找不到 dashboard_hotkeys.py: $HotkeyPy" }

$webLine = 'CreateObject("WScript.Shell").Run """{0}"" ""{1}""", 0, False' -f $Pythonw, $WebPy
$hotkeyLine = 'CreateObject("WScript.Shell").Run """{0}"" ""{1}""", 0, False' -f $Pythonw, $HotkeyPy
$vbsContent = $webLine + [Environment]::NewLine + $hotkeyLine
# 用 UTF-8 无 BOM 写（vbs 路径含中文时 ASCII 会写坏）；现路径全英文，两种写法字节一致
[System.IO.File]::WriteAllText($VbsPath, $vbsContent, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "已创建开机自启项: $VbsPath"
Write-Host "使用解释器: $Pythonw"
Write-Host "立即测试: wscript `"$VbsPath`""
Write-Host "停用自启: powershell -ExecutionPolicy Bypass -File setup_web_autostart.ps1 -Remove"
