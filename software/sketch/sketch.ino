// =====================================================================
// BREATHE Vision - STM32U585 sketch (Arduino Core on Zephyr, UNO Q)
//
// * Reads the Modulino Thermo, Knob (and drives the Buzzer) on the Qwiic
//   connector, which is Wire1 on the UNO Q (NOT Wire).
// * Draws 4 bar columns on the 8x13 LED matrix.
// * Talks to the Python app over the Bridge (RPC):
//     Python -> MCU : show_cells(a,b,c,d,flags), beep(pattern)
//     MCU -> Python : thermo(t, rh) once a second, knob(kind, value)
// Rule: inside a provide()/provide_safe() handler do NOT call Bridge.call,
// Monitor.print or Serial.print. We only set flags and do the work in loop().
// =====================================================================
#include <Arduino_RouterBridge.h>
#include <Arduino_LED_Matrix.h>
#include <Arduino_Modulino.h>

Arduino_LED_Matrix matrix;
ModulinoThermo thermo;
ModulinoKnob knob;
ModulinoBuzzer buzzer;

uint8_t frame[104];                 // 8 rows x 13 columns, row-major, brightness 0..7
volatile bool frameDirty = false;
volatile int pendingBeep = 0;       // 1 ok, 2 warn, 3 alarm (3 beeps), 4 click

int beepsLeft = 0;                  // for the 3-beep alarm
unsigned long nextBeepAt = 0;
unsigned long lastThermo = 0, pressStart = 0;
bool wasPressed = false;
int16_t lastKnob = 0;
bool haveThermo = false, haveKnob = false, haveBuzzer = false;

// flags: bit0 thermal, bit1 camera moved, bit2 obstruction, bit3 scanning
void show_cells(int a, int b, int c, int d, int flags) {
  int lv[4] = {a, b, c, d};
  for (int i = 0; i < 104; i++) frame[i] = 0;
  for (int cell = 0; cell < 4; cell++) {
    int col0 = cell * 3;
    int h = constrain(abs(lv[cell]), 0, 8);
    uint8_t bright = (lv[cell] < 0) ? 2 : 7;          // negative = missing / no verdict (dim)
    for (int r = 0; r < h; r++) {
      frame[(7 - r) * 13 + col0] = bright;
      frame[(7 - r) * 13 + col0 + 1] = bright;
    }
  }
  for (int r = 0; r < 4; r++) {
    if (flags & (1 << r)) frame[(2 * r) * 13 + 12] = 7;   // status LEDs in the last column
  }
  frameDirty = true;                                  // drawn in loop()
}

void beep(int pattern) { pendingBeep = pattern; }

void setup() {
  Bridge.begin();
  matrix.begin();
  matrix.setGrayscaleBits(3);
  Modulino.begin(Wire1);                              // Qwiic = Wire1 on the UNO Q
  haveThermo = thermo.begin();
  haveKnob = knob.begin();
  haveBuzzer = buzzer.begin();
  if (haveKnob) lastKnob = knob.get();
  Bridge.provide_safe("show_cells", show_cells);
  Bridge.provide_safe("beep", beep);
  show_cells(1, 1, 1, 1, 0);                          // "alive" pattern until Python takes over
  Monitor.println("BREATHE sketch started");
  Monitor.print("thermo="); Monitor.print(haveThermo);
  Monitor.print(" knob="); Monitor.print(haveKnob);
  Monitor.print(" buzzer="); Monitor.println(haveBuzzer);
}

void loop() {
  unsigned long now = millis();

  if (frameDirty) { matrix.draw(frame); frameDirty = false; }

  if (pendingBeep) {
    int p = pendingBeep;
    pendingBeep = 0;
    if (haveBuzzer) {
      switch (p) {
        case 1: buzzer.tone(1319, 80); break;              // healthy
        case 2: buzzer.tone(880, 200); break;              // watch / thermal / info
        case 3: beepsLeft = 3; nextBeepAt = now; break;     // swelling: 3 x 1760 Hz
        case 4: buzzer.tone(2000, 15); break;              // knob click
      }
    }
  }
  if (beepsLeft > 0 && (long)(now - nextBeepAt) >= 0) {   // buzzer.tone() does not block,
    buzzer.tone(1760, 400);                                // so we space the notes with millis()
    beepsLeft--;
    nextBeepAt = now + 600;
  }

  if (now - lastThermo >= 1000) {                      // air temperature + humidity, 1 Hz
    lastThermo = now;
    if (haveThermo) {
      float t = thermo.getTemperature();
      float rh = thermo.getHumidity();
      Bridge.notify("thermo", t, rh);
    }
  }

  if (haveKnob) {
    int16_t k = knob.get();
    if (k != lastKnob) {
      Bridge.notify("knob", "rotate", (int)(k - lastKnob));
      lastKnob = k;
      if (haveBuzzer) buzzer.tone(2000, 15);
    }
    bool p = knob.isPressed();
    if (p && !wasPressed) pressStart = now;
    if (!p && wasPressed) {
      unsigned long held = now - pressStart;
      Bridge.notify("knob", held >= 1500 ? "long" : "short", (int)held);
    }
    wasPressed = p;
  }
  delay(10);
}
