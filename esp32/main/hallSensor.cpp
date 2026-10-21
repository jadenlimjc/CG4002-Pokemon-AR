#include "hallSensor.h"

HallSensor::HallSensor(int digitalPin, int analogPin)
  : digitalPin_(digitalPin), analogPin_(analogPin) {}

void HallSensor::begin(void (*isrFunc)()) {
  pinMode(digitalPin_, INPUT_PULLUP);
  pinMode(analogPin_, INPUT);
  attachInterrupt(digitalPinToInterrupt(digitalPin_), isrFunc, CHANGE);
}

void HallSensor::end() {
  detachInterrupt(digitalPinToInterrupt(digitalPin_));
}

void HallSensor::onIsr() {
  state_ = digitalRead(digitalPin_);
}

void HallSensor::printStatus() const {
  int liveDigital = digitalRead(digitalPin_);
  Serial.print("Live digital: ");
  Serial.print(liveDigital);
  Serial.print(" | hallState (ISR): ");
  Serial.println(state_);
  Serial.println(state_ == 0 ? "Magnet NEAR" : "Magnet AWAY");
}

int HallSensor::state() const { 
  return state_; 
}