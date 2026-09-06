#include <iostream>
#include <fstream>
#include <cmath>
#include "gesture_cnn.h"
#include "weights.h"

// =================================================================================
// Golden Reference Implementation (using floating-point for precision)
// This function mimics the HLS kernel's logic exactly but uses standard
// C++ types to generate a bit-accurate golden reference for the fixed-point design.
// =================================================================================
void gesture_cnn_ref(
    const data_t in_buf[IN_CHANNELS][IN_LENGTH],
    result_t final_logits[NUM_CLASSES]
) {
    // Internal feature maps for the reference model
    data_t b1_conv[32][IN_LENGTH];
    data_t b1_pool[32][64];
    data_t b2_conv[64][64];
    data_t b2_pool[64][32];
    data_t b3_conv[128][32];
    data_t pooled_vec[128];
    data_t fc1_out[64];

    // --- Block 1 ---
    const accum_t eps1 = accum_t(1e-5);
    for (int oc = 0; oc < 32; ++oc) {
        accum_t inv_std1 = accum_t(1.0) / accum_t(sqrt(bn1_running_var[oc].to_float() + eps1.to_float()));
        accum_t scale1 = accum_t(bn1_weight[oc]) * inv_std1;
        accum_t shift1 = accum_t(bn1_bias[oc]) - accum_t(bn1_running_mean[oc]) * scale1;
        for (int l = 0; l < 128; ++l) {
            accum_t acc = accum_t(conv1_bias[oc]);
            for (int ic = 0; ic < 6; ++ic) {
                for (int k = 0; k < 7; ++k) {
                    int in_idx = l + k - 3;
                    if (in_idx >= 0 && in_idx < 128) {
                        acc += accum_t(in_buf[ic][in_idx]) * accum_t(conv1_weight[oc*6*7 + ic*7 + k]);
                    }
                }
            }
            accum_t bn_out = acc * scale1 + shift1;
            b1_conv[oc][l] = (bn_out > 0) ? data_t(bn_out) : data_t(0);
        }
    }
    for (int c = 0; c < 32; ++c) for (int l = 0; l < 64; ++l) b1_pool[c][l] = (b1_conv[c][l*2] > b1_conv[c][l*2+1]) ? b1_conv[c][l*2] : b1_conv[c][l*2+1];

    // --- Block 2 ---
    const accum_t eps2 = accum_t(1e-5);
    for (int oc = 0; oc < 64; ++oc) {
        accum_t inv_std2 = accum_t(1.0) / accum_t(sqrt(bn2_running_var[oc].to_float() + eps2.to_float()));
        accum_t scale2 = accum_t(bn2_weight[oc]) * inv_std2;
        accum_t shift2 = accum_t(bn2_bias[oc]) - accum_t(bn2_running_mean[oc]) * scale2;
        for (int l = 0; l < 64; ++l) {
            accum_t acc = accum_t(conv2_bias[oc]);
            for (int ic = 0; ic < 32; ++ic) {
                for (int k = 0; k < 5; ++k) {
                    int in_idx = l + k - 2;
                    if (in_idx >= 0 && in_idx < 64) {
                        acc += accum_t(b1_pool[ic][in_idx]) * accum_t(conv2_weight[oc*32*5 + ic*5 + k]);
                    }
                }
            }
            accum_t bn_out = acc * scale2 + shift2;
            b2_conv[oc][l] = (bn_out > 0) ? data_t(bn_out) : data_t(0);
        }
    }
    for (int c = 0; c < 64; ++c) for (int l = 0; l < 32; ++l) b2_pool[c][l] = (b2_conv[c][l*2] > b2_conv[c][l*2+1]) ? b2_conv[c][l*2] : b2_conv[c][l*2+1];

    // --- Block 3 ---
    const accum_t eps3 = accum_t(1e-5);
    for (int oc = 0; oc < 128; ++oc) {
        accum_t inv_std3 = accum_t(1.0) / accum_t(sqrt(bn3_running_var[oc].to_float() + eps3.to_float()));
        accum_t scale3 = accum_t(bn3_weight[oc]) * inv_std3;
        accum_t shift3 = accum_t(bn3_bias[oc]) - accum_t(bn3_running_mean[oc]) * scale3;
        for (int l = 0; l < 32; ++l) {
            accum_t acc = accum_t(conv3_bias[oc]);
            for (int ic = 0; ic < 64; ++ic) {
                for (int k = 0; k < 3; ++k) {
                    int in_idx = l + k - 1;
                    if (in_idx >= 0 && in_idx < 32) {
                        acc += accum_t(b2_pool[ic][in_idx]) * accum_t(conv3_weight[oc*64*3 + ic*3 + k]);
                    }
                }
            }
            accum_t bn_out = acc * scale3 + shift3;
            b3_conv[oc][l] = (bn_out > 0) ? data_t(bn_out) : data_t(0);
        }
    }
    for (int c = 0; c < 128; ++c) {
        accum_t sum = 0;
        for (int l = 0; l < 32; ++l) sum += accum_t(b3_conv[c][l]);
        pooled_vec[c] = data_t(sum / accum_t(32));
    }

    // --- Classifier ---
    for (int o = 0; o < 64; ++o) {
        accum_t acc = accum_t(fc1_bias[o]);
        for (int i = 0; i < 128; ++i) acc += accum_t(pooled_vec[i]) * accum_t(fc1_weight[o*128 + i]);
        fc1_out[o] = (acc > 0) ? data_t(acc) : data_t(0);
    }
    for (int o = 0; o < NUM_CLASSES; ++o) {
        accum_t acc = accum_t(fc2_bias[o]);
        for (int i = 0; i < 64; ++i) acc += accum_t(fc1_out[i]) * accum_t(fc2_weight[o*64 + i]);
        final_logits[o] = result_t(acc);
    }
}


