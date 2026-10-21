// Host-only export utility: never add this file to the HLS synthesis sources.
// Use the same HLS arithmetic as the old runtime setup, including rounding.
#include <iostream>
#include <iomanip>
#include <vector>
#include <cmath>
#include "../../vitis/gesture_cnn.h"

int main() {
    std::cout << std::fixed << std::setprecision(20);
    for (int block = 1; block <= 3; ++block) {
        int channels;
        if (!(std::cin >> channels) || channels != (16 << block)) return 1;
        std::vector<accum_t> scales(channels), shifts(channels);
        for (int oc = 0; oc < channels; ++oc) {
            double gamma, beta, mean, var;
            if (!(std::cin >> gamma >> beta >> mean >> var) ||
                !std::isfinite(gamma) || !std::isfinite(beta) ||
                !std::isfinite(mean) || !std::isfinite(var)) return 1;
            const accum_t eps = accum_t(1e-5);
            accum_t variance = accum_t(data_t(var)) + eps;
            if (variance < eps) variance = eps;
            accum_t inv_std = accum_t(1) / sqrt_variance(variance);
            scales[oc] = accum_t(data_t(gamma)) * inv_std;
            shifts[oc] = accum_t(data_t(beta)) -
                         accum_t(data_t(mean)) * scales[oc];
        }
        for (int kind = 0; kind < 2; ++kind) {
            std::cout << "const accum_t bn" << block
                      << (kind == 0 ? "_scale" : "_shift")
                      << "[" << channels << "] = {\n    ";
            for (int oc = 0; oc < channels; ++oc) {
                if (oc) std::cout << ", ";
                std::cout << (kind == 0 ? scales[oc] : shifts[oc]).to_double();
            }
            std::cout << "\n};\n\n";
        }
    }
    return 0;
}
