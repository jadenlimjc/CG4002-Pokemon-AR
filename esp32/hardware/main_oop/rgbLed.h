#ifndef RGB_LED_H
#define RGB_LED_H

#include <Arduino.h>

// =====================================================
// RgbLed: KY-016 common-cathode RGB LED wrapper.
// =====================================================
class RgbLed {
  private:
    int redPin_;
    int greenPin_;
    int bluePin_;
    int freq_;
    int resolution_;
    
  public:
    RgbLed(int redPin, int greenPin, int bluePin, int freq, int resolution);

    bool begin();

    void setColor(uint8_t r, uint8_t g, uint8_t b);
    void off();
    void green();
    void red();
    void blue();


};

#endif // RGB_LED_H