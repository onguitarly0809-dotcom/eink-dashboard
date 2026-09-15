#include "EPDSerial.h"

// 与 PC 端 epd_dashboard/push.py 的波特率协商表对应：新固件 921600/512B ACK 块
const uint16_t kChunkSize = 512;
enum State { STATE_COMMAND, STATE_DATA, STATE_COMPLETE };
State state = STATE_COMMAND;
uint8_t row_buffer[EPD_ROW_BYTES];
uint16_t row_index = 0;
uint32_t received_bytes = 0;

void flush_row() {
  epd_data(row_buffer, EPD_ROW_BYTES);
  row_index = 0;
}

void reset_receiver() {
  state = STATE_COMMAND;
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
      if (sscanf(command.c_str(), "BEGIN %lu", &expected) != 1 || expected != EPD_IMAGE_BYTES) {
        Serial.printf("ERR SIZE %lu\r\n", static_cast<unsigned long>(expected));
        return;
      }
      Serial.println("EPD INIT");
      if (!epd_init()) {
        Serial.println("ERR INIT");
        reset_receiver();
        return;
      }
      epd_begin_stream();
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
    uint32_t remaining = EPD_IMAGE_BYTES - received_bytes;
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
      }
    }
    received_bytes += actual;
    Serial.printf("ACK %lu\r\n", static_cast<unsigned long>(received_bytes));
    if (received_bytes == EPD_IMAGE_BYTES) {
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
      if (!epd_refresh_and_sleep()) {
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

