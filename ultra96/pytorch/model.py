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
    def __init__(self, in_channels=6, num_classes=10):
        super(Gesture1DCNN, self).__init__()

        # Block 1 learns short motion patterns; pooling halves 256 -> 128.
        self.block1 = nn.Sequential(
            nn.Conv1d(in_channels=in_channels, out_channels=32, kernel_size=7, stride=1, padding=3),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2, stride=2)  # 256 -> 128
        )

        # Block 2 expands 32 -> 64 features; pooling halves 128 -> 64.
        self.block2 = nn.Sequential(
            nn.Conv1d(in_channels=32, out_channels=64, kernel_size=5, stride=1, padding=2),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2, stride=2)  # 128 -> 64
        )

        # Block 3 learns 128 features, then averages over all 64 timesteps.
        self.block3 = nn.Sequential(
            nn.Conv1d(in_channels=64, out_channels=128, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1)  # Flattens temporal dimension -> (Batch, 128, 1)
        )

        # Classifier maps the 128 features to ten gesture logits.
        self.classifier = nn.Sequential(
            nn.Dropout(0.3),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, num_classes)
        )

    def forward(self, x):
        # Shape flow: [B,6,256] -> [B,32,128] -> [B,64,64] -> [B,128].
        x = self.block1(x)
        x = self.block2(x)
        x = self.block3(x)
        x = torch.flatten(x, start_dim=1)  # Shape: (Batch, 128)
        # Raw logits are sufficient because argmax does not require softmax.
        logits = self.classifier(x)
        return logits
