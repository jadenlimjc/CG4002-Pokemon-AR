#ifndef GESTURE_CNN_H
#define GESTURE_CNN_H

#include <hls_stream.h>
#include <ap_axi_sdata.h>
#include <ap_fixed.h>

// =================================================================================
// Fixed-point data types for HLS. These are now the single source of truth.
// =================================================================================
using data_t   = ap_fixed<16, 6>;  // Input, weights, and feature maps
using accum_t  = ap_fixed<24, 12>; // Accumulator for convolutions and linear layers
using result_t = ap_fixed<16, 6>;  // Final output logits
using axis_t = ap_axis<32, 0, 0, 0>; // 32-bit floating-point AXI-Stream packet

constexpr int IN_CHANNELS = 6;
constexpr int IN_LENGTH = 128;
constexpr int TOTAL_INPUT_SIZE = IN_CHANNELS * IN_LENGTH; // 768 floats
constexpr int NUM_CLASSES = 7;

void gesture_cnn_top(hls::stream<axis_t>& in_stream, hls::stream<axis_t>& out_stream);

#endif // GESTURE_CNN_H