int main() {
    hls::stream<axis_t> in_stream("in_stream");
    hls::stream<axis_t> out_stream("out_stream");

    // Load golden input
    std::ifstream in_file("golden_input.dat");
    if (!in_file.is_open()) {
        std::cerr << "Error: Cannot open golden_input.dat" << std::endl;
        return 1;
    }

    // This buffer will hold the input quantized to the HLS data_t type
    static data_t in_buf_quantized[IN_CHANNELS][IN_LENGTH];

    for (int i = 0; i < TOTAL_INPUT_SIZE; ++i) {
        float val;
        in_file >> val;
        axis_t packet;
        union { float f; unsigned int i; } u;
        u.f = val;

        // Quantize the input for the C++ reference model
        in_buf_quantized[i / IN_LENGTH][i % IN_LENGTH] = data_t(val);

        packet.data = u.i;
        packet.last = (i == TOTAL_INPUT_SIZE - 1) ? 1 : 0;
        in_stream.write(packet);
    }
    in_file.close();

    // Generate the bit-accurate golden reference for the fixed-point model
    result_t ref_logits[NUM_CLASSES];
    gesture_cnn_ref(in_buf_quantized, ref_logits);

    // Run Kernel
    gesture_cnn_top(in_stream, out_stream);

    // Compare HLS kernel output with the generated fixed-point reference
    bool match = true;
    for (int i = 0; i < NUM_CLASSES; ++i) {
        axis_t out_packet = out_stream.read();
        union { unsigned int i; float f; } u;
        u.i = out_packet.data.to_uint();
        result_t hw_val = result_t(u.f); // Convert hardware float output back to fixed-point
        result_t ref_val = ref_logits[i];

        std::cout << "Class " << i << " | Hardware: " << hw_val << " | C++ Ref: " << ref_val << std::endl;
        if (hw_val != ref_val) {
            match = false;
        }
    }

    if (match) {
        std::cout << ">>> TEST PASSED: Hardware output matches the C++ fixed-point reference! <<<" << std::endl;
        return 0;
    } else {
        std::cerr << ">>> TEST FAILED: Output mismatch detected! <<<" << std::endl;
        return 1;
    }
}
