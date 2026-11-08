#include <iostream>
#include <fstream>
#include <string>
#include <cmath>
#include <limits>
#include <cstdlib>
#include "gesture_cnn.h"
#include "weights.h"

static_assert(sizeof(fc2_weight) / sizeof(fc2_weight[0]) == 64 * NUM_CLASSES,
              "Classifier weights are stale: retrain and export all eleven classes");
static_assert(sizeof(fc2_bias) / sizeof(fc2_bias[0]) == NUM_CLASSES,
              "Classifier biases are stale: retrain and export all eleven classes");

// =================================================================================
// Bit-accurate golden reference.  Keep the same fixed-point types and
// expression ordering as the synthesizable implementation.
// =================================================================================
void gesture_cnn_ref(
    const data_t in_buf[IN_CHANNELS][IN_LENGTH],
    result_t final_logits[NUM_CLASSES]
) {
    // Use standard arrays for the reference implementation
    data_t b1_conv[32][IN_LENGTH];
    data_t b1_pool[32][BLOCK1_LENGTH];
    data_t b2_conv[64][BLOCK1_LENGTH];
    data_t b2_pool[64][BLOCK2_LENGTH];
    data_t b3_conv[128][BLOCK2_LENGTH];
    data_t pooled_vec[FC1_INPUT_SIZE];
    data_t fc1_out[64];

    // --- Block 1 ---
    const accum_t eps1 = accum_t(1e-5);
    for (int oc = 0; oc < 32; ++oc) {
        accum_t variance1 = accum_t(bn1_running_var[oc]) + eps1;
        if (variance1 < eps1) variance1 = eps1;
        accum_t inv_std1 = accum_t(1) / sqrt_variance(variance1);
        accum_t scale1 = accum_t(bn1_weight[oc]) * inv_std1;
        accum_t shift1 = accum_t(bn1_bias[oc]) -
            (accum_t(bn1_running_mean[oc]) * scale1);
        // Independently check exported coefficients against the old runtime math.
        if (scale1 != bn1_scale[oc] || shift1 != bn1_shift[oc]) {
            std::cerr << "BN1 coefficient mismatch at channel " << oc << std::endl;
            std::exit(1);
        }
        for (int l = 0; l < IN_LENGTH; ++l) {
            accum_t acc = accum_t(conv1_bias[oc]);
            for (int ic = 0; ic < 6; ++ic) {
                for (int k = 0; k < CONV1_KERNEL; ++k) {
                    int in_idx = l + k * CONV1_DILATION - CONV1_PAD;
                    if (in_idx >= 0 && in_idx < IN_LENGTH) {
                        acc += in_buf[ic][in_idx] * conv1_weight[(oc*6 + ic)*CONV1_KERNEL + k];
                    }
                }
            }
            const auto bn_out = acc * scale1 + shift1;
            b1_conv[oc][l] = (bn_out > 0) ? data_t(bn_out) : data_t(0);
        }
    }
    for (int c = 0; c < 32; ++c) for (int l = 0; l < BLOCK1_LENGTH; ++l) b1_pool[c][l] = (b1_conv[c][l*2] > b1_conv[c][l*2+1]) ? b1_conv[c][l*2] : b1_conv[c][l*2+1];

    // --- Block 2 ---
    const accum_t eps2 = accum_t(1e-5);
    for (int oc = 0; oc < 64; ++oc) {
        accum_t variance2 = accum_t(bn2_running_var[oc]) + eps2;
        if (variance2 < eps2) variance2 = eps2;
        accum_t inv_std2 = accum_t(1) / sqrt_variance(variance2);
        accum_t scale2 = accum_t(bn2_weight[oc]) * inv_std2;
        accum_t shift2 = accum_t(bn2_bias[oc]) -
            (accum_t(bn2_running_mean[oc]) * scale2);
        // Independently check exported coefficients against the old runtime math.
        if (scale2 != bn2_scale[oc] || shift2 != bn2_shift[oc]) {
            std::cerr << "BN2 coefficient mismatch at channel " << oc << std::endl;
            std::exit(1);
        }
        for (int l = 0; l < BLOCK1_LENGTH; ++l) {
            accum_t acc = accum_t(conv2_bias[oc]);
            for (int ic = 0; ic < 32; ++ic) {
                for (int k = 0; k < CONV2_KERNEL; ++k) {
                    int in_idx = l + k * CONV2_DILATION - CONV2_PAD;
                    if (in_idx >= 0 && in_idx < BLOCK1_LENGTH) {
                        acc += b1_pool[ic][in_idx] * conv2_weight[(oc*32 + ic)*CONV2_KERNEL + k];
                    }
                }
            }
            const auto bn_out = acc * scale2 + shift2;
            b2_conv[oc][l] = (bn_out > 0) ? data_t(bn_out) : data_t(0);
        }
    }
    for (int c = 0; c < 64; ++c) for (int l = 0; l < BLOCK2_LENGTH; ++l) b2_pool[c][l] = (b2_conv[c][l*2] > b2_conv[c][l*2+1]) ? b2_conv[c][l*2] : b2_conv[c][l*2+1];

    // --- Block 3 ---
    const accum_t eps3 = accum_t(1e-5);
    for (int oc = 0; oc < 128; ++oc) {
        accum_t variance3 = accum_t(bn3_running_var[oc]) + eps3;
        if (variance3 < eps3) variance3 = eps3;
        accum_t inv_std3 = accum_t(1) / sqrt_variance(variance3);
        accum_t scale3 = accum_t(bn3_weight[oc]) * inv_std3;
        accum_t shift3 = accum_t(bn3_bias[oc]) -
            (accum_t(bn3_running_mean[oc]) * scale3);
        // Independently check exported coefficients against the old runtime math.
        if (scale3 != bn3_scale[oc] || shift3 != bn3_shift[oc]) {
            std::cerr << "BN3 coefficient mismatch at channel " << oc << std::endl;
            std::exit(1);
        }
        for (int l = 0; l < BLOCK2_LENGTH; ++l) {
            accum_t acc = accum_t(conv3_bias[oc]);
            for (int ic = 0; ic < 64; ++ic) {
                for (int k = 0; k < CONV3_KERNEL; ++k) {
                    int in_idx = l + k * CONV3_DILATION - CONV3_PAD;
                    if (in_idx >= 0 && in_idx < BLOCK2_LENGTH) {
                        acc += b2_pool[ic][in_idx] * conv3_weight[(oc*64 + ic)*CONV3_KERNEL + k];
                    }
                }
            }
            const auto bn_out = acc * scale3 + shift3;
            b3_conv[oc][l] = (bn_out > 0) ? data_t(bn_out) : data_t(0);
        }
    }
    for (int c = 0; c < 128; ++c) {
        for (int b = 0; b < TEMPORAL_BINS; ++b) {
            const int start = b * BLOCK2_LENGTH / TEMPORAL_BINS;
            const int end = ((b + 1) * BLOCK2_LENGTH + TEMPORAL_BINS - 1) / TEMPORAL_BINS;
            accum_t sum = accum_t(0);
            for (int l = start; l < end; ++l) sum += accum_t(b3_conv[c][l]);
            pooled_vec[c * TEMPORAL_BINS + b] = data_t(sum / accum_t(end - start));
        }
    }

    // --- Classifier ---
    for (int o = 0; o < 64; ++o) {
        accum_t acc = accum_t(fc1_bias[o]);
        for (int i = 0; i < FC1_INPUT_SIZE; ++i) acc += pooled_vec[i] * fc1_weight[o*FC1_INPUT_SIZE + i];
        fc1_out[o] = (acc > 0) ? data_t(acc) : data_t(0);
    }
    for (int o = 0; o < NUM_CLASSES; ++o) {
        accum_t acc = accum_t(fc2_bias[o]);
        for (int i = 0; i < 64; ++i) acc += fc1_out[i] * fc2_weight[o*64 + i];
        final_logits[o] = result_t(acc);
    }
}


