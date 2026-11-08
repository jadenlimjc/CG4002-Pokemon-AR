import torch
import torch.nn as nn

MODEL_PRESETS = {
    "legacy": {},
    "temporal": {"kernel_sizes": (7, 5, 7), "dilations": (1, 2, 4), "temporal_bins": 4},
}

# =====================================================================
# 1D CNN MODEL ARCHITECTURE
# =====================================================================
class Gesture1DCNN(nn.Module):
    """
    1D CNN tailored for IMU-based edge deployment.
    Configurable temporal context and ordered pooling for IMU windows.

    Constructor defaults retain the original architecture so metadata from old
    checkpoints still loads. New training selects MODEL_PRESETS["temporal"].
    The temporal preset requires corresponding FPGA/HLS changes before export.
    """
    def __init__(self, in_channels=6, num_classes=11,
                 channels=(32, 64, 128), kernel_sizes=(7, 5, 3),
                 hidden_features=64, dropout=0.3, dilations=(1, 1, 1), temporal_bins=1):
        super(Gesture1DCNN, self).__init__()
        if len(channels) != 3 or any(type(c) is not int or c < 1 for c in channels):
            raise ValueError("channels must contain three positive integers")
        if (len(kernel_sizes) != 3 or
                any(type(k) is not int or k < 1 or k % 2 == 0 for k in kernel_sizes)):
            raise ValueError("kernel_sizes must contain three positive odd integers")
        if type(hidden_features) is not int or hidden_features < 1:
            raise ValueError("hidden_features must be a positive integer")
        if len(dilations) != 3 or any(type(d) is not int or d < 1 for d in dilations):
            raise ValueError("dilations must contain three positive integers")
        if type(temporal_bins) is not int or temporal_bins < 1:
            raise ValueError("temporal_bins must be a positive integer")
        self.config = {"in_channels": in_channels, "num_classes": num_classes,
                       "channels": list(channels), "kernel_sizes": list(kernel_sizes),
                       "hidden_features": hidden_features, "dropout": dropout,
                       "dilations": list(dilations), "temporal_bins": temporal_bins}
        c1, c2, c3 = channels
        k1, k2, k3 = kernel_sizes
        d1, d2, d3 = dilations
        self.temporal_bins = temporal_bins
        # Context of each feature before temporal averaging, in input samples.
        self.receptive_field_samples = (1 + (k1 - 1) * d1 + 1
                                       + 2 * (k2 - 1) * d2 + 2
                                       + 4 * (k3 - 1) * d3)

        # Block 1 learns short motion patterns; pooling halves the input temporal length.
        self.block1 = nn.Sequential(
            nn.Conv1d(in_channels, c1, kernel_size=k1, stride=1,
                      padding=d1 * (k1 // 2), dilation=d1),
            nn.BatchNorm1d(c1),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2, stride=2)  # L -> L/2
        )

        # Block 2 increases features; pooling halves the temporal length again.
        self.block2 = nn.Sequential(
            nn.Conv1d(c1, c2, kernel_size=k2, stride=1,
                      padding=d2 * (k2 // 2), dilation=d2),
            nn.BatchNorm1d(c2),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2, stride=2)  # L/2 -> L/4
        )

        # Keep early/late features separate; one bin reproduces global averaging.
        self.block3 = nn.Sequential(
            nn.Conv1d(c2, c3, kernel_size=k3, stride=1,
                      padding=d3 * (k3 // 2), dilation=d3),
            nn.BatchNorm1d(c3),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(temporal_bins)  # [Batch, c3, temporal_bins]
        )

        # Classifier maps pooled features to gesture logits.
        self.classifier = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(c3 * temporal_bins, hidden_features),
            nn.ReLU(),
            nn.Linear(hidden_features, num_classes)
        )

    def forward(self, x):
        if x.ndim != 3 or x.shape[1] != self.config["in_channels"]:
            raise ValueError("Expected input shaped [batch, in_channels, samples]")
        if x.shape[-1] // 4 < self.temporal_bins:
            raise ValueError("Input must have at least 4 * temporal_bins samples")
        # [B,C,L] -> [B,c1,L/2] -> [B,c2,L/4] -> [B,c3,bins].
        x = self.block1(x)
        x = self.block2(x)
        x = self.block3(x)
        x = torch.flatten(x, start_dim=1)  # [Batch, c3 * temporal_bins]
        # Raw logits are sufficient because argmax does not require softmax.
        logits = self.classifier(x)
        return logits
