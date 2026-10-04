#include "vibrationMotor.h"

VibrationMotor::VibrationMotor(int pin, unsigned long runTimeMs)
  : pin_(pin), runTimeMs_(runTimeMs) {}

void VibrationMotor::begin() {
  pinMode(pin_, OUTPUT);
  digitalWrite(pin_, LOW);
}

void VibrationMotor::checkTrigger(bool &trigger, bool &running, unsigned long &startMillis, const char* label) {
  if (trigger && !running) {
    trigger = false;
    running = true;
    startMillis = millis();

    if (!anyPhysicallyOn_) {
      anyPhysicallyOn_ = true;
      pulseStartMillis_ = millis();
    }

    digitalWrite(pin_, HIGH);
    Serial.print("Vibration motor ON (");
    Serial.print(label);
    Serial.println(")");
  }

  if (running && (millis() - startMillis >= runTimeMs_)) {
    running = false;
    Serial.print("Vibration motor OFF (");
    Serial.print(label);
    Serial.println(")");

    if (!anySourceRunning()) {
      digitalWrite(pin_, LOW);
      anyPhysicallyOn_ = false;
      unsigned long total = millis() - pulseStartMillis_;
      Serial.print("Motor fully OFF - continuous buzz lasted ");
      Serial.print(total);
      Serial.println(" ms");
    }
  }
}

void VibrationMotor::registerRunningFlag(bool *flag) {
  if (numFlags_ < MAX_FLAGS) {
    runningFlags_[numFlags_++] = flag;
  }
}

void VibrationMotor::stopAll() {
  digitalWrite(pin_, LOW);
  anyPhysicallyOn_ = false;
  pulseStartMillis_ = 0;
}

bool VibrationMotor::anySourceRunning() const {
  for (int i = 0; i < numFlags_; i++) {
    if (*runningFlags_[i]) {
      return true;
    }
  }
  return false;
}