# dashboard_control.ps1 — 7.5 寸墨水屏仪表盘控制脚本（CLI 总调度）
# 用法:
#   .\dashboard_control.ps1 refresh                          # 更新全部(天气+额度+计划)并推送
#   .\dashboard_control.ps1 weather                          # 只更新天气并推送
#   .\dashboard_control.ps1 weather                          # 只更新天气并推送
#   .\dashboard_control.ps1 plans                            # 只更新计划并推送
#   .\dashboard_control.ps1 plans -PlansText "事项A; 事项B"   # 先写计划再推送
#   .\dashboard_control.ps1 test -Pattern info               # 测试卡(默认 info)
#   .\dashboard_control.ps1 test -Pattern chess              # 棋盘格(查坏点)
#   .\dashboard_control.ps1 page1                            # 切到页1(今日看板)并推送；缓存TTL内秒出图
#   .\dashboard_control.ps1 page3 -Force                     # 切到页3并强制联网刷新行情（跳过缓存TTL）
#   .\dashboard_control.ps1 news                             # 只更新热点新闻并推送（跳过缓存TTL）
#   .\dashboard_control.ps1 markets                          # 只更新行情并推送
#   .\dashboard_control.ps1 page4                            # 按领域轮换生成认知洞察(历史去重)并推送
#   .\dashboard_control.ps1 analysis                         # 强制重新生成AI认知洞察并推送到页4
#   .\dashboard_control.ps1 page5                            # 渲染页5(智谱AI走势归因)并推送(超TTL且港股时段内自动重生成)
#   .\dashboard_control.ps1 stock                            # 强制重新生成智谱AI走势归因并推送到页5
#   单模块更新会先跳转到该模块所在页再渲染推送：weather/plans→页1(今日看板)、news→页2(三栏新闻)、markets→页3(行情)、analysis→页4(认知洞察)、stock→页5(智谱AI走势归因)
#   refresh 每次调用自动轮播 页1(今日看板) / 页2(三栏新闻) / 页3(行情) / 页4(认知洞察) / 页5(智谱AI走势归因)
#   .\dashboard_control.ps1 clear                            # 清屏(全白)
#   .\dashboard_control.ps1 preview                          # 只渲染不推送(先看效果)
#   .\dashboard_control.ps1 status                           # 查看各模块状态
param(
    [Parameter(Position = 0)]
    [ValidateSet("test", "weather", "plans", "news", "markets", "analysis", "stock", "refresh", "preview", "status", "clear", "page1", "page2", "page3", "page4", "page5")]
    [string]$Command = "refresh",
    [string]$PortName = $env:EPD_SERIAL_PORT,
    [ValidateSet("info", "chess", "white", "black")]
    [string]$Pattern = "info",
    [ValidateSet("full", "today", "weather", "plans", "news", "markets", "insight", "psychology", "analysis", "stock")]
    [string]$RenderMode = "full",
    [ValidateRange(0, 5)]
    [int]$Page = 0,
    [string]$PlansText = "",
    [int]$PushRetries = 3,
    # page1-5 切页默认走缓存 TTL（秒出图）；-Force 跳过 TTL 强制联网刷新数据
    [switch]$Force
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
# 强制 Python 子进程以 UTF-8 输出，避免中文日志在管道中按 GBK 写、被按 UTF-8 读而乱码
$env:PYTHONUTF8 = "1"

# ---------- 常量集中区 ----------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RenderPy = Join-Path $ScriptDir "render_dashboard.py"
$SenderPs1 = Join-Path $ScriptDir "send_dashboard.ps1"
$PlansFile = Join-Path $ScriptDir "plans.txt"
$CacheFile = Join-Path $ScriptDir "dashboard_data.json"
$PageStateFile = Join-Path $ScriptDir "page_state.json"
$LogFile = Join-Path $ScriptDir "control.log"
# 跨进程互斥：计划任务 / Web 控制台 / 热键 / 手动 CLI 四个入口共用同一把锁，
# 防止并发渲染互相覆盖 dashboard_data.json 或同时抢占串口
$MutexName = "Global\EPD_Dashboard_Control"

# 渲染用 Python：优先 EPD_PYTHON，其次使用 PATH 中的 python。
$RenderPython = "python"
if ($env:EPD_PYTHON) {
    if (-not (Test-Path -LiteralPath $env:EPD_PYTHON)) { throw "EPD_PYTHON does not exist: $env:EPD_PYTHON" }
    $RenderPython = $env:EPD_PYTHON
}

$InvariantCulture = [System.Globalization.CultureInfo]::InvariantCulture
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    try {
        # 简单轮转：超过 1MB 保留后半，避免长期运行无限增长
        if ((Get-Item -LiteralPath $LogFile -ErrorAction SilentlyContinue).Length -gt 1MB) {
            $lines = Get-Content -LiteralPath $LogFile
            $lines | Select-Object -Last ([int]($lines.Count / 2)) | Set-Content -LiteralPath $LogFile -Encoding UTF8
        }
    } catch { }
}

