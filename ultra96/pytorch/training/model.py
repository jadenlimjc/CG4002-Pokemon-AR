import torch
import torch.nn as nn

# =====================================================================
# 1D CNN MODEL ARCHITECTURE
# =====================================================================
class Gesture1DCNN(nn.Module):
    """
    1D CNN tailored for IMU-based edge deployment.
    Uses simple, synthesizable operations (Conv1d, BatchNorm1d, ReLU, Linear).
    """
    def __init__(self, in_channels=6, num_classes=11,
                 channels=(32, 64, 128), kernel_sizes=(7, 5, 3),
                 hidden_features=64, dropout=0.3):
        super(Gesture1DCNN, self).__init__()
        if len(channels) != 3 or any(type(c) is not int or c < 1 for c in channels):
            raise ValueError("channels must contain three positive integers")
        if (len(kernel_sizes) != 3 or
                any(type(k) is not int or k < 1 or k % 2 == 0 for k in kernel_sizes)):
            raise ValueError("kernel_sizes must contain three positive odd integers")
        if type(hidden_features) is not int or hidden_features < 1:
            raise ValueError("hidden_features must be a positive integer")
        self.config = {"in_channels": in_channels, "num_classes": num_classes,
                       "channels": list(channels), "kernel_sizes": list(kernel_sizes),
                       "hidden_features": hidden_features, "dropout": dropout}
        c1, c2, c3 = channels
        k1, k2, k3 = kernel_sizes

        # Block 1 learns short motion patterns; pooling halves 256 -> 128.
        self.block1 = nn.Sequential(
            nn.Conv1d(in_channels, c1, kernel_size=k1, stride=1, padding=k1 // 2),
            nn.BatchNorm1d(c1),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2, stride=2)  # 256 -> 128
        )

        # Block 2 increases features; pooling halves 128 -> 64.
        self.block2 = nn.Sequential(
            nn.Conv1d(c1, c2, kernel_size=k2, stride=1, padding=k2 // 2),
            nn.BatchNorm1d(c2),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2, stride=2)  # 128 -> 64
        )

        # Block 3 averages its features over all 64 timesteps.
        self.block3 = nn.Sequential(
            nn.Conv1d(c2, c3, kernel_size=k3, stride=1, padding=k3 // 2),
            nn.BatchNorm1d(c3),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1)  # Output: (Batch, c3, 1)
        )

        # Classifier maps pooled features to gesture logits.
        self.classifier = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(c3, hidden_features),
            nn.ReLU(),
            nn.Linear(hidden_features, num_classes)
        )

    def forward(self, x):
        # Shape flow: [B,C,256] -> [B,c1,128] -> [B,c2,64] -> [B,c3].
        x = self.block1(x)
        x = self.block2(x)
        x = self.block3(x)
        x = torch.flatten(x, start_dim=1)  # Shape: (Batch, 128)
        # Raw logits are sufficient because argmax does not require softmax.
        logits = self.classifier(x)
        return logits
