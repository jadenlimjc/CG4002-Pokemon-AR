import torch
import torch.nn as nn

# =====================================================================
# 1D CNN MODEL ARCHITECTURE
# =====================================================================
class Gesture1DCNN(nn.Module):
    """
    1D CNN tailored for IMU-based edge deployment.
    Uses simple, synthesizable operations (Conv1d, BatchNorm1d, ReLU, Linear).
    This class is the "Single Source of Truth" for the model architecture.
    """
    def __init__(self, in_channels=6, num_classes=7):
        super(Gesture1DCNN, self).__init__()

        # Conv Block 1: Large receptive field (kernel=7)
        self.block1 = nn.Sequential(
            nn.Conv1d(in_channels=in_channels, out_channels=32, kernel_size=7, stride=1, padding=3),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2, stride=2)  # 128 -> 64
        )

        # Conv Block 2: Medium receptive field (kernel=5)
        self.block2 = nn.Sequential(
            nn.Conv1d(in_channels=32, out_channels=64, kernel_size=5, stride=1, padding=2),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2, stride=2)  # 64 -> 32
        )

        # Conv Block 3: Fine feature extraction (kernel=3)
        self.block3 = nn.Sequential(
            nn.Conv1d(in_channels=64, out_channels=128, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1)  # Flattens temporal dimension -> (Batch, 128, 1)
        )

        # Classification Head
        self.classifier = nn.Sequential(
            nn.Dropout(0.3),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, num_classes)
        )

    def forward(self, x):
        # Expected input shape: (Batch, 6, 128)
        x = self.block1(x)
        x = self.block2(x)
        x = self.block3(x)
        x = torch.flatten(x, start_dim=1)  # Shape: (Batch, 128)
        logits = self.classifier(x)
        return logits