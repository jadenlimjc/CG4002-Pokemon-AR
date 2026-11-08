"""Small IMU perturbations applied to training batches only."""

import math

import torch


class IMUTrainingAugmentation:
    """Preserve half the examples; perturb the others with a private CPU RNG.

    All six channels share the same time mapping. Acceleration scaling acts
    around each window's temporal mean to avoid scaling its gravity offset.
    Noise is expressed in the sensor-range-normalized units used by the NPZs.
    Input tensors and their underlying dataset storage are never modified.
    """

    def __init__(self, probability=0.5, amplitude_fraction=0.1,
                 noise_std=0.002, speed_fraction=0.1, seed=43):
        values = (probability, amplitude_fraction, noise_std, speed_fraction)
        if (not all(math.isfinite(v) for v in values)
                or not 0 <= probability <= 1 or not 0 <= amplitude_fraction < 1
                or noise_std < 0 or not 0 <= speed_fraction < 1
                or type(seed) is not int or seed < 0):
            raise ValueError("Invalid augmentation strength, probability, or seed")
        self.config = dict(probability=probability, amplitude_fraction=amplitude_fraction,
                           noise_std=noise_std, speed_fraction=speed_fraction, seed=seed)
        self.generator = torch.Generator(device="cpu").manual_seed(seed)

    @torch.no_grad()
    def __call__(self, inputs):
        if inputs.device.type != "cpu" or inputs.ndim != 3 or inputs.shape[1] != 6:
            raise ValueError("Augmentation expects a CPU batch shaped [B, 6, T]")
        batch, _, length = inputs.shape
        if length < 2 or not inputs.is_floating_point():
            raise ValueError("Augmentation requires floating-point windows with T >= 2")
        cfg = self.config
        if cfg["probability"] == 0:
            return inputs.clone()
        apply = torch.rand((batch, 1, 1), generator=self.generator) < cfg["probability"]
        speed = 1 + (2 * torch.rand((batch, 1), generator=self.generator) - 1) * cfg["speed_fraction"]
        centre = (length - 1) / 2
        times = ((torch.arange(length) - centre) * speed + centre).clamp(0, length - 1)
        left = times.floor().long()
        right = (left + 1).clamp_max(length - 1)
        alpha = (times - left).unsqueeze(1).to(inputs.dtype)
        warped = (inputs.gather(2, left[:, None, :].expand(-1, 6, -1)) * (1 - alpha)
                  + inputs.gather(2, right[:, None, :].expand(-1, 6, -1)) * alpha)
        scales = 1 + (2 * torch.rand((batch, 2, 1), generator=self.generator) - 1) * cfg["amplitude_fraction"]
        accel_mean = warped[:, :3].mean(dim=2, keepdim=True)
        acceleration = (warped[:, :3] - accel_mean) * scales[:, :1] + accel_mean
        rotation = warped[:, 3:] * scales[:, 1:]
        augmented = torch.cat((acceleration, rotation), dim=1)
        noise = torch.randn(inputs.shape, generator=self.generator, dtype=inputs.dtype)
        augmented = augmented + cfg["noise_std"] * noise
        return torch.where(apply, augmented, inputs)


