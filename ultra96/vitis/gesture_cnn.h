#ifndef GESTURE_CNN_H
#define GESTURE_CNN_H

#include <hls_stream.h>
#include <ap_axi_sdata.h> // For ap_axis
#include <hls_math.h>      // For hls::sqrt
#include <ap_fixed.h>

// =================================================================================
// Round to nearest, ties to even, and saturate at every narrowing boundary.
// data_t: [-32, 32 - 2^-12]; result_t: [-2048, 2048 - 2^-12].
// A data_t product has 24 fractional bits. Preserve all of them in MACs.
// With at most 192 products, |sum| <= 192 * 32 * 32 + 32 = 196640;
// 28 integer bits (including sign) also leave headroom for BN coefficients.
// Keep operand multipliers at 18 bits rather than multiplying widened MACs.
using data_t = ap_fixed<18, 6, AP_RND_CONV, AP_SAT>;
using accum_t  = ap_fixed<52, 28, AP_RND_CONV, AP_SAT>;
using result_t = ap_fixed<24, 12, AP_RND_CONV, AP_SAT>;

// HLS math overloads accept default-mode ap_fixed arguments. The conversion
// preserves every bit because width and binary point match accum_t. Variance
// is positive and its square root fits this format, so no wrapping occurs.
inline accum_t sqrt_variance(const accum_t& variance) {
    using sqrt_arg_t = ap_fixed<accum_t::width, accum_t::iwidth>;
    return accum_t(hls::sqrt(sqrt_arg_t(variance)));
}

// NaN maps to zero; infinities and finite outliers clip to the input range.
// Check before conversion because ap_fixed conversion of NaN/Inf is undefined.
inline data_t quantize_input(float value) {
    if (value != value) return data_t(0);
    if (value >= 32.0f) return data_t(32); // AP_SAT selects the maximum representable value.
    if (value <= -32.0f) return data_t(-32);
    return data_t(value);
}

using axis_t = ap_axis<32, 0, 0, 0>; // 32-bit floating-point AXI-Stream packet

constexpr int IN_CHANNELS = 6;
constexpr int IN_LENGTH = 256;
constexpr int BLOCK1_LENGTH = IN_LENGTH / 2;
constexpr int BLOCK2_LENGTH = BLOCK1_LENGTH / 2;
constexpr int TOTAL_INPUT_SIZE = IN_CHANNELS * IN_LENGTH; // 1536 floats
// Labels 0-9 retain their original order; Uppercut is label 10.
constexpr int NUM_CLASSES = 11;

void gesture_cnn_top(hls::stream<axis_t>& in_stream, hls::stream<axis_t>& out_stream);

// =================================================================================
// LAYER IMPLEMENTATIONS (TEMPLATES)
// These must be in the header file for the testbench to compile.
// =================================================================================

// 1D Convolution with Padding + BatchNorm + ReLU
template<int IN_CH, int OUT_CH, int IN_LEN, int K_SIZE, int PAD>
void conv_bn_relu(
    hls::stream<data_t>& in_stream,
    hls::stream<data_t>& out_stream,
    const data_t (&weight)[OUT_CH * IN_CH * K_SIZE],
    const data_t* bias,
    const accum_t (&bn_scale)[OUT_CH],
    const accum_t (&bn_shift)[OUT_CH]
) {
    // Line buffer to implement a sliding window of size K_SIZE
    data_t line_buf[IN_CH][K_SIZE];
    // Supply every tap in a convolution window in parallel. The flattened
    // weights are laid out [..., K_SIZE], so cyclic banks map one tap to each
    // bank and match the fully-unrolled kernel loop below.
    #pragma HLS ARRAY_PARTITION variable=line_buf complete dim=2
    #pragma HLS ARRAY_PARTITION variable=weight cyclic factor=K_SIZE dim=1

    // The stream is time-major: all channels for timestep 0, then timestep 1,
    // and so on.  Seed the line buffer with zeros for the left padding.
    for (int ic = 0; ic < IN_CH; ++ic) {
        for (int k = 0; k < K_SIZE; ++k) {
            line_buf[ic][k] = data_t(0);
        }
    }

    // Scale and shift are precomputed offline with the same HLS arithmetic.

    // Main convolution loop
    for (int l = 0; l < IN_LEN + PAD; ++l) {
        // 1. Shift the line buffer
        for (int ic = 0; ic < IN_CH; ++ic) {
            for (int k = 0; k < K_SIZE - 1; ++k) {
                line_buf[ic][k] = line_buf[ic][k + 1];
            }
        }

        // 2. Read a complete timestep, or insert explicit right padding.
        for (int ic = 0; ic < IN_CH; ++ic) {
            line_buf[ic][K_SIZE - 1] =
                (l < IN_LEN) ? in_stream.read() : data_t(0);
        }

        // 3. Perform convolution, batchnorm, and ReLU if the window is valid
        if (l >= PAD) {
            for (int oc = 0; oc < OUT_CH; ++oc) {
                accum_t tap_acc[K_SIZE];
                #pragma HLS ARRAY_PARTITION variable=tap_acc complete dim=1

                for (int k = 0; k < K_SIZE; ++k) {
                    #pragma HLS UNROLL
                    tap_acc[k] = accum_t(0);
                }

                for (int ic = 0; ic < IN_CH; ++ic) {
                    // Each tap has an independent recurrence, allowing the
                    // input-channel loop to start a new iteration each cycle.
                    #pragma HLS PIPELINE II=1
                    for (int k = 0; k < K_SIZE; ++k) {
                        #pragma HLS UNROLL
                        int w_idx = (oc * IN_CH * K_SIZE) + (ic * K_SIZE) + k;
                        tap_acc[k] += line_buf[ic][k] * weight[w_idx];
                    }
                }

                accum_t acc = accum_t(bias[oc]);
                for (int k = 0; k < K_SIZE; ++k) {
                    #pragma HLS UNROLL
                    acc += tap_acc[k];
                }
                // Fused BatchNorm + ReLU: y = max(0, acc * scale + shift).
                // Preserve the full expression range through ReLU, then saturate.
                const auto bn_out = acc * bn_scale[oc] + bn_shift[oc];
                out_stream.write((bn_out > 0) ? data_t(bn_out) : data_t(0));
            }
        }
    }
}