// Exercise numeric boundaries independently of the golden inference fixture.
bool test_quantization_boundaries() {
    const double lsb = std::ldexp(1.0, data_t::iwidth - data_t::width);
    bool ok = true;
    ok &= data_t(1000).to_double() == 32.0 - lsb;
    ok &= data_t(-1000).to_double() == -32.0;
    ok &= data_t(0.5 * lsb).to_double() == 0.0;
    ok &= data_t(1.5 * lsb).to_double() == 2.0 * lsb;
    ok &= data_t(-1.5 * lsb).to_double() == -2.0 * lsb;
    ok &= quantize_input(std::numeric_limits<float>::infinity()).to_double() == 32.0 - lsb;
    ok &= quantize_input(-std::numeric_limits<float>::infinity()).to_double() == -32.0;
    ok &= quantize_input(std::numeric_limits<float>::quiet_NaN()).to_double() == 0.0;

    // Worst-case dot product must remain exact and allow later cancellation.
    accum_t sum = 0;
    for (int i = 0; i < FC1_INPUT_SIZE; ++i) sum += data_t(-32) * data_t(-32);
    ok &= sum.to_double() == FC1_INPUT_SIZE * 1024.0;
    for (int i = 0; i < FC1_INPUT_SIZE; ++i) sum -= data_t(-32) * data_t(-32);
    ok &= sum.to_double() == 0.0;
    ok &= result_t(1000000).to_double() == 2048.0 - 1.0 / 4096.0;
    ok &= result_t(-1000000).to_double() == -2048.0;

    // Pooling a full-scale channel must not wrap during summation.
    hls::stream<data_t> pool_input;
    data_t pooled[1];
    for (int i = 0; i < BLOCK2_LENGTH; ++i) pool_input.write(data_t(1000));
    adaptive_avg_pool<1, BLOCK2_LENGTH>(pool_input, pooled);
    ok &= pooled[0].to_double() == 32.0 - lsb;

    // A fraction just over half of one input LSB must round up; narrow division can
    // truncate this to zero before the final convergent rounding.
    for (int i = 0; i < BLOCK2_LENGTH; ++i)
        pool_input.write(i < BLOCK2_LENGTH / 2 + 1 ? data_t(lsb) : data_t(0));
    adaptive_avg_pool<1, BLOCK2_LENGTH>(pool_input, pooled);
    ok &= pooled[0].to_double() == lsb;
    for (int i = 0; i < BLOCK2_LENGTH; ++i)
        pool_input.write(i < BLOCK2_LENGTH / 2 + 1 ? data_t(-lsb) : data_t(0));
    adaptive_avg_pool<1, BLOCK2_LENGTH>(pool_input, pooled);
    ok &= pooled[0].to_double() == -lsb;

    // Dense output saturates after the entire dot product, preserving sign.
    const data_t inputs[2] = {data_t(-32), data_t(-32)};
    const data_t weights[4] = {data_t(-32), data_t(-32), data_t(31), data_t(31)};
    const data_t biases[2] = {data_t(0), data_t(0)};
    data_t outputs[2];
    linear_layer<2, 2, data_t>(inputs, outputs, weights, biases, true);
    ok &= outputs[0].to_double() == 32.0 - lsb;
    ok &= outputs[1].to_double() == 0.0;
    if (!ok) std::cerr << "Quantization boundary tests failed" << std::endl;
    return ok;
}


