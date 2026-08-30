#include "gesture_cnn.h"
#include "weights.h"
#include <cmath>

// Helper union for 32-bit AXI-Stream data transfer
union conv_pkt {
    float f;
    unsigned int i;
};

// =================================================================================
// 1. LAYER IMPLEMENTATIONS
// =================================================================================

// 1D Convolution with Padding + BatchNorm + ReLU
template<int IN_CH, int OUT_CH, int IN_LEN, int K_SIZE, int PAD>
void conv_bn_relu(
    const data_t in_fm[IN_CH][IN_LEN],
    data_t out_fm[OUT_CH][IN_LEN],
    const data_t* weight,
    const data_t* bias,
    const data_t* bn_w,
    const data_t* bn_b,
    const data_t* bn_mean,
    const data_t* bn_var
) {
    const data_t eps = 1e-5f;

    for (int oc = 0; oc < OUT_CH; ++oc) {
        // Precompute batch norm scaling terms for this output channel
        data_t inv_std = 1.0f / std::sqrt(bn_var[oc] + eps);
        data_t scale = bn_w[oc] * inv_std;
        data_t shift = bn_b[oc] - (bn_mean[oc] * scale);

        for (int l = 0; l < IN_LEN; ++l) {
            #pragma HLS PIPELINE II=1
            data_t acc = bias[oc];

            for (int ic = 0; ic < IN_CH; ++ic) {
                for (int k = 0; k < K_SIZE; ++k) {
                    int in_idx = l + k - PAD;
                    if (in_idx >= 0 && in_idx < IN_LEN) {
                        int w_idx = (oc * IN_CH * K_SIZE) + (ic * K_SIZE) + k;
                        acc += in_fm[ic][in_idx] * weight[w_idx];
                    }
                }
            }

            // BatchNorm application
            data_t bn_out = acc * scale + shift;
            
            // ReLU activation
            out_fm[oc][l] = (bn_out > 0.0f) ? bn_out : 0.0f;
        }
    }
}

// 1D Max Pooling (Kernel=2, Stride=2)
template<int CH, int IN_LEN, int OUT_LEN>
void max_pool2(const data_t in_fm[CH][IN_LEN], data_t out_fm[CH][OUT_LEN]) {
    for (int c = 0; c < CH; ++c) {
        for (int l = 0; l < OUT_LEN; ++l) {
            #pragma HLS PIPELINE II=1
            data_t val1 = in_fm[c][l * 2];
            data_t val2 = in_fm[c][l * 2 + 1];
            out_fm[c][l] = (val1 > val2) ? val1 : val2;
        }
    }
}

// Adaptive Average Pooling 1D (Spatial reduction to length 1)
template<int CH, int IN_LEN>
void adaptive_avg_pool(const data_t in_fm[CH][IN_LEN], data_t out_vec[CH]) {
    for (int c = 0; c < CH; ++c) {
        #pragma HLS PIPELINE II=1
        data_t sum = 0.0f;
        for (int l = 0; l < IN_LEN; ++l) {
            sum += in_fm[c][l];
        }
        out_vec[c] = sum / (data_t)IN_LEN;
    }
}

// Fully Connected (Dense) Layer
template<int IN_F, int OUT_F>
void linear_layer(
    const data_t in_vec[IN_F],
    data_t out_vec[OUT_F],
    const data_t* weight,
    const data_t* bias,
    bool apply_relu
) {
    for (int o = 0; o < OUT_F; ++o) {
        #pragma HLS PIPELINE II=1
        data_t acc = bias[o];
        for (int i = 0; i < IN_F; ++i) {
            acc += in_vec[i] * weight[o * IN_F + i];
        }
        if (apply_relu) {
            out_vec[o] = (acc > 0.0f) ? acc : 0.0f;
        } else {
            out_vec[o] = acc;
        }
    }
}

// =================================================================================
// 2. TOP-LEVEL SYNTHESIZABLE KERNEL
// =================================================================================
void gesture_cnn_top(hls::stream<axis_t>& in_stream, hls::stream<axis_t>& out_stream) {
    #pragma HLS INTERFACE axis port=in_stream
    #pragma HLS INTERFACE axis port=out_stream
    #pragma HLS INTERFACE s_axilite port=return bundle=control

    // Internal intermediate feature maps
    data_t in_buf[6][128];
    data_t b1_conv[32][128];
    data_t b1_pool[32][64];

    data_t b2_conv[64][64];
    data_t b2_pool[64][32];

    data_t b3_conv[128][32];
    data_t pooled_vec[128];

    data_t fc1_out[64];
    data_t final_logits[7];

    // 1. Ingest 768 floats (6 channels * 128 timesteps) from AXI DMA
    for (int c = 0; c < 6; ++c) {
        for (int l = 0; l < 128; ++l) {
            #pragma HLS PIPELINE II=1
            axis_t pkt = in_stream.read();
            conv_pkt u;
            u.i = pkt.data.to_uint();
            in_buf[c][l] = u.f;
        }
    }

    // 2. Block 1: Conv1D (6->32, k=7, pad=3) -> MaxPool(2)
    conv_bn_relu<6, 32, 128, 7, 3>(
        in_buf, b1_conv,
        conv1_weight, conv1_bias,
        bn1_weight, bn1_bias, bn1_running_mean, bn1_running_var
    );
    max_pool2<32, 128, 64>(b1_conv, b1_pool);

    // 3. Block 2: Conv1D (32->64, k=5, pad=2) -> MaxPool(2)
    conv_bn_relu<32, 64, 64, 5, 2>(
        b1_pool, b2_conv,
        conv2_weight, conv2_bias,
        bn2_weight, bn2_bias, bn2_running_mean, bn2_running_var
    );
    max_pool2<64, 64, 32>(b2_conv, b2_pool);

    // 4. Block 3: Conv1D (64->128, k=3, pad=1) -> AdaptiveAvgPool
    conv_bn_relu<64, 128, 32, 3, 1>(
        b2_pool, b3_conv,
        conv3_weight, conv3_bias,
        bn3_weight, bn3_bias, bn3_running_mean, bn3_running_var
    );
    adaptive_avg_pool<128, 32>(b3_conv, pooled_vec);

    // 5. Classifier: FC1 (128 -> 64) -> ReLU -> FC2 (64 -> 7)
    linear_layer<128, 64>(pooled_vec, fc1_out, fc1_weight, fc1_bias, true);
    linear_layer<64, 7>(fc1_out, final_logits, fc2_weight, fc2_bias, false);

    // 6. Send 7 Logits back over AXI DMA
    for (int i = 0; i < 7; ++i) {
        #pragma HLS PIPELINE II=1
        axis_t out_pkt;
        conv_pkt u;
        u.f = final_logits[i];
        out_pkt.data = u.i;
        out_pkt.keep = -1;
        out_pkt.last = (i == 6) ? 1 : 0;
        out_stream.write(out_pkt);
    }
}
