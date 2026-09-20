#include "gesture_cnn.h"
#include "weights.h"

// Helper union for 32-bit AXI-Stream data transfer
union conv_pkt {
    float f;
    unsigned int i;
};

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

    // 1. Ingest 1536 floats (6 channels * 256 timesteps) from AXI DMA
    for (int i = 0; i < IN_CHANNELS * IN_LENGTH; ++i) {
        #pragma HLS PIPELINE II=1
        axis_t pkt = in_stream.read();
        conv_pkt u;
        u.i = pkt.data.to_uint();
        // The external AXI protocol remains IEEE-754 float; quantize here.
        s_in.write(data_t(u.f));
    }

    // 2. Block 1: Conv1D (6->32, k=7, pad=3) -> MaxPool(2)
    conv_bn_relu<IN_CHANNELS, 32, IN_LENGTH, 7, 3>(
        s_in, s_b1_conv,
        conv1_weight, conv1_bias,
        bn1_weight, bn1_bias, bn1_running_mean, bn1_running_var
    );
    max_pool2<32, IN_LENGTH, BLOCK1_LENGTH>(s_b1_conv, s_b1_pool);

    // 3. Block 2: Conv1D (32->64, k=5, pad=2) -> MaxPool(2)
    conv_bn_relu<32, 64, BLOCK1_LENGTH, 5, 2>(
        s_b1_pool, s_b2_conv,
        conv2_weight, conv2_bias,
        bn2_weight, bn2_bias, bn2_running_mean, bn2_running_var
    );
    max_pool2<64, BLOCK1_LENGTH, BLOCK2_LENGTH>(s_b2_conv, s_b2_pool);

    // 4. Block 3: Conv1D (64->128, k=3, pad=1) -> AdaptiveAvgPool
    conv_bn_relu<64, 128, BLOCK2_LENGTH, 3, 1>(
        s_b2_pool, s_b3_conv,
        conv3_weight, conv3_bias,
        bn3_weight, bn3_bias, bn3_running_mean, bn3_running_var
    );
    adaptive_avg_pool<128, BLOCK2_LENGTH>(s_b3_conv, pooled_vec);

    // 5. Classifier: FC1 (128 -> 64) -> ReLU -> FC2 (64 -> 7)
    linear_layer<128, 64, data_t>(pooled_vec, fc1_out, fc1_weight, fc1_bias, true);
    linear_layer<64, NUM_CLASSES, result_t>(
        fc1_out, final_logits, fc2_weight, fc2_bias, false
    );

    // 6. Send 7 Logits back over AXI DMA
    for (int i = 0; i < NUM_CLASSES; ++i) {
        #pragma HLS PIPELINE II=1
        axis_t out_pkt;
        conv_pkt u;
        // Convert the fixed-point result back to the existing float protocol.
        u.f = final_logits[i].to_float();
        out_pkt.data = u.i;
        out_pkt.keep = -1;
        out_pkt.last = (i == NUM_CLASSES - 1) ? 1 : 0;
        out_stream.write(out_pkt);
    }
}
