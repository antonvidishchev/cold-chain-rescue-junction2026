// ColdChain Watchdog: STM32 (MCU) side of the Arduino Uno Q.
//
//   * reads the Modulino Thermo every 2 s and notifies Python ("on_reading")
//   * plays non-blocking buzzer patterns on the Modulino Buzzer
//   * drives the built-in 8x13 LED matrix: temperature, marquee text, alarm
//   * polls the Modulino Knob and notifies Python ("on_knob", +clockwise detents)
//
// Bridge functions called from python/main.py:
//   play_pattern(int)   0 stop, 1 unfreeze, 2 urgent, 3 doors, 4 urgent reminder, 5 ack chirp
//   show_text(String)   scrolling marquee, repeats until another show_* call
//   show_alarm(String)  alternates a warning sign and the text (e.g. "P1")
//   show_temp()         idle: current temperature

#include <Arduino.h>
#include <Arduino_LED_Matrix.h>
#include <Arduino_Modulino.h>
#include <Arduino_RouterBridge.h>

Arduino_LED_Matrix matrix;
ModulinoThermo thermo;
ModulinoBuzzer buzzer;
ModulinoKnob knob;
bool knobOk = false;
int16_t knobLast = 0;
// Flip to -1 if turning the knob clockwise makes knob.get() count down.
const int KNOB_CW_SIGN = 1;
const unsigned long KNOB_POLL_MS = 50;
const int16_t KNOB_MAX_STEP = 8;  // detents per poll; more means a glitch
// DEMO ONLY: added to every Thermo reading so a room-temperature board looks
// like a fridge (~22 C -> ~2 C). Set to 0.0 for real readings.
const float DEMO_TEMP_OFFSET_C = -20.0;

// ---------------------------------------------------------------- matrix
const uint8_t ROWS = 8;
const uint8_t COLS = 13;
const uint8_t ON = 7;  // grayscale brightness (3 bits)
uint8_t frame[ROWS * COLS];

// 5x7 font, column-wise, bit 0 = top row.
struct Glyph {
  char c;
  uint8_t cols[5];
};
const Glyph FONT[] = {
  {' ', {0x00, 0x00, 0x00, 0x00, 0x00}}, {'!', {0x00, 0x00, 0x5F, 0x00, 0x00}},
  {'-', {0x08, 0x08, 0x08, 0x08, 0x08}}, {'.', {0x00, 0x60, 0x60, 0x00, 0x00}},
  {'0', {0x3E, 0x51, 0x49, 0x45, 0x3E}}, {'1', {0x00, 0x42, 0x7F, 0x40, 0x00}},
  {'2', {0x42, 0x61, 0x51, 0x49, 0x46}}, {'3', {0x21, 0x41, 0x45, 0x4B, 0x31}},
  {'4', {0x18, 0x14, 0x12, 0x7F, 0x10}}, {'5', {0x27, 0x45, 0x45, 0x45, 0x39}},
  {'6', {0x3C, 0x4A, 0x49, 0x49, 0x30}}, {'7', {0x01, 0x71, 0x09, 0x05, 0x03}},
  {'8', {0x36, 0x49, 0x49, 0x49, 0x36}}, {'9', {0x06, 0x49, 0x49, 0x29, 0x1E}},
  {'A', {0x7E, 0x11, 0x11, 0x11, 0x7E}}, {'B', {0x7F, 0x49, 0x49, 0x49, 0x36}},
  {'C', {0x3E, 0x41, 0x41, 0x41, 0x22}}, {'D', {0x7F, 0x41, 0x41, 0x22, 0x1C}},
  {'E', {0x7F, 0x49, 0x49, 0x49, 0x41}}, {'F', {0x7F, 0x09, 0x09, 0x09, 0x01}},
  {'G', {0x3E, 0x41, 0x49, 0x49, 0x7A}}, {'H', {0x7F, 0x08, 0x08, 0x08, 0x7F}},
  {'I', {0x00, 0x41, 0x7F, 0x41, 0x00}}, {'J', {0x20, 0x40, 0x41, 0x3F, 0x01}},
  {'K', {0x7F, 0x08, 0x14, 0x22, 0x41}}, {'L', {0x7F, 0x40, 0x40, 0x40, 0x40}},
  {'M', {0x7F, 0x02, 0x0C, 0x02, 0x7F}}, {'N', {0x7F, 0x04, 0x08, 0x10, 0x7F}},
  {'O', {0x3E, 0x41, 0x41, 0x41, 0x3E}}, {'P', {0x7F, 0x09, 0x09, 0x09, 0x06}},
  {'Q', {0x3E, 0x41, 0x51, 0x21, 0x5E}}, {'R', {0x7F, 0x09, 0x19, 0x29, 0x46}},
  {'S', {0x46, 0x49, 0x49, 0x49, 0x31}}, {'T', {0x01, 0x01, 0x7F, 0x01, 0x01}},
  {'U', {0x3F, 0x40, 0x40, 0x40, 0x3F}}, {'V', {0x1F, 0x20, 0x40, 0x20, 0x1F}},
  {'W', {0x3F, 0x40, 0x38, 0x40, 0x3F}}, {'X', {0x63, 0x14, 0x08, 0x14, 0x63}},
  {'Y', {0x07, 0x08, 0x70, 0x08, 0x07}}, {'Z', {0x61, 0x51, 0x49, 0x45, 0x43}},
};
const uint8_t GLYPH_W = 6;  // 5 columns + 1 gap