// Independent direct-index reference catches tap spacing, padding and stream order.
template<int K, int D, int L>
bool test_dilated_convolution() {
    const int PAD = D * (K - 1) / 2;
    data_t input[2][L];
    data_t weight[2 * 2 * K];
    const data_t bias[2] = {data_t(0.125), data_t(-0.25)};
    const accum_t scale[2] = {accum_t(1), accum_t(0.5)};
    const accum_t shift[2] = {accum_t(0.25), accum_t(-0.125)};
    for (int i = 0; i < 4 * K; ++i) weight[i] = data_t((i % 7 - 3) * 0.125);
    hls::stream<data_t> in, out;
    for (int l = 0; l < L; ++l) {
        for (int c = 0; c < 2; ++c) {
            input[c][l] = data_t(((l * 3 + c * 7) % 17 - 8) * 0.125);
            in.write(input[c][l]);
        }
    }
    conv_bn_relu<2, 2, L, K, PAD, D>(in, out, weight, bias, scale, shift);
    for (int l = 0; l < L; ++l) {
        for (int oc = 0; oc < 2; ++oc) {
            accum_t acc = accum_t(bias[oc]);
            for (int ic = 0; ic < 2; ++ic) {
                for (int k = 0; k < K; ++k) {
                    const int t = l + k * D - PAD;
                    if (t >= 0 && t < L) acc += input[ic][t] * weight[(oc * 2 + ic) * K + k];
                }
            }
            const auto value = acc * scale[oc] + shift[oc];
            const data_t expected = value > 0 ? data_t(value) : data_t(0);
            if (out.empty() || out.read() != expected) return false;
        }
    }
    return in.empty() && out.empty();
}

template<int L, int BINS>
bool test_ordered_pooling() {
    hls::stream<data_t> in;
    data_t pooled[2 * BINS];
    for (int t = 0; t < L; ++t)
        for (int c = 0; c < 2; ++c) in.write(data_t((c * L + t) * 0.25));
    adaptive_avg_pool<2, L, BINS>(in, pooled);
    for (int c = 0; c < 2; ++c) {
        for (int b = 0; b < BINS; ++b) {
            const int start = b * L / BINS;
            const int end = ((b + 1) * L + BINS - 1) / BINS;
            accum_t sum = 0;
            for (int t = start; t < end; ++t) sum += data_t((c * L + t) * 0.25);
            if (pooled[c * BINS + b] != data_t(sum / accum_t(end - start))) return false;
        }
    }
    return in.empty();
}

bool test_temporal_layers() {
    const bool ok = test_dilated_convolution<7, 1, 16>()
        && test_dilated_convolution<5, 2, 16>()
        && test_dilated_convolution<7, 4, 32>()
        && test_dilated_convolution<7, 4, 8>() // Padding span exceeds input length.
        && test_ordered_pooling<32, 4>()
        && test_ordered_pooling<10, 4>() // Uneven, overlapping adaptive bins.
        && test_ordered_pooling<4, 4>();
    if (!ok) std::cerr << "Temporal layer tests failed" << std::endl;
    return ok;
}