// MaxPool keeps the larger of each pair, halving temporal length.
template<int CH, int IN_LEN, int OUT_LEN>
void max_pool2(hls::stream<data_t>& in_stream, hls::stream<data_t>& out_stream) {
    data_t first_timestep[CH];

    for (int l = 0; l < OUT_LEN; ++l) {
        // Each convolution timestep contains one value for every channel.
        // Save the first timestep before consuming the second one.
        for (int c = 0; c < CH; ++c) {
            #pragma HLS PIPELINE II=1
            first_timestep[c] = in_stream.read();
        }
        for (int c = 0; c < CH; ++c) {
            #pragma HLS PIPELINE II=1
            data_t second_timestep = in_stream.read();
            out_stream.write((first_timestep[c] > second_timestep)
                ? first_timestep[c] : second_timestep);
        }
    }
}

// Number of guard bits required to sum N fixed-point values exactly.
constexpr int pool_guard_bits(int n) {
    return n <= 1 ? 0 : 1 + pool_guard_bits((n + 1) / 2);
}

// Global average pooling reduces each channel to one feature.
template<int CH, int IN_LEN>
void adaptive_avg_pool(hls::stream<data_t>& in_stream, data_t out_vec[CH]) {
    static_assert(CH > 0 && IN_LEN > 0, "Pooling dimensions must be positive");
    // Preserve the input's fractional bits and add ceil(log2(IN_LEN))
    // integer guard bits. For 64 timesteps this is a 24-bit exact sum.
    // No rounding or saturation is needed during summation: even IN_LEN
    // copies of either data_t endpoint fit. Saturate only the final output.
    constexpr int GUARD = pool_guard_bits(IN_LEN);
    using pool_sum_t = ap_fixed<data_t::width + GUARD, data_t::iwidth + GUARD>;
    pool_sum_t sums[CH];
    #pragma HLS BIND_STORAGE variable=sums type=ram_t2p impl=bram

    for (int c = 0; c < CH; ++c) {
        sums[c] = pool_sum_t(0);
    }

    // Consume the same time-major layout produced by conv_bn_relu.
    for (int l = 0; l < IN_LEN; ++l) {
        for (int c = 0; c < CH; ++c) {
            #pragma HLS PIPELINE II=1
            sums[c] += pool_sum_t(in_stream.read());
        }
    }

    for (int c = 0; c < CH; ++c) {
        // Widen before division to match the reference quotient precision.
        // Dividing pool_sum_t directly can discard fractional average bits
        // before data_t gets a chance to round them.
        out_vec[c] = data_t(accum_t(sums[c]) / accum_t(IN_LEN));
    }
}

// Dense layer: one dot product plus bias per output neuron.
template<int IN_F, int OUT_F, typename OUT_T>
void linear_layer(
    const data_t in_vec[IN_F],
    OUT_T out_vec[OUT_F],
    const data_t* weight,
    const data_t* bias,
    bool apply_relu
) {
    for (int o = 0; o < OUT_F; ++o) {
        accum_t acc = accum_t(bias[o]);
        for (int i = 0; i < IN_F; ++i) {
            // Keep the dot product sequential and pipeline individual MACs;
            // pipelining the output loop can fully expand the inner product.
            #pragma HLS PIPELINE II=1
            acc += in_vec[i] * weight[o * IN_F + i];
        }
        if (apply_relu) {
            out_vec[o] = (acc > accum_t(0)) ? OUT_T(acc) : OUT_T(0);
        } else {
            out_vec[o] = OUT_T(acc);
        }
    }
}

#endif // GESTURE_CNN_H
