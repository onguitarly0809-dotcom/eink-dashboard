# send_dashboard.ps1 — 薄委托：转发到仓库根共享脚本 ops/send_dashboard.ps1
$Root = Split-Path -Parent $PSScriptRoot
$_rc = 0
try {
    & (Join-Path $Root "ops\send_dashboard.ps1") -BinaryPath (Join-Path $PSScriptRoot "dashboard.bin") @args
    if ($LASTEXITCODE) { $_rc = $LASTEXITCODE }
} catch {
    Write-Host $_.Exception.Message
    $_rc = 1
}
exit $_rc