int main(int argc, char** argv) {
    std::cout << "Configuration: " << EXPORTED_SAMPLE_RATE_HZ << " Hz | "
              << IN_LENGTH << "-sample window ("
              << double(IN_LENGTH) / EXPORTED_SAMPLE_RATE_HZ << " s) | "
              << TOTAL_INPUT_SIZE << " input floats" << std::endl;
    if (!test_quantization_boundaries()) return 1;
    if (!test_temporal_layers()) return 1;
    hls::stream<axis_t> in_stream("in_stream");
    hls::stream<axis_t> out_stream("out_stream");

    // Load golden input
    std::ifstream in_file(argc > 1 ? argv[1] : "golden_input.dat");
    if (!in_file.is_open()) {
        std::cerr << "Error: Cannot open golden_input.dat" << std::endl;
        return 1;
    }

    // This buffer will hold the input quantized to the HLS data_t type
    static data_t in_buf_quantized[IN_CHANNELS][IN_LENGTH];

    // golden_input.dat is flattened from a PyTorch [C, L] tensor, so load it
    // channel-major first.  The hardware stream itself is time-major because
    // conv_bn_relu consumes all channels for each timestep.
    for (int i = 0; i < TOTAL_INPUT_SIZE; ++i) {
        float val;
        if (!(in_file >> val)) {
            std::cerr << "Error: golden_input.dat contains fewer than "
                      << TOTAL_INPUT_SIZE << " values" << std::endl;
            return 1;
        }

        // Quantize the input for the C++ reference model
        in_buf_quantized[i / IN_LENGTH][i % IN_LENGTH] = quantize_input(val);
    }
    std::string extra;
    if (in_file >> extra) {
        std::cerr << "Error: golden_input.dat contains more than "
                  << TOTAL_INPUT_SIZE << " values; re-export for this window size" << std::endl;
        return 1;
    }
    in_file.close();

    for (int l = 0; l < IN_LENGTH; ++l) {
        for (int c = 0; c < IN_CHANNELS; ++c) {
            const int stream_idx = l * IN_CHANNELS + c;
            axis_t packet;
            union { float f; unsigned int i; } u;
            u.f = in_buf_quantized[c][l].to_float();
            packet.data = u.i;
            packet.keep = -1;
            packet.strb = -1;
            packet.last = (stream_idx == TOTAL_INPUT_SIZE - 1) ? 1 : 0;
            in_stream.write(packet);
        }
    }

    // Generate the bit-accurate golden reference for the fixed-point model
    // This now calls the pure C++ reference function.
    result_t ref_logits[NUM_CLASSES];
    gesture_cnn_ref(in_buf_quantized, ref_logits);

    // Run Kernel
    unsigned int model_id = 0;
    gesture_cnn_top(in_stream, out_stream, model_id);
    if (model_id != MODEL_ID) {
        std::cerr << "Incorrect hardware model identity" << std::endl;
        return 1;
    }

    // Compare HLS kernel output with the generated fixed-point reference
    bool match = true;
    std::ofstream logit_file;
    if (argc > 2) {
        logit_file.open(argv[2]);
        if (!logit_file) return 1;
        logit_file.precision(12);
    }
    for (int i = 0; i < NUM_CLASSES; ++i) {
        axis_t out_packet = out_stream.read();
        union { unsigned int i; float f; } u;
        u.i = out_packet.data.to_uint();
        result_t hw_val = result_t(u.f); // Convert hardware float output back to fixed-point
        result_t ref_val = ref_logits[i];
        if (logit_file) logit_file << hw_val.to_double() << '\n';

        // Calculate the difference. For ap_fixed, it's best to convert to a
        // common floating-point type for comparison.
        float diff = std::abs(hw_val.to_float() - ref_val.to_float());
        // Define a small tolerance. The smallest representable value for our
        // fixed-point type is a good choice.
        const float tolerance = 0.0f; // Exact: 24-bit result fits IEEE-754 float

        std::cout << "Class " << i << " | Hardware: " << hw_val << " | C++ Ref: " << ref_val << std::endl;
        if (out_packet.last != (i == NUM_CLASSES - 1) || out_packet.keep != 15 || out_packet.strb != 15) {
            std::cerr << "Invalid AXI output framing at class " << i << std::endl;
            match = false;
        }
        if (diff > tolerance) {
            match = false;
        }
    }

    if (!in_stream.empty() || !out_stream.empty()) {
        std::cerr << "Unexpected leftover AXI packets" << std::endl;
        match = false;
    }
    if (match) {
        std::cout << ">>> TEST PASSED: Hardware output matches the C++ fixed-point reference! <<<" << std::endl;
        return 0;
    } else {
        std::cerr << ">>> TEST FAILED: Output mismatch detected! <<<" << std::endl;
        return 1;
    }
}
