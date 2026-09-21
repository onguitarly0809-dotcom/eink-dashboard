# dashboard_menu.ps1 — 墨水屏仪表盘交互式控制菜单
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ControlPs1 = Join-Path $ScriptDir "dashboard_control.ps1"

# 计划显示上限（对应 render_dashboard.py 的 plans[:5]），避免显示溢出
$MaxPlans = 5

while ($true) {
    Write-Host ""
    Write-Host "=========================================="
    Write-Host "   墨水屏仪表盘控制菜单"
    Write-Host "=========================================="
    Write-Host "  1) 完整刷新并推送（自动轮播 今日看板/新闻页/行情页/认知洞察页/智谱AI分析页）"
    Write-Host "  2) 只更新天气并推送"
    Write-Host "  4) 只更新计划并推送"
    Write-Host "  5) 只更新热点新闻并推送"
    Write-Host "  6) 修改计划内容并推送"
    Write-Host "  7) 📄 刷新日常信息页（天气+额度+计划）"
    Write-Host "  8) 📰 刷新热点新闻页"
    Write-Host "  9) 📈 刷新股市信息页"
    Write-Host "  14) 🧠 刷新认知洞察页（按领域生成新主题并去重）"
    Write-Host "  15) 🔄 强制重新生成认知洞察并推送"
    Write-Host "  16) 📈 刷新智谱AI今日走势分析页（超90分钟且港股时段内自动重生成）"
    Write-Host "  17) 🔄 强制重新生成智谱AI分析并推送"
    Write-Host "  10) 测试图案（信息卡/棋盘格/全白/全黑）"
    Write-Host "  11) 清屏（全白）"
    Write-Host "  12) 预览（只渲染不推送）"
    Write-Host "  18) 🖼️ 仅预览认知洞察页（不推送）"
    Write-Host "  13) 查看状态"
    Write-Host "  0) 退出"

    $choice = Read-Host "  选择"
    if ($choice -eq "0") {
        Write-Host "  已退出。"
        break
    }
    if (-not $choice -and [Console]::IsInputRedirected) { break }

    switch ($choice) {
        "1" { & $ControlPs1 refresh }
        "2" { & $ControlPs1 weather }
        "4" { & $ControlPs1 plans }
        "5" { & $ControlPs1 news }
        "6" {
            # 第一步：确定计划数量（上限 $MaxPlans，避免显示溢出）
            $count = -1
            while ($count -lt 0) {
                $countInput = Read-Host "  本次要设置几个计划？（最多 $MaxPlans 个，输入 0 表示不修改、直接推送现有计划）"
                if ($countInput -eq "" -and [Console]::IsInputRedirected) { $count = -1; break }
                if (-not [int]::TryParse($countInput, [ref]$count) -or $count -lt 0 -or $count -gt $MaxPlans) {
                    Write-Host "  无效输入，请输入 0 ~ $MaxPlans 的整数"
                    $count = -1
                    continue
                }
            }
            if ($count -eq -1) { break }

            if ($count -eq 0) {
                Write-Host "  数量为 0，保留现有计划，直接更新并推送"
                & $ControlPs1 plans
            } else {
                # 第二步：逐条输入每个计划
                $items = @()
                for ($i = 1; $i -le $count; $i++) {
                    $text = Read-Host "  请输入第 $i / $count 个计划内容（直接回车跳过此项）"
                    if ($text -and $text.Trim()) {
                        $item = $text.Trim()
                        $items += $item
                        Write-Host "  已记录：$item"
                    }
                }
                if ($items.Count -eq 0) {
                    Write-Host "  未输入任何计划，保留现有计划，直接更新并推送"
                    & $ControlPs1 plans
                } else {
                    Write-Host "  共记录 $($items.Count) 个计划，开始更新并推送..."
                    & $ControlPs1 plans -PlansText ($items -join ";")
                }
            }
        }
        "7" { & $ControlPs1 page1 }
        "8" { & $ControlPs1 page2 }
        "9" { & $ControlPs1 page3 }
        "14" { & $ControlPs1 page4 }
        "15" { & $ControlPs1 analysis }
        "16" { & $ControlPs1 page5 }
        "17" { & $ControlPs1 stock }
        "10" {
            Write-Host "  请选择测试图案:"
            Write-Host "    1) 信息卡   2) 棋盘格   3) 全白   4) 全黑"
            $pt = Read-Host "  选择"
            $pat = switch ($pt) { "1" { "info" } "2" { "chess" } "3" { "white" } "4" { "black" } default { "info" } }
            & $ControlPs1 test -Pattern $pat
        }
        "11" { & $ControlPs1 clear }
        "12" { & $ControlPs1 preview }
        "13" { & $ControlPs1 status }
        "18" { & $ControlPs1 preview -RenderMode insight -Page 4 }
        default { Write-Host "  无效选择，请重新输入" }
    }

    Write-Host ""
    Read-Host "  按回车键返回菜单" | Out-Null
}
