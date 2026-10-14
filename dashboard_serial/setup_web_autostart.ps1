# setup_web_autostart.ps1 — 薄委托：转发到仓库根共享脚本 ops/setup_web_autostart.ps1
$Root = Split-Path -Parent $PSScriptRoot
$_rc = 0
try {
    & (Join-Path $Root "ops\setup_web_autostart.ps1") -DataDir $PSScriptRoot @args
    if ($LASTEXITCODE) { $_rc = $LASTEXITCODE }
} catch {
    Write-Host $_.Exception.Message
    $_rc = 1
}
exit $_rc
