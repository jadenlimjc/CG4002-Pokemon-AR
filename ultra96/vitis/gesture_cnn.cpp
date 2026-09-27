#include "gesture_cnn.h"
#include "weights.h"

// Helper union for 32-bit AXI-Stream data transfer
union conv_pkt {
    float f;
    unsigned int i;
};

static void read_input(
    hls::stream<axis_t>& in_stream,
    hls::stream<data_t>& out_stream
) {
    #pragma HLS INLINE off
    for (int i = 0; i < TOTAL_INPUT_SIZE; ++i) {
        #pragma HLS PIPELINE II=1
        axis_t pkt = in_stream.read();
        conv_pkt u;
        u.i = pkt.data.to_uint();
        // The external AXI protocol remains IEEE-754 float; quantize here.
        out_stream.write(data_t(u.f));
    }
}

static void write_output(
    const result_t logits[NUM_CLASSES],
    hls::stream<axis_t>& out_stream
) {
    #pragma HLS INLINE off
    for (int i = 0; i < NUM_CLASSES; ++i) {
        #pragma HLS PIPELINE II=1
        axis_t pkt;
        conv_pkt u;
        u.f = logits[i].to_float();
        pkt.data = u.i;
        pkt.keep = -1;
        pkt.last = (i == NUM_CLASSES - 1) ? 1 : 0;
        out_stream.write(pkt);
    }
}

static void conv1_process(
    hls::stream<data_t>& input,
    hls::stream<data_t>& output
) {
    #pragma HLS INLINE off
    conv_bn_relu<IN_CHANNELS, 32, IN_LENGTH, 7, 3>(
        input, output, conv1_weight, conv1_bias,
        bn1_weight, bn1_bias, bn1_running_mean, bn1_running_var
    );
}

static void conv2_process(
    hls::stream<data_t>& input,
    hls::stream<data_t>& output
) {
    #pragma HLS INLINE off
    conv_bn_relu<32, 64, BLOCK1_LENGTH, 5, 2>(
        input, output, conv2_weight, conv2_bias,
        bn2_weight, bn2_bias, bn2_running_mean, bn2_running_var
    );
}

static void conv3_process(
    hls::stream<data_t>& input,
    hls::stream<data_t>& output
) {
    #pragma HLS INLINE off
    conv_bn_relu<64, 128, BLOCK2_LENGTH, 3, 1>(
        input, output, conv3_weight, conv3_bias,
        bn3_weight, bn3_bias, bn3_running_mean, bn3_running_var
    );
}

static void fc1_process(
    const data_t input[128],
    data_t output[64]
) {
    #pragma HLS INLINE off
    linear_layer<128, 64, data_t>(
        input, output, fc1_weight, fc1_bias, true
    );
}

static void fc2_process(
    const data_t input[64],
    result_t output[NUM_CLASSES]
) {
    #pragma HLS INLINE off
    linear_layer<64, NUM_CLASSES, result_t>(
        input, output, fc2_weight, fc2_bias, false
    );
}

// =================================================================================
// TOP-LEVEL SYNTHESIZABLE KERNEL
// =================================================================================
void gesture_cnn_top(hls::stream<axis_t>& in_stream, hls::stream<axis_t>& out_stream) {
    #pragma HLS INTERFACE axis port=in_stream
    #pragma HLS INTERFACE axis port=out_stream
    #pragma HLS INTERFACE s_axilite port=return bundle=control
    #pragma HLS DATAFLOW

    // Intermediate streams between layers
    hls::stream<data_t> s_in("s_in");
    hls::stream<data_t> s_b1_conv("s_b1_conv");
    hls::stream<data_t> s_b1_pool("s_b1_pool");
    hls::stream<data_t> s_b2_conv("s_b2_conv");
    hls::stream<data_t> s_b2_pool("s_b2_pool");
    hls::stream<data_t> s_b3_conv("s_b3_conv");

    // Buffers for flattened/vector data
    data_t pooled_vec[128];
    data_t fc1_out[64];
    result_t final_logits[NUM_CLASSES];

    #pragma HLS STREAM variable=s_in depth=1536
    #pragma HLS STREAM variable=s_b1_conv depth=512
    #pragma HLS STREAM variable=s_b1_pool depth=512
    #pragma HLS STREAM variable=s_b2_conv depth=256
    #pragma HLS STREAM variable=s_b2_pool depth=256
    #pragma HLS STREAM variable=s_b3_conv depth=128

    // 1. Ingest and quantize the AXI input stream.
    read_input(in_stream, s_in);

    // 2. Block 1: Conv1D (6->32, k=7, pad=3) -> MaxPool(2)
    conv1_process(s_in, s_b1_conv);
    max_pool2<32, IN_LENGTH, BLOCK1_LENGTH>(s_b1_conv, s_b1_pool);

    // 3. Block 2: Conv1D (32->64, k=5, pad=2) -> MaxPool(2)
    conv2_process(s_b1_pool, s_b2_conv);
    max_pool2<64, BLOCK1_LENGTH, BLOCK2_LENGTH>(s_b2_conv, s_b2_pool);

    // 4. Block 3: Conv1D (64->128, k=3, pad=1) -> AdaptiveAvgPool
    conv3_process(s_b2_pool, s_b3_conv);
    adaptive_avg_pool<128, BLOCK2_LENGTH>(s_b3_conv, pooled_vec);

    // 5. Classifier: FC1 (128 -> 64) -> ReLU -> FC2 (64 -> 10)
    fc1_process(pooled_vec, fc1_out);
    fc2_process(fc1_out, final_logits);

    // 6. Convert and send the logits over AXI DMA.
    write_output(final_logits, out_stream);
}
