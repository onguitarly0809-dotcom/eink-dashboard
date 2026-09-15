#ifndef EPD_SERIAL_H
#define EPD_SERIAL_H

#include <Arduino.h>

#define EPD_WIDTH 800
#define EPD_HEIGHT 480
#define EPD_ROW_BYTES (EPD_WIDTH / 8)
#define EPD_IMAGE_BYTES (EPD_ROW_BYTES * EPD_HEIGHT)

#define EPD_SCK_PIN 14
#define EPD_MOSI_PIN 13
#define EPD_CS_PIN 15
#define EPD_RST_PIN 2
#define EPD_DC_PIN 4
#define EPD_BUSY_PIN 5

static void epd_delay(unsigned int milliseconds) {
  delay(milliseconds);
}

static void epd_command(uint8_t command) {
  digitalWrite(EPD_DC_PIN, LOW);
  digitalWrite(EPD_CS_PIN, LOW);
  for (uint8_t mask = 0x80; mask; mask >>= 1) {
    digitalWrite(EPD_MOSI_PIN, (command & mask) ? HIGH : LOW);
    digitalWrite(EPD_SCK_PIN, HIGH);
    digitalWrite(EPD_SCK_PIN, LOW);
  }
  digitalWrite(EPD_CS_PIN, HIGH);
}

static void epd_data_byte(uint8_t value) {
  digitalWrite(EPD_DC_PIN, HIGH);
  digitalWrite(EPD_CS_PIN, LOW);
  for (uint8_t mask = 0x80; mask; mask >>= 1) {
    digitalWrite(EPD_MOSI_PIN, (value & mask) ? HIGH : LOW);
    digitalWrite(EPD_SCK_PIN, HIGH);
    digitalWrite(EPD_SCK_PIN, LOW);
  }
  digitalWrite(EPD_CS_PIN, HIGH);
}

static void epd_data(const uint8_t *data, size_t length) {
  digitalWrite(EPD_DC_PIN, HIGH);
  digitalWrite(EPD_CS_PIN, LOW);
  for (size_t index = 0; index < length; index++) {
    const uint8_t value = data[index];
    for (uint8_t mask = 0x80; mask; mask >>= 1) {
      digitalWrite(EPD_MOSI_PIN, (value & mask) ? HIGH : LOW);
      digitalWrite(EPD_SCK_PIN, HIGH);
      digitalWrite(EPD_SCK_PIN, LOW);
    }
  }
  digitalWrite(EPD_CS_PIN, HIGH);
}

static bool epd_wait_idle(uint32_t timeout_ms = 25000) {
  // 无超时的死循环会永久挂死固件（PC 端只能等 DONE 超时），25s 内未就绪返回失败
  uint32_t start = millis();
  while (digitalRead(EPD_BUSY_PIN) == LOW) {
    if (millis() - start > timeout_ms) {
      return false;
    }
    delay(10);
  }
  return true;
}

static void epd_reset() {
  digitalWrite(EPD_RST_PIN, HIGH);
  delay(200);
  digitalWrite(EPD_RST_PIN, LOW);
  delay(2);
  digitalWrite(EPD_RST_PIN, HIGH);
  delay(200);
}

static bool epd_init() {
  pinMode(EPD_SCK_PIN, OUTPUT);
  pinMode(EPD_MOSI_PIN, OUTPUT);
  pinMode(EPD_CS_PIN, OUTPUT);
  pinMode(EPD_RST_PIN, OUTPUT);
  pinMode(EPD_DC_PIN, OUTPUT);
  pinMode(EPD_BUSY_PIN, INPUT);
  digitalWrite(EPD_CS_PIN, HIGH);
  digitalWrite(EPD_SCK_PIN, LOW);

  epd_reset();
  epd_command(0x01);
  epd_data_byte(0x07);
  epd_data_byte(0x07);
  epd_data_byte(0x3f);
  epd_data_byte(0x3f);

  epd_command(0x06);
  epd_data_byte(0x17);
  epd_data_byte(0x17);
  epd_data_byte(0x28);
  epd_data_byte(0x17);

  epd_command(0x04);
  delay(100);
  if (!epd_wait_idle()) {
    return false;
  }

  epd_command(0x00);
  epd_data_byte(0x1f);

  epd_command(0x61);
  epd_data_byte(0x03);
  epd_data_byte(0x20);
  epd_data_byte(0x01);
  epd_data_byte(0xe0);

  epd_command(0x15);
  epd_data_byte(0x00);

  epd_command(0x50);
  epd_data_byte(0x10);
  epd_data_byte(0x07);

  epd_command(0x60);
  epd_data_byte(0x22);
  return true;
}

static void epd_begin_stream() {
  // 旧版此处先把旧帧 RAM（0x10）用 bit-bang 逐位写全白：48000B × 16 次翻转的 tight loop
  // 跑 3 秒以上，正好踩在 ESP8266 软看门狗边界上——历史上推送间歇性 Soft WDT reset 的根因。
  // 全刷波形本身会整屏黑白翻转，旧帧内容不影响最终显示，直接跳过；READY 由数秒降为即时。
  epd_command(0x13);
}

static bool epd_refresh_and_sleep() {
  epd_command(0x12);
  delay(100);
  if (!epd_wait_idle()) {
    return false;
  }
  epd_command(0x02);
  if (!epd_wait_idle()) {
    return false;
  }
  epd_command(0x07);
  epd_data_byte(0xa5);
  return true;
}

#endif


