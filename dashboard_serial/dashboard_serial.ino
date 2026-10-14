#include "EPDSerial.h"

// 与 PC 端 epd_dashboard/push.py 的波特率协商表对应：新固件 921600/512B ACK 块
const uint16_t kChunkSize = 512;
enum State { STATE_COMMAND, STATE_DATA, STATE_COMPLETE };
State state = STATE_COMMAND;
// 帧模式由 BEGIN 尺寸决定：48000=1bit 快刷（默认），96000=4灰两平面（方案四）
bool gray_mode = false;
uint8_t row_buffer[EPD_ROW_BYTES];
uint16_t row_index = 0;
uint32_t received_bytes = 0;

void flush_row() {
  epd_data(row_buffer, EPD_ROW_BYTES);
  row_index = 0;
}

void reset_receiver() {
  state = STATE_COMMAND;
  gray_mode = false;
  row_index = 0;
  received_bytes = 0;
}

void setup() {
  Serial.setRxBufferSize(2048);  // ESP8266 默认 256B，512B ACK 块必须扩软件接收缓冲
  Serial.begin(921600);
  Serial.setTimeout(5000);
  delay(200);
  Serial.println("EPD READY");
}

void loop() {
  if (state == STATE_COMMAND) {
    if (!Serial.available()) {
      return;
    }
    String command = Serial.readStringUntil('\n');
    command.trim();
    if (command.length() == 0) {
      return;
    }
    if (command == "PING") {
      Serial.println("PONG");
      return;
    }
    if (command.startsWith("BEGIN ")) {
      uint32_t expected = 0;
      if (sscanf(command.c_str(), "BEGIN %lu", &expected) != 1
          || (expected != EPD_IMAGE_BYTES && expected != EPD_IMAGE_BYTES_4G)) {
        Serial.printf("ERR SIZE %lu\r\n", static_cast<unsigned long>(expected));
        return;
      }
      gray_mode = (expected == EPD_IMAGE_BYTES_4G);
      Serial.println("EPD INIT");
      bool ok = gray_mode ? epd_init_4gray() : epd_init();
      if (!ok) {
        Serial.println("ERR INIT");
        reset_receiver();
        return;
      }
      if (gray_mode) {
        epd_begin_stream_4gray();
      } else {
        epd_begin_stream();
      }
      state = STATE_DATA;
      received_bytes = 0;
      row_index = 0;
      Serial.println("READY");
      return;
    }
    Serial.println("ERR COMMAND");
    return;
  }

  if (state == STATE_DATA) {
    // 尾块不足 kChunkSize 时按剩余字节数收（48000 % 512 == 384，不能假设整除）
    uint32_t frame_bytes = gray_mode ? EPD_IMAGE_BYTES_4G : EPD_IMAGE_BYTES;
    uint32_t remaining = frame_bytes - received_bytes;
    uint16_t want = (remaining < kChunkSize) ? (uint16_t)remaining : kChunkSize;
    uint8_t chunk[kChunkSize];
    size_t actual = Serial.readBytes(chunk, want);
    if (actual != want) {
      Serial.printf("ERR SHORT %lu\r\n", static_cast<unsigned long>(actual));
      reset_receiver();
      return;
    }
    for (uint16_t index = 0; index < want; index++) {
      row_buffer[row_index++] = chunk[index];
      if (row_index == EPD_ROW_BYTES) {
        flush_row();
        // 四灰平面切换必须在行刷新点判定：512B 块会跨过 48000 边界
        // （48000%512=384），块级 received_bytes==48000 永远不成立，
        // 曾导致整帧 96KB 全写进 0x10、0x13 残留旧帧而花屏
        if (gray_mode && received_bytes + index + 1 == EPD_IMAGE_BYTES) {
          epd_switch_plane_4gray();
        }
      }
    }
    received_bytes += actual;
    Serial.printf("ACK %lu\r\n", static_cast<unsigned long>(received_bytes));
    if (received_bytes == frame_bytes) {
      if (row_index != 0) {
        Serial.println("ERR ALIGN");
        reset_receiver();
        return;
      }
      state = STATE_COMPLETE;
      Serial.println("DATA OK");
    }
    return;
  }

  if (state == STATE_COMPLETE) {
    if (!Serial.available()) {
      return;
    }
    String command = Serial.readStringUntil('\n');
    command.trim();
    if (command == "REFRESH") {
      Serial.println("REFRESHING");
      bool ok = gray_mode ? epd_refresh_and_sleep_4gray() : epd_refresh_and_sleep();
      if (!ok) {
        Serial.println("ERR BUSY");
        reset_receiver();
        return;
      }
      Serial.println("DONE");
      reset_receiver();
    } else if (command.length() > 0) {
      Serial.println("ERR STATE");
      reset_receiver();
    }
  }
}

