#pragma once
#include <Print.h>

// Fans out every write to two Print destinations at once
// (e.g. Serial + WebSerial), so existing code that calls
// dbg.print(...) / dbg.println(...) reaches both.
class DualPrint : public Print {
public:
  DualPrint(Print& a, Print& b) : outA(a), outB(b) {}

  size_t write(uint8_t c) override {
    outA.write(c);
    outB.write(c);
    return 1;
  }

  size_t write(const uint8_t* buffer, size_t size) override {
    outA.write(buffer, size);
    outB.write(buffer, size);
    return size;
  }

private:
  Print& outA;
  Print& outB;
};

extern DualPrint dbg;