function Get-PageState {
    if (Test-Path -LiteralPath $PageStateFile) {
        try {
            $state = [System.IO.File]::ReadAllText($PageStateFile, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
            if ($state.page -in 1,2,3,4,5) { return [int]$state.page }
        } catch { }
    }
    return 1
}

function Set-PageState {
    param([int]$Page)
    # 无 BOM 写入，任何读取方（PowerShell/Python）都能直接解析
    [System.IO.File]::WriteAllText($PageStateFile, "{`"page`": $Page}", $Utf8NoBom)
    return $Page
}

function Invoke-Render {
    param([string]$Mode, [int]$Page = 1, [switch]$Force, [switch]$Push)
    Write-Host "== 渲染 mode=$Mode page=$Page$(if ($Force) { ' (force)' })$(if ($Push) { ' +推送' }) =="
    $extra = @()
    if ($Force) { $extra += "--force" }
    if ($Push) { $extra += "--push" }
    # 捕获子进程输出并回显；失败时尾部落 control.log——定时任务的输出无人看到，
    # 此前只记"渲染失败"无法定位（2026-09-02 全天轮播失败即因此查不到根因）。
    # 注意：PS5.1 下 2>&1 会把 stderr 行变成 ErrorRecord，脚本顶部 $ErrorActionPreference=Stop
    # 会令其直接抛终止性异常（异常消息=stderr 首行），故捕获期间必须临时降为 Continue。
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $RenderPython $RenderPy --mode $Mode --page $Page @extra 2>&1
    } finally {
        $ErrorActionPreference = $prevEAP
    }
    $output | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        $tail = (@($output | ForEach-Object { $_.ToString() } | Select-Object -Last 12) -join " | ") -replace "\r?\n", " "
        Write-Log "ERROR render mode=$Mode page=$Page exit=$LASTEXITCODE :: $tail"
        throw "渲染失败（mode=$Mode），已取消推送，屏幕保留上次内容"
    }
}

function Invoke-RenderTest {
    param([string]$TestPattern)
    Write-Host "== 测试图案 $TestPattern =="
    & $RenderPython $RenderPy --test-pattern $TestPattern
    if ($LASTEXITCODE -ne 0) {
        throw "测试渲染失败"
    }
}

function Invoke-Push {
    param([int]$MaxRetries = 3)
    for ($attempt = 1; $attempt -le $MaxRetries; $attempt++) {
        Write-Host "== 推送到墨水屏 $PortName（第 $attempt/$MaxRetries 次）=="
        try {
            & $SenderPs1 -PortName $PortName
            return
        } catch {
            Write-Host ("推送失败（第 {0} 次）：{1}" -f $attempt, $_.Exception.Message) -ForegroundColor Yellow
            if ($attempt -lt $MaxRetries) {
                Write-Host "6 秒后重试..."
                Start-Sleep -Seconds 6
            }
        }
    }
    throw "多次推送失败：请检查 USB 连接 / 固件是否烧录 / 串口号是否正确（$PortName）"
}

# 渲染并推送（python 进程内直连串口，省掉再起一个 PowerShell），成功后才把目标页
# 落盘——失败时轮播不会跳页。耗时计入 control.log，便于量化响应速度。
function Invoke-RenderAndCommitPage {
    param([string]$Mode, [int]$TargetPage, [switch]$Force)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    Invoke-Render $Mode -Page $TargetPage -Force:$Force -Push
    Set-PageState $TargetPage
    $secs = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    Write-Host "== 页面就绪耗时 $secs s（含串口传输+刷屏）=="
    Write-Log "timing mode=$Mode page=$TargetPage took ${secs}s"
}

$Mutex = New-Object System.Threading.Mutex($false, $MutexName)
$HasMutex = $false
try {
    if ($Command -ne "status") {
        # 抢不到锁说明另一个实例（计划任务/Web/热键）正在渲染或推送，直接让位
        $HasMutex = $Mutex.WaitOne(0)
        if (-not $HasMutex) {
            Write-Host "另一个仪表盘控制实例正在运行，本次 $Command 已跳过。"
            Write-Log "SKIP $Command : another instance holds the mutex"
            exit 1
        }
    }
    switch ($Command) {
        "test" {
            Invoke-RenderTest $Pattern
            Invoke-Push -MaxRetries $PushRetries
            Write-Log "test pattern=$Pattern -> pushed"
        }
        "weather" {
            Invoke-RenderAndCommitPage "weather" -TargetPage 1
            Write-Log "weather(page=1) -> pushed"
        }
        "plans" {
            if ($PlansText) {
                $items = @($PlansText -split ";" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
                if ($items.Count -eq 0) { throw "PlansText 为空，无法写入计划" }
                [System.IO.File]::WriteAllLines($PlansFile, [string[]]$items, $Utf8NoBom)
                Write-Host "已写入 plans.txt: $($items -join ' | ')"
            }
            Invoke-RenderAndCommitPage "plans" -TargetPage 1
            Write-Log "plans(page=1) -> pushed"
        }
        "page1" {
            # 页1 渲染器只用天气/额度/计划，news/markets 交给页2/页3 与定时轮播刷新；
            # today 模式受 TTL 门控，缓存新鲜时秒出图
            Invoke-RenderAndCommitPage "today" -TargetPage 1 -Force:$Force
            Write-Log "page1(日常信息页) -> pushed"
        }
        "page2" {
            Invoke-RenderAndCommitPage "news" -TargetPage 2 -Force:$Force
            Write-Log "page2(热点新闻页) -> pushed"
        }
        "page3" {
            Invoke-RenderAndCommitPage "markets" -TargetPage 3 -Force:$Force
            Write-Log "page3(股市信息页) -> pushed"
        }
        "page4" {
            Invoke-RenderAndCommitPage "insight" -TargetPage 4 -Force:$Force
            Write-Log "page4(AI认知洞察页) -> pushed"
        }
        "analysis" {
            Invoke-RenderAndCommitPage "analysis" -TargetPage 4
            Write-Log "analysis(page=4 强制重新生成认知洞察) -> pushed"
        }
        "page5" {
            Invoke-RenderAndCommitPage "markets" -TargetPage 5 -Force:$Force
            Write-Log "page5(智谱AI今日走势分析页) -> pushed"
        }
        "stock" {
            Invoke-RenderAndCommitPage "stock" -TargetPage 5
            Write-Log "stock(page=5 强制重生成) -> pushed"
        }
        "news" {
            # 手动单模块命令语义 = 明确要求联网刷新该模块，不受切页 TTL 限制
            Invoke-RenderAndCommitPage "news" -TargetPage 2 -Force
            Write-Log "news(page=2) -> pushed"
        }

        "markets" {
            Invoke-RenderAndCommitPage "markets" -TargetPage 3 -Force
            Write-Log "markets(page=3) -> pushed"
        }
        "refresh" {
            $target = ((Get-PageState) % 5) + 1
            Invoke-RenderAndCommitPage "full" -TargetPage $target
            Write-Log "refresh(full page=$target) -> pushed"
        }
        "preview" {
            $page = if ($Page -in 1..5) { $Page } else { Get-PageState }
            Invoke-Render $RenderMode -Page $page -Force:$Force
            Write-Host "== 仅渲染，未推送。看效果: dashboard_portrait.png =="
            Write-Log "preview mode=$RenderMode page=$page"
        }
        "clear" {
            Invoke-RenderTest "white"
            Invoke-Push -MaxRetries $PushRetries
            Write-Log "clear(white) -> pushed"
        }
        "status" {
            Write-Host "===== 仪表盘状态 ====="
            $curPage = Get-PageState
            $curPageName = switch ($curPage) { 1 { "今日看板" } 2 { "三栏新闻" } 3 { "行情" } 4 { "认知洞察" } 5 { "智谱AI今日走势分析" } default { "页$curPage" } }
            Write-Host ("当前页面: 页{0}（{1}）" -f $curPage, $curPageName)
            # 串口设备在线状态：拔出 USB 后这里会显示离线，插回（哪怕换了 USB 口）推送会自动找回
            $ports = [System.IO.Ports.SerialPort]::GetPortNames()
            if ($ports -contains $PortName) {
                Write-Host ("串口设备: {0} 在线" -f $PortName)
            } elseif ($ports.Count -gt 0) {
                Write-Host ("串口设备: {0} 离线（当前存在的串口: {1}）" -f $PortName, ($ports -join ", "))
            } else {
                Write-Host ("串口设备: {0} 离线（系统无任何串口，USB 未连接）" -f $PortName)
            }
            if (Test-Path -LiteralPath $CacheFile) {
                $cache = [System.IO.File]::ReadAllText($CacheFile, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
                if ($cache.updated_at) {
                    $age = (New-TimeSpan -Start ([datetime]::Parse($cache.updated_at, $InvariantCulture)) -End (Get-Date)).TotalMinutes
                    Write-Host ("缓存更新: {0}（{1} 分钟前）" -f $cache.updated_at, [math]::Round($age, 1))
                }
                if ($cache.weather) {
                    Write-Host ("天气: {0}°C {1}，湿度 {2}%，更新 {3}" -f $cache.weather.temperature, $cache.weather.description, $cache.weather.humidity, $cache.weather.updated)
                } else { Write-Host "天气: 无缓存" }
                if ($cache.glm) {
                    foreach ($k in $cache.glm.quotas.PSObject.Properties.Name) {
                        $q = $cache.glm.quotas.$k
                        Write-Host ("GLM {0}: 剩 {1:N0}/{2:N0}（{3}%），重置 {4}" -f $k, $q.remaining, $q.total, $q.percent, $q.reset)
                    }
                } else { Write-Host "GLM Coding Plan: 无缓存" }
                if ($cache.plans) {
                    Write-Host ("计划: {0} 项" -f $cache.plans.Count)
                    foreach ($item in $cache.plans) { Write-Host "  - $item" }
                } else { Write-Host "计划: 无" }
                if ($cache.analysis) {
                    $a = $cache.analysis
                    $staleMark = if ($a.stale) { " [历史]" } else { "" }
                    Write-Host ("认知洞察: {0} · 更新 {1}（模型 {2}）{3}" -f $a.domain, $a.updated, $a.model, $staleMark)
                } else { Write-Host "认知洞察: 未生成（触发页4时自动生成，或手动运行 analysis）" }
                if ($cache.stock_analysis) {
                    $s = $cache.stock_analysis
                    $staleMark = if ($s.stale) { " [历史]" } else { "" }
                    Write-Host ("智谱AI分析: 更新 {0}（模型 {1}）{2}" -f $s.updated, $s.model, $staleMark)
                } else { Write-Host "智谱AI分析: 未生成（交易时段轮播到页5时自动生成，或手动运行 stock）" }
            } else {
                Write-Host "尚无渲染缓存（dashboard_data.json 不存在，先运行 preview 或 refresh）"
            }
            Write-Log "status"
        }
        default {
            Write-Host "用法: .\dashboard_control.ps1 <命令> [-PortName <你的串口>] [-Force]"
            Write-Host "  命令:"
            Write-Host "    refresh   更新全部并推送"
            Write-Host "    weather   只更新天气并推送"
            Write-Host "    plans     只更新计划并推送（可用 -PlansText 'a; b' 顺带改计划）"
            Write-Host "    news      只更新热点新闻并推送（跳过缓存TTL）"
            Write-Host "    markets   只更新行情并推送（跳过缓存TTL）"
            Write-Host "    page1-5   切页并推送；缓存TTL内直接用缓存秒出图，加 -Force 强制联网刷新"
            Write-Host "    analysis  强制重新生成认知洞察并推送到页4"
            Write-Host "    stock     强制重新生成智谱AI分析并推送到页5"
            Write-Host "    test      测试图案（-Pattern info|chess|white|black）"
            Write-Host "    clear     清屏（全白）"
            Write-Host "    preview   只渲染不推送（-RenderMode full|today|weather|plans|news|markets|analysis|stock）"
            Write-Host "    status    查看状态"
        }
    }
} catch {
    Write-Host ("操作失败：{0}" -f $_.Exception.Message) -ForegroundColor Red
    Write-Log "FAIL $Command : $($_.Exception.Message)"
    exit 1
} finally {
    if ($HasMutex) { $Mutex.ReleaseMutex() | Out-Null }
    $Mutex.Dispose()
}