class SpatialIMUTrainingAugmentation:
    """Shared proper 3D rotation, monotonic time warp, and magnitude envelopes.

    Acceleration magnitude variation acts on motion around the temporal mean
    (an approximate gravity component); gyro magnitude variation acts directly.
    These perturbations approximate sensor placement and motion variation, not
    a physically exact reconstruction of a different movement.
    """

    def __init__(self, probability=0.5, rotation_degrees=10.0, warp_strength=0.1,
                 magnitude_fraction=0.1, seed=43):
        if (not all(math.isfinite(v) for v in
                    (probability, rotation_degrees, warp_strength, magnitude_fraction))
                or not 0 <= probability <= 1 or not 0 <= rotation_degrees <= 180
                or not 0 <= warp_strength < 1 or not 0 <= magnitude_fraction < 1
                or type(seed) is not int or seed < 0):
            raise ValueError("Invalid spatial IMU augmentation settings")
        self.config = dict(kind="imu", probability=probability,
                           rotation_degrees=rotation_degrees, warp_strength=warp_strength,
                           magnitude_fraction=magnitude_fraction, seed=seed)
        self.generator = torch.Generator(device="cpu").manual_seed(seed)

    def time_mapping(self, batch, length, dtype):
        """Integrate a positive smooth speed curve, fixing both endpoints."""
        t = torch.linspace(0, 1, length, dtype=dtype)[None, :]
        phases = 2 * math.pi * torch.rand((batch, 2, 1), generator=self.generator, dtype=dtype)
        curve = (torch.sin(2 * math.pi * t + phases[:, 0])
                 + 0.5 * torch.sin(4 * math.pi * t + phases[:, 1])) / 1.5
        speed = torch.exp(self.config["warp_strength"] * curve)
        steps = (speed[:, 1:] + speed[:, :-1]) / 2
        cumulative = torch.cat((torch.zeros((batch, 1), dtype=dtype), steps.cumsum(1)), dim=1)
        return cumulative / cumulative[:, -1:] * (length - 1)

    @torch.no_grad()
    def __call__(self, inputs):
        if (inputs.device.type != "cpu" or inputs.ndim != 3 or inputs.shape[1] != 6
                or inputs.shape[2] < 2 or not inputs.is_floating_point()):
            raise ValueError("Augmentation expects floating-point CPU [B, 6, T] with T >= 2")
        batch, _, length = inputs.shape
        cfg = self.config
        if cfg["probability"] == 0:
            return inputs.clone()
        apply = torch.rand((batch, 1, 1), generator=self.generator) < cfg["probability"]
        warped = inputs.clone()
        if cfg["warp_strength"]:
            times = self.time_mapping(batch, length, inputs.dtype).clamp(0, length - 1)
            left = times.floor().long()
            right = (left + 1).clamp_max(length - 1)
            alpha = (times - left).unsqueeze(1)
            warped = (inputs.gather(2, left[:, None].expand(-1, 6, -1)) * (1 - alpha)
                      + inputs.gather(2, right[:, None].expand(-1, 6, -1)) * alpha)
        if cfg["magnitude_fraction"]:
            # One smooth positive scalar per 3D sensor vector: never scale axes
            # independently. Random phase and gain vary the magnitude over time.
            t = torch.linspace(0, 1, length, dtype=inputs.dtype)[None, None, :]
            phase = 2 * math.pi * torch.rand((batch, 2, 1), generator=self.generator, dtype=inputs.dtype)
            gain = 2 * torch.rand((batch, 2, 1), generator=self.generator, dtype=inputs.dtype) - 1
            scales = 1 + cfg["magnitude_fraction"] * gain * torch.sin(2 * math.pi * t + phase)
            mean = warped[:, :3].mean(dim=2, keepdim=True)
            warped = torch.cat(((warped[:, :3] - mean) * scales[:, :1] + mean,
                                warped[:, 3:] * scales[:, 1:]), dim=1)
        if cfg["rotation_degrees"]:
            # Rodrigues' rotation formula; the same axis and angle rotate both
            # sensor triads, including the acceleration gravity component.
            axis = torch.randn((batch, 1, 3, 1), generator=self.generator, dtype=inputs.dtype)
            axis = axis / axis.norm(dim=2, keepdim=True).clamp_min(1e-12)
            angle = ((2 * torch.rand((batch, 1, 1, 1), generator=self.generator,
                                    dtype=inputs.dtype) - 1) * math.radians(cfg["rotation_degrees"]))
            vectors = warped.reshape(batch, 2, 3, length)
            rotated = (vectors * angle.cos()
                       + torch.cross(axis.expand_as(vectors), vectors, dim=2) * angle.sin()
                       + axis * (axis * vectors).sum(dim=2, keepdim=True) * (1 - angle.cos()))
            warped = rotated.reshape_as(inputs)
        return torch.where(apply, warped, inputs)


def make_training_augmentation(config):
    """Accept older basic configs and explicitly tagged IMU configs."""
    options = dict(config)
    kind = options.pop("kind", "basic")
    if kind == "basic":
        return IMUTrainingAugmentation(**options)
    if kind == "imu":
        return SpatialIMUTrainingAugmentation(**options)
    raise ValueError(f"Unknown augmentation kind: {kind}")
