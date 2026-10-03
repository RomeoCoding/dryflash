// Minimal Verus-style Arduino sketch for the dryflash compatibility check: Wire (MPU-6050,
// ADS1115), SPI through Adafruit_MAX31855's hardware-SPI constructor, digitalRead/digitalWrite.
#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <Adafruit_MAX31855.h>

#define TC_CS 5
#define ADS_ADDR 0x49
Adafruit_MAX31855 tc(TC_CS);  // hardware SPI (VSPI: SCK 18, MISO 19)

static uint8_t rd8(uint8_t addr, uint8_t reg) {
  Wire.beginTransmission(addr); Wire.write(reg); Wire.endTransmission(false);
  Wire.requestFrom(addr, (uint8_t)1);
  return Wire.read();
}
static int16_t rd16(uint8_t addr, uint8_t reg) {
  Wire.beginTransmission(addr); Wire.write(reg); Wire.endTransmission(false);
  Wire.requestFrom(addr, (uint8_t)2);
  int16_t v = Wire.read() << 8; v |= Wire.read();
  return v;
}
static void wr(uint8_t addr, uint8_t reg, const uint8_t *b, int n) {
  Wire.beginTransmission(addr); Wire.write(reg); Wire.write(b, n); Wire.endTransmission();
}

void setup() {
  Serial.begin(115200);
  pinMode(25, OUTPUT);
  pinMode(27, INPUT_PULLUP);
  Wire.begin(21, 22);
  Serial.printf("ARD who_am_i=0x%02x\n", rd8(0x68, 0x75));
  uint8_t wake = 0x01; wr(0x68, 0x6B, &wake, 1);
  uint8_t cfg[2] = {0x44, 0xE3}; wr(ADS_ADDR, 0x01, cfg, 2);
  Serial.printf("ARD max31855 begin=%d\n", tc.begin());
}

void loop() {
  static int led = 0;
  led = !led;
  digitalWrite(25, led);
  float ax = rd16(0x68, 0x3B) / 16384.0;
  float ain0 = rd16(ADS_ADDR, 0x00) * 2.048 / 32768.0;
  double c = tc.readCelsius();
  uint8_t err = tc.readError();
  Serial.printf("ARD ax=%.4f ain0=%.4f tc=%.2f err=%u btn=%d\n", ax, ain0, c, err, digitalRead(27));
  delay(500);
}
