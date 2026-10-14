# dashboard_control.ps1 — 薄委托：转发到仓库根共享脚本 ops/control.ps1
# 计划任务 VBS / Web / 热键 / 手动命令仍从本目录进入，调用方式不变
$Root = Split-Path -Parent $PSScriptRoot
$_rc = 0
try {
    & (Join-Path $Root "ops\control.ps1") -DataDir $PSScriptRoot @args
    if ($LASTEXITCODE) { $_rc = $LASTEXITCODE }
} catch {
    Write-Host $_.Exception.Message
    $_rc = 1
}
exit $_rc
