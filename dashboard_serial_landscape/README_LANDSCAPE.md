# dashboard_serial_landscape（横版全页 · 当前运营方向）

墨水屏硬件**横放**（800×480 原生方向，从竖放顺时针转 90°）的整页看板变体，五页：
今日看板（田字格+月历+洗车指数）/ 三栏新闻（24 字 AI 摘要）/ 行情 / 认知洞察
（固定分栏+机制流程图）/ 智谱AI 走势归因。

> **2026-09-23 重构**：横竖两份 `epd_dashboard` 拷贝合并为仓库根共享包（版式差异在
> `epd_dashboard/layouts/landscape.py`，渲染器在 `renderers/landscape/`）。本目录保留
> 运行期文件、字体资产（fonts/ 含宋体/tabler）、web 前端与薄入口；回退点：git 标签
> `pre-refactor-20260923`。竖版 `../dashboard_serial/` 同构保留。

## 运营层（已从竖版迁移，2026-09-21 起默认横版运营）

- 计划任务 `EPD_Dashboard_Refresh` → 本目录 `epd_refresh_hidden.vbs` → `dashboard_control.ps1`
  （轮播页1-5、TTL 缓存、互斥锁与竖版同机制）
- Web 控制台 `dashboard_web.py`（8080）+ 全局热键 `dashboard_hotkeys.py`（M1-M5/F13-F17），
  登录自启 `EPD_Web_Start.vbs` 指向本目录
- **横竖一键切换**：`python ../switch_orientation.py landscape|portrait`
  （改计划任务指向 + 重写自启 VBS + 重启控制台/热键；Web 控制台里有"一键切换"按钮）
  切换不改动任何变体目录内容；当前方向看 `../ACTIVE_ORIENTATION.txt`

> 注：切换用 Python 实现（`switch_orientation.py`）。曾尝试 PowerShell 版
> `set_orientation.ps1` 被 Defender 按脚本启发式误报删除；Python 版稳定存活。
> 若日后仍遇误报，管理员 PowerShell 执行
> `Add-MpPreference -ExclusionPath "<项目根目录>"` 加项目目录排除。

## 设计体系（V4 定稿）

1. 字体：阅读层=思源黑体（16-20px），展示层=Tabler Icons 线稿图标字体（MIT，
   `fonts/tabler/`，`common.draw_tabler`）；像素字已退役
2. 版式语言：8px 紧边距+1px 外框、黑标题带（白字黑体+图标+右侧 16px 元信息）、
   12.5% 抖动灰条、1px 发丝分割线、N 等分栅格、居中细字占位
3. 页1 田字格黄金分割列宽；页2 三栏五等分+24字摘要；页3 三栏六等分；
   页4/5 双栏正文（真实字体度量、固定/均衡分栏、字号自适应与生成端字数配额联动）

## 设计体系 V3（墨水屏美学，调研 TRMNL Framework 后落地）

1. **全页 Fusion Pixel 中文像素字**（`fonts/` 内 OFL 开源字体，8/10/12px 三档原生字号）；
   `fonts.py` 把任意请求字号吸附到整数倍格栅，全页统一点阵纹理，墨水屏 1-bit 下零灰阶残留
2. **抖动灰阶**（`renderers/common.py` 的 `dither_rect/dither_polygon`）：数据格 12.5% 底纹、
   电量条空格 25%、折线图下方 25% 填充——1-bit 屏的"灰阶"设计材料
3. **1px 线纪律**：全页唯一重锚是黑色报头条（页1/6）与报告页主标题 2px 下划线（页4/5）
4. **统一标签语言**：黑底白字 chip（`draw_chip`）+ 手工字距小标签 + 描边粗数值（`text_bold`），
   页 1-6 家族脸一致

## 页面（全部原生横屏 800×480，orientation=none，无需旋转）

| 页 | 内容 | 布局 |
|---|---|---|
| 1 | 今日看板 | 黑报头 + 巨型位图温度 + 天况列 + 2×2 抖动数据格 + 工作计划/GLM 额度 |
| 2 | 三栏新闻 | 国内/国际/AI，每栏 5 条（单条最多两行，超长"…"截断） |
| 3 | 行情 | 我的关注 ｜ 板块热点 ｜ 市场参考，各 6 行双行条目 |
| 4 | AI 认知洞察 | chip 标题栏 + 双栏正文自适应字号，剩余高度均摊块间距 |
| 5 | 智谱AI 走势归因 | 分时折线（抖动填充，大盘对照进图头）+ 双栏正文 |
| 6 | 横版天气整页 | 黑报头 + 巨字温度/罗盘/月相 + 抖动数据格 + 5日卡 + 双图表 |

## 用法（与竖版命令完全一致，在本目录执行）

```bat
python render_dashboard.py --mode full                 REM 全量抓数据 + 页1
python render_dashboard.py --mode today --page 2       REM 按键切页（TTL 内秒出）
python render_dashboard.py --mode weather --page 6 --push
```

## 与竖版的差异点

- `config.py`：`WIDTH/HEIGHT = 800/480`；三栏锚点 `COLUMN_X/COLUMN_W/COLUMN_BOX`
- `fonts.py`：像素字优先 + 格栅吸附（竖版仍为思源黑体）
- `renderers/common.py`：`draw_box`（chip 标题/1px）、抖动件、chip/label/text_bold
- 所有页面直接画 800×480 画布，`--orientation` 默认 `none`
- 输出/缓存/日志都落在本目录，串口由 `EPD_SERIAL_PORT` 指定：**两个变体不要同时推送**

## 尚未迁移（仍在竖版目录）

Web 控制台（dashboard_web.py + web/）、热键（dashboard_hotkeys.py）、
控制脚本（dashboard_control.ps1 / dashboard_menu.ps1）、计划任务 VBS。
横版版面确认后按需移植。
