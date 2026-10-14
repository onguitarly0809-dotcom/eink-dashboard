# ESP8266 固件分析报告（dashboard_serial.ino + EPDSerial.h）

> 2026-08-26 完备性评估产出，2026-09-01 V2.5 提速改造**已修改固件**（见文末"V2.5 变更"），
> 需用 Arduino IDE 重新编译烧录（板型 NodeMCU 1.0 / ESP-12E，端口按 EPD_SERIAL_PORT 或设备管理器确认）。

## 协议回顾

PC（epd_dashboard/push.py，send_dashboard.ps1 为手动调试备胎）与固件的串口协议：

```
PC -> 固件: PING            固件 -> PC: PONG
PC -> 固件: BEGIN 48000     固件 -> PC: EPD INIT / READY
循环 94 次:  PC 发 512 字节   固件回 ACK <累计字节数>   （V2.5：旧固件为 375×128B）
PC -> 固件: DATA OK / REFRESH   固件 -> PC: DATA OK / REFRESHING / DONE / ERR BUSY
```

波特率：V2.5 固件 921600（旧固件 115200）。push.py 自动协商两个波特率，固件刷前刷后都能推。

## 已知隐患（按严重度）

### 1. `epd_wait_idle` 无超时（EPDSerial.h，高危）——**V2.5 已修复**
`while (digitalRead(BUSY) == LOW) delay(10);` —— BUSY 引脚虚焊、屏未响应或 busy 极性与批次不符时**永久死循环**，只能断电重启；PC 端只能看到超时。
V2.5：加 25s 超时返回 false；`epd_init()` 失败回 ERR INIT，REFRESH 失败回 `ERR BUSY`，PC 端能拿到明确错误。

### 1b. Soft WDT reset（V2.5 根因定位并修复，原"间歇性推送失败"的真凶）
旧 `epd_begin_stream` 在 BEGIN 后用 bit-bang 把旧帧 RAM（0x10）写全白：48000B × 每字节 16 次
digitalWrite 的 tight loop 耗时 3 秒以上，正好踩在 ESP8266 软看门狗（约 3.2s 无 yield）边界——
临界状态下时崩时不崩（control.log 2026-08-31 08:30-08:53 连续失败、09-01 10:43 成功即此规律）。
V2.5：直接跳过白屏预清（全刷波形本身整屏黑白翻转，旧帧内容不影响最终显示），READY 即时返回，
风险源一并消除。若个别屏幕批次出现异常残影，恢复方法：在 `epd_begin_stream` 里按行写 0x10
并在每行间插 `yield()`。

### 2. 中断后状态残留（send_dashboard.ps1 + ino，中危）
上次传输在 STATE_DATA 中途断开时固件停留在收数据状态；本次的 `\r\n` 和 `PING` 会被当作图像数据吃进缓冲，依赖固件 5 秒超时自愈。PC 端 PING 重试总时长（5×(2s 超时+0.5s 间隔)）刚好覆盖，时序脆弱。
建议（PC 侧即可缓解）：连接后先发一个 `RESET` 类命令或延时 6 秒再握手；固件侧可在收到非图像期的不完整数据时立即 reset_receiver。

### 3. 传输无校验和/CRC（中危）
ACK 只确认累计字节数，128 字节块内位翻转无检测，屏幕直接显示坏点。棋盘格测试图案是当前唯一的人工诊断手段。
建议：协议升级为 `ACK <bytes> <crc8>`，PC 侧重传不匹配块。需两端同步改。

### 4. 三份重复的 bit-bang 代码（EPDSerial.h，维护性）
`epd_command` / `epd_data_byte` / `epd_data` 三个函数各自复制了软件 SPI 时序，改时序要改三处。
建议：提取 `epd_write_bit(byte)` 公共函数。

### 5. 初始化命令序列裸魔法数字（维护性）
0x01/0x06/0x61/0x82... 无寄存器名注释，与厂家 datasheet 对照困难（datasheet 在 `<本地 datasheet 目录>`）。

### 6. 其他
- `Serial.readStringUntil('\n')` 受 `setTimeout(5000)` 影响，半条命令会阻塞 loop 5 秒（低危）。
- ACK 输出 `printf` 与 `println` 混用（`\r\n` 一致，仅风格问题）。
- 缓冲区边界检查已核实无溢出（48000 % 100 == 0，`row_index` 恰好在 EPD_ROW_BYTES 归零）。

## 协议参数同步点（改屏幕尺寸时各处必须一致）

| 位置 | 参数 |
|---|---|
| `epd_dashboard/config.py` | `EPD_WIDTH/EPD_HEIGHT` → `EPD_IMAGE_BYTES`（当前 48000）、`EPD_SERIAL_PORT` |
| `epd_dashboard/push.py` | `BAUD_CANDIDATES = ((921600, 512), (115200, 128))`（协商表） |
| `EPDSerial.h` / `.ino` | `EPD_IMAGE_BYTES`、`kChunkSize = 512`、`EPD_ROW_BYTES = 100`、`Serial.begin(921600)`、`setRxBufferSize(2048)` |
| `send_dashboard.ps1`（手动调试备胎） | `$BaudRate = 115200`、`$chunkSize = 128`——只匹配旧固件，推新固件需手动改这两个参数 |

## V2.5 变更清单（2026-09-01）

1. `Serial.begin(115200)` → `921600`，`setup()` 加 `Serial.setRxBufferSize(2048)`（ESP8266 默认 256B，512B 块必须扩）
2. `kChunkSize` 128 → 512（ACK 次数 375 → 94，停等往返开销约降 4/5）
3. `epd_begin_stream` 跳过旧帧白屏预清（Soft WDT 根因修复 + READY 即时）
4. `epd_wait_idle` 加 25s 超时；`epd_refresh_and_sleep` 返回 bool，REFRESH 失败回 `ERR BUSY`
5. 传输 48000B 纯耗时：115200/128B 停等约 9s → 921600/512B 约 1.2s
