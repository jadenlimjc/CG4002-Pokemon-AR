#include "passiveBuzzer.h"
#include "DualPrint.h"

#define NOTE_C6 1047
#define NOTE_E6 1319
#define NOTE_G6 1568
#define NOTE_C7 2093

PassiveBuzzer::PassiveBuzzer(int pin, int freq, int resolution)
  : pin_(pin), freq_(freq), resolution_(resolution) {}

bool PassiveBuzzer::begin() {
  bool isAttached = ledcAttach(pin_, freq_, resolution_);
  dbg.print("Buzzer PWM: ");
  dbg.println(isAttached ? "OK" : "FAILED");
  return isAttached;
}


void PassiveBuzzer::playStartSound() {
  int notes[]     = {NOTE_C6, NOTE_E6, NOTE_G6, NOTE_C7};
  int durations[] = {100, 100, 100, 150};
  for (int i = 0; i < 4; i++) {
    ledcWriteTone(pin_, notes[i]);
    delay(durations[i]);
    ledcWriteTone(pin_, 0);
    delay(30);  // gap between notes
  }
}

void PassiveBuzzer::playEndSound() {
  int notes[]     = {NOTE_G6, NOTE_E6, NOTE_C6};
  int durations[] = {150, 150, 300};
  for (int i = 0; i < 3; i++) {
    ledcWriteTone(pin_, notes[i]);
    delay(durations[i]);
    ledcWriteTone(pin_, 0);
    delay(30);
  }
}
void PassiveBuzzer::on(uint32_t frequency) { 
  ledcWriteTone(pin_, frequency); 
}

void PassiveBuzzer::off() { 
  ledcWriteTone(pin_, 0); 
}