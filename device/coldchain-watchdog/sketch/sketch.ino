// ColdChain Watchdog: STM32 (MCU) side of the Arduino Uno Q.
//
// Responsibilities (kept deliberately small):
//   * read the Modulino Thermo and push readings to the Linux side over Bridge
//   * drive the Modulino Buzzer when the Linux side asks for it
//
// The alarm *decision* lives in python/main.py, which holds the product range
// and the stock-present flag cached from the backend.

#include <Arduino.h>
#include <Arduino_RouterBridge.h>
#include <Arduino_Modulino.h>

ModulinoThermo thermo;
ModulinoBuzzer buzzer;

const unsigned long READ_INTERVAL_MS = 2000;
const unsigned long BEEP_PERIOD_MS = 700;
const size_t BEEP_FREQ_HZ = 2700;
const size_t BEEP_LEN_MS = 350;

volatile bool alarmOn = false;

// Called from Python: Bridge.call("set_alarm", True/False)
bool set_alarm(bool on) {
  alarmOn = on;
  if (!on) {
    buzzer.noTone();
  }
  return alarmOn;
}

void setup() {
  Bridge.begin();
  Monitor.begin();
  Modulino.begin();
  thermo.begin();
  buzzer.begin();

  // provide_safe runs the handler from loop() context, so I2C access is safe.
  Bridge.provide_safe("set_alarm", set_alarm);
}

void loop() {
  static unsigned long lastRead = 0;
  static unsigned long lastBeep = 0;
  unsigned long now = millis();

  if (now - lastRead >= READ_INTERVAL_MS) {
    lastRead = now;
    float tempC = thermo.getTemperature();
    float humidity = thermo.getHumidity();
    Bridge.notify("on_reading", tempC, humidity);
    Monitor.print("temp_c=");
    Monitor.println(tempC, 2);
  }

  if (alarmOn && now - lastBeep >= BEEP_PERIOD_MS) {
    lastBeep = now;
    buzzer.tone(BEEP_FREQ_HZ, BEEP_LEN_MS);
  }

  delay(20);
}
