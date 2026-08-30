#ifndef GESTURE_CNN_H
#define GESTURE_CNN_H

#include <hls_stream.h>
#include <ap_axi_sdata.h>

typedef float data_t;
typedef ap_axis<32, 0, 0, 0> axis_t; // 32-bit floating-point AXI-Stream packet

#define IN_CHANNELS 6
#define IN_LENGTH 128
#define TOTAL_INPUT_SIZE (IN_CHANNELS * IN_LENGTH) // 768 floats
#define NUM_CLASSES 7

void gesture_cnn_top(hls::stream<axis_t>& in_stream, hls::stream<axis_t>& out_stream);

#endif // GESTURE_CNN_H