const uint8_t *glyphFor(char c) {
  c = toupper(c);
  for (const Glyph &g : FONT) {
    if (g.c == c) return g.cols;
  }
  return FONT[0].cols;  // unknown -> space
}

// Warning sign: triangle with an exclamation mark.
const char *WARNING_ICON[ROWS] = {
  "......#......",
  ".....#.#.....",
  "....#.#.#....",
  "....#.#.#....",
  "...#..#..#...",
  "...#.....#...",
  "..#...#...#..",
  ".###########.",
};

// 3x5 digits for the temperature, one byte per row, bit 2 = leftmost column.
const uint8_t DIGITS[10][5] = {
  {7, 5, 5, 5, 7}, {2, 6, 2, 2, 7}, {7, 1, 7, 4, 7}, {7, 1, 7, 1, 7}, {5, 5, 7, 1, 1},
  {7, 4, 7, 1, 7}, {7, 4, 7, 5, 7}, {7, 1, 1, 1, 1}, {7, 5, 7, 5, 7}, {7, 5, 7, 1, 7},
};
const uint8_t MINUS[5] = {0, 0, 7, 0, 0};
const uint8_t DEGREE[5] = {3, 3, 0, 0, 0};

enum DisplayMode { MODE_TEMP, MODE_TEXT, MODE_ALARM };
DisplayMode mode = MODE_TEMP;
char text[48] = "";
uint16_t textWidth = 0;
int scrollPos = 0;
unsigned long nextFrameAt = 0;
uint8_t alarmPhase = 0;  // 0 icon, 1 text
float lastTemp = NAN;

const unsigned long SCROLL_MS = 90;
const unsigned long ICON_MS = 900;
const unsigned long SHORT_TEXT_MS = 1300;

void drawTextAt(int offset) {
  // Column x of the matrix shows column (offset + x) of the text.
  memset(frame, 0, sizeof(frame));
  size_t len = strlen(text);
  for (int x = 0; x < COLS; x++) {
    int src = offset + x;
    if (src < 0 || src >= (int)(len * GLYPH_W)) continue;
    uint8_t col = src % GLYPH_W;
    if (col >= 5) continue;
    uint8_t bits = glyphFor(text[src / GLYPH_W])[col];
    for (uint8_t y = 0; y < 7; y++) {
      if (bits & (1 << y)) frame[y * COLS + x] = ON;
    }
  }
  matrix.draw(frame);
}

void drawIcon() {
  for (uint8_t y = 0; y < ROWS; y++) {
    for (uint8_t x = 0; x < COLS; x++) {
      frame[y * COLS + x] = WARNING_ICON[y][x] == '#' ? ON : 0;
    }
  }
  matrix.draw(frame);
}

void drawSmallGlyph(const uint8_t *rows, uint8_t width, int x, int y) {
  for (uint8_t r = 0; r < 5; r++) {
    for (uint8_t c = 0; c < width; c++) {
      if (rows[r] & (1 << (width - 1 - c))) frame[(y + r) * COLS + x + c] = ON;
    }
  }
}

void drawTemperature(float celsius) {
  memset(frame, 0, sizeof(frame));
  if (isnan(celsius)) {
    drawSmallGlyph(MINUS, 3, 3, 1);
    drawSmallGlyph(MINUS, 3, 7, 1);
    matrix.draw(frame);
    return;
  }
  int value = constrain((int)round(celsius), -9, 99);
  const uint8_t *glyphs[3];
  uint8_t count = 0;
  if (value < 0) {
    glyphs[count++] = MINUS;
    value = -value;
  }
  if (value >= 10) glyphs[count++] = DIGITS[value / 10];
  glyphs[count++] = DIGITS[value % 10];

  int totalWidth = 2 + count * 4;
  int x = (COLS - totalWidth) / 2;
  int y = (ROWS - 5) / 2;
  for (uint8_t i = 0; i < count; i++) {
    drawSmallGlyph(glyphs[i], 3, x, y);
    x += 4;
  }
  drawSmallGlyph(DEGREE, 2, x, y);
  matrix.draw(frame);
}

void setText(const String &s) {
  s.toCharArray(text, sizeof(text));
  textWidth = strlen(text) * GLYPH_W - 1;
}

bool textFits() { return textWidth <= COLS; }

