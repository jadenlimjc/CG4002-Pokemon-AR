#include <iostream>
#include <fstream>
#include <cmath>
#include "gesture_cnn.h"

int main() {
    hls::stream<axis_t> in_stream("in_stream");
    hls::stream<axis_t> out_stream("out_stream");

    // Load golden input
    std::ifstream in_file("golden_input.dat");
    if (!in_file.is_open()) {
        std::cerr << "Error: Cannot open golden_input.dat" << std::endl;
        return 1;
    }

    for (int i = 0; i < TOTAL_INPUT_SIZE; ++i) {
        float val;
        in_file >> val;
        axis_t packet;
        union { float f; unsigned int i; } u;
        u.f = val;
        packet.data = u.i;
        packet.last = (i == TOTAL_INPUT_SIZE - 1) ? 1 : 0;
        in_stream.write(packet);
    }
    in_file.close();

    // Run Kernel
    gesture_cnn_top(in_stream, out_stream);

    // Load and compare golden output
    std::ifstream out_file("golden_output.dat");
    bool match = true;
    for (int i = 0; i < NUM_CLASSES; ++i) {
        float ref_val;
        out_file >> ref_val;
        axis_t out_packet = out_stream.read();
        union { unsigned int i; float f; } u;
        u.i = out_packet.data.to_uint();
        float out_val = u.f;

        std::cout << "Class " << i << " | Hardware: " << out_val << " | PyTorch Ref: " << ref_val << std::endl;
        if (std::abs(out_val - ref_val) > 1e-3) {
            match = false;
        }
    }
    out_file.close();

    if (match) {
        std::cout << ">>> TEST PASSED: Hardware output matches PyTorch reference! <<<" << std::endl;
        return 0;
    } else {
        std::cerr << ">>> TEST FAILED: Output mismatch detected! <<<" << std::endl;
        return 1;
    }
}
