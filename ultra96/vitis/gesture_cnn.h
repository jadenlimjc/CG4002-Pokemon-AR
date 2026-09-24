#ifndef GESTURE_CNN_H
#define GESTURE_CNN_H

#include <hls_stream.h>
#include <ap_axi_sdata.h> // For ap_axis
#include <hls_math.h>      // For hls::sqrt
#include <ap_fixed.h>

// =================================================================================
// Fixed-point data types for HLS. These are now the single source of truth.
// =================================================================================
using data_t   = ap_fixed<16, 6>;  // Input, weights, and feature maps
using accum_t  = ap_fixed<24, 12>; // Accumulator for convolutions and linear layers
// Logits from the trained model can exceed the data_t range (approximately
// [-32, 32)).  Keep them in the accumulator format to prevent wraparound
// before they are converted back to IEEE-754 floats on AXI-Stream.
using result_t = ap_fixed<24, 12>; // Final output logits
using axis_t = ap_axis<32, 0, 0, 0>; // 32-bit floating-point AXI-Stream packet

constexpr int IN_CHANNELS = 6;
constexpr int IN_LENGTH = 256;
constexpr int BLOCK1_LENGTH = IN_LENGTH / 2;
constexpr int BLOCK2_LENGTH = BLOCK1_LENGTH / 2;
constexpr int TOTAL_INPUT_SIZE = IN_CHANNELS * IN_LENGTH; // 1536 floats
constexpr int NUM_CLASSES = 7;

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
    const data_t* bn_w,
    const data_t* bn_b,
    const data_t* bn_mean,
    const data_t* bn_var
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

    // Buffers to hold pre-computed batchnorm parameters
    accum_t scale_buf[OUT_CH];
    accum_t shift_buf[OUT_CH];

    const accum_t eps = accum_t(1e-5);

    // Pre-compute batchnorm parameters for all output channels
    for (int oc = 0; oc < OUT_CH; ++oc) {
        #pragma HLS PIPELINE
        accum_t variance = accum_t(bn_var[oc]) + eps;
        accum_t stddev = hls::sqrt(variance);
        accum_t inv_std = accum_t(1) / stddev;
        scale_buf[oc] = accum_t(bn_w[oc]) * inv_std;
        shift_buf[oc] = accum_t(bn_b[oc]) - (accum_t(bn_mean[oc]) * accum_t(bn_w[oc]) * inv_std);
    }

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
                        tap_acc[k] += accum_t(line_buf[ic][k]) *
                                      accum_t(weight[w_idx]);
                    }
                }

                accum_t acc = accum_t(bias[oc]);
                for (int k = 0; k < K_SIZE; ++k) {
                    #pragma HLS UNROLL
                    acc += tap_acc[k];
                }
                // Apply BatchNorm and ReLU immediately and stream out
                accum_t bn_out = acc * scale_buf[oc] + shift_buf[oc];
                out_stream.write((bn_out > 0) ? data_t(bn_out) : data_t(0));
            }
        }
    }
}

// 1D Max Pooling (Kernel=2, Stride=2)
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

// Adaptive Average Pooling 1D (Spatial reduction to length 1)
template<int CH, int IN_LEN>
void adaptive_avg_pool(hls::stream<data_t>& in_stream, data_t out_vec[CH]) {
    accum_t sums[CH];

    for (int c = 0; c < CH; ++c) {
        sums[c] = accum_t(0);
    }

    // Consume the same time-major layout produced by conv_bn_relu.
    for (int l = 0; l < IN_LEN; ++l) {
        for (int c = 0; c < CH; ++c) {
            #pragma HLS PIPELINE II=1
            sums[c] += accum_t(in_stream.read());
        }
    }

    for (int c = 0; c < CH; ++c) {
        out_vec[c] = data_t(sums[c] / accum_t(IN_LEN));
    }
}

// Fully Connected (Dense) Layer
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
            acc += accum_t(in_vec[i]) * accum_t(weight[o * IN_F + i]);
        }
        if (apply_relu) {
            out_vec[o] = (acc > accum_t(0)) ? OUT_T(acc) : OUT_T(0);
        } else {
            out_vec[o] = OUT_T(acc);
        }
    }
}

#endif // GESTURE_CNN_H
