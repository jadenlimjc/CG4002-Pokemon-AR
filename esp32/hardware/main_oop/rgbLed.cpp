#include "rgbLed.h"

RgbLed::RgbLed(int redPin, int greenPin, int bluePin, int freq, int resolution)
  : redPin_(redPin), greenPin_(greenPin), bluePin_(bluePin), freq_(freq), resolution_(resolution) {}

bool RgbLed::begin() {
  bool isRedAttached = ledcAttach(redPin_, freq_, resolution_);
  bool isGreenAttached = ledcAttach(greenPin_, freq_, resolution_);
  bool isBlueAttached = ledcAttach(bluePin_, freq_, resolution_);

  Serial.print("Red PWM: ");   
  Serial.println(isRedAttached ? "OK" : "FAILED");
  Serial.print("Green PWM: "); 
  Serial.println(isGreenAttached ? "OK" : "FAILED");
  Serial.print("Blue PWM: ");  
  Serial.println(isBlueAttached ? "OK" : "FAILED");
  return isRedAttached && isGreenAttached && isBlueAttached;
}

void RgbLed::setColor(uint8_t r, uint8_t g, uint8_t b) {
  ledcWrite(redPin_, r);
  ledcWrite(greenPin_, g);
  ledcWrite(bluePin_, b);
}

void RgbLed::off()   { 
  setColor(0, 0, 0); 
}

void RgbLed::green() { 
  setColor(0, 255, 0); 
}

void RgbLed::red()   { 
  setColor(255, 0, 0); 
}

void RgbLed::blue()  { 
  setColor(0, 0, 255); 
}