void updateDisplay(unsigned long now) {
  if (now < nextFrameAt) return;
  switch (mode) {
    case MODE_TEMP:
      drawTemperature(lastTemp);
      nextFrameAt = now + 1000;
      break;
    case MODE_TEXT:
      // Enter from the right edge, leave on the left, repeat.
      drawTextAt(scrollPos);
      scrollPos++;
      if (scrollPos > (int)textWidth) scrollPos = -COLS;
      nextFrameAt = now + SCROLL_MS;
      break;
    case MODE_ALARM:
      if (alarmPhase == 0) {
        drawIcon();
        alarmPhase = 1;
        scrollPos = textFits() ? -(COLS - textWidth) / 2 : -COLS;
        nextFrameAt = now + ICON_MS;
      } else if (textFits()) {
        drawTextAt(scrollPos);
        alarmPhase = 0;
        nextFrameAt = now + SHORT_TEXT_MS;
      } else {
        drawTextAt(scrollPos++);
        if (scrollPos > (int)textWidth) alarmPhase = 0;
        nextFrameAt = now + SCROLL_MS;
      }
      break;
  }
}

// ---------------------------------------------------------------- buzzer
enum Pattern { P_STOP = 0, P_UNFREEZE = 1, P_URGENT = 2, P_DOORS = 3, P_REMINDER = 4, P_ACK = 5 };
uint8_t pattern = P_STOP;
unsigned long patternStart = 0;
unsigned long nextToneAt = 0;
uint16_t step = 0;

void startPattern(uint8_t p) {
  pattern = p;
  patternStart = millis();
  nextToneAt = patternStart;
  step = 0;
  if (p == P_STOP) buzzer.noTone();
}

void updateBuzzer(unsigned long now) {
  if (pattern == P_STOP || now < nextToneAt) return;
  unsigned long elapsed = now - patternStart;
  switch (pattern) {
    case P_UNFREEZE:  // two groups of three short beeps
      if (step >= 6) {
        startPattern(P_STOP);
        return;
      }
      buzzer.tone(1500, 120);
      nextToneAt = now + (step == 2 ? 700 : 240);
      step++;
      break;
    case P_URGENT:  // two-tone siren for 10 s, then periodic reminder
      if (elapsed >= 10000) {
        startPattern(P_REMINDER);
        return;
      }
      buzzer.tone(step % 2 ? 1200 : 2000, 250);
      nextToneAt = now + 250;
      step++;
      break;
    case P_REMINDER:  // double chirp every 5 s until reset
      buzzer.tone(2000, 100);
      nextToneAt = now + (step % 2 == 0 ? 200 : 4800);
      step++;
      break;
    case P_ACK:  // two short rising tones: "got it"
      if (step >= 2) {
        startPattern(P_STOP);
        return;
      }
      buzzer.tone(step == 0 ? 1000 : 1800, 120);
      nextToneAt = now + 160;
      step++;
      break;
    case P_DOORS:  // seatbelt-style chime for 15 s
      if (elapsed >= 15000) {
        startPattern(P_STOP);
        return;
      }
      buzzer.tone(880, 200);
      nextToneAt = now + 750;
      step++;
      break;
  }
}

// ---------------------------------------------------------------- bridge
bool play_pattern(int p) {
  startPattern((uint8_t)p);
  return true;
}

bool show_text(String s) {
  setText(s);
  mode = MODE_TEXT;
  scrollPos = -COLS;
  nextFrameAt = 0;
  return true;
}

bool show_alarm(String s) {
  setText(s);
  mode = MODE_ALARM;
  alarmPhase = 0;
  nextFrameAt = 0;
  return true;
}

bool show_temp() {
  mode = MODE_TEMP;
  nextFrameAt = 0;
  return true;
}

void setup() {
  Bridge.begin();
  Monitor.begin();

  matrix.begin();
  matrix.setGrayscaleBits(3);
  matrix.clear();

  Modulino.begin(Wire1);
  thermo.begin();
  buzzer.begin();
  knobOk = knob.begin();
  if (knobOk) knobLast = knob.get();

  // provide_safe runs the handlers from loop() context, so I2C access is safe.
  Bridge.provide_safe("play_pattern", play_pattern);
  Bridge.provide_safe("show_text", show_text);
  Bridge.provide_safe("show_alarm", show_alarm);
  Bridge.provide_safe("show_temp", show_temp);

  buzzer.tone(1000, 150);  // boot chirp
}

void loop() {
  static unsigned long lastRead = 0;
  unsigned long now = millis();

  if (lastRead == 0 || now - lastRead >= 2000) {
    lastRead = now;
    lastTemp = thermo.getTemperature() + DEMO_TEMP_OFFSET_C;
    float humidity = thermo.getHumidity();
    Bridge.notify("on_reading", lastTemp, humidity);
    Monitor.print("temp_c=");
    Monitor.println(lastTemp, 2);
  }

  static unsigned long lastKnob = 0;
  if (knobOk && now - lastKnob >= KNOB_POLL_MS) {
    lastKnob = now;
    int16_t pos = knob.get();
    int16_t delta = pos - knobLast;
    if (delta != 0) {
      knobLast = pos;
      // knob.get() returns 0 on a failed I2C read: drop implausible jumps.
      if (abs(delta) <= KNOB_MAX_STEP) Bridge.notify("on_knob", (int)(delta * KNOB_CW_SIGN));
    }
  }

  updateBuzzer(now);
  updateDisplay(now);
  delay(5);
}
