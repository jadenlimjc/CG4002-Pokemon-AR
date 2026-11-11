#include "passiveBuzzer.h"

PassiveBuzzer::PassiveBuzzer(int pin, int freq, int resolution)
  : pin_(pin), freq_(freq), resolution_(resolution) {}

bool PassiveBuzzer::begin() {
  bool isAttached = ledcAttach(pin_, freq_, resolution_);
  Serial.print("Buzzer PWM: ");
  Serial.println(isAttached ? "OK" : "FAILED");
  return isAttached;
}


void PassiveBuzzer::on(uint32_t frequency) { 
  ledcWriteTone(pin_, frequency); 
}

void PassiveBuzzer::off() { 
  ledcWriteTone(pin_, 0); 
}
