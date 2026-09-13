"""Replaceable data sources for FPGA model evaluation.

Every source yields ``(window, label)`` where window has shape [6, 128].
To add live sensor data later, implement the same ``__iter__`` contract; the
FPGA evaluator itself does not need to change.
"""

import numpy as np


class SyntheticIMUDataSource:
    """NumPy equivalent of the synthetic dataset used for model validation."""

    def __init__(self, num_samples=300, window_size=128, num_classes=7, seed=123):
        self.num_samples = num_samples
        self.window_size = window_size
        self.num_classes = num_classes
        self.rng = np.random.RandomState(seed)
        self.class_names = [
            "Neutral", "Aim", "Throw", "Stop Aim", "Punch",
            "Downward Swipe", "Guard"
        ]

    def __iter__(self):
        for _ in range(self.num_samples):
            label = int(self.rng.randint(0, self.num_classes))
            generated_label = label
            if label == 0 and self.rng.rand() < 0.25:
                generated_label = -1
            yield self._generate_sample(generated_label), label

    def _generate_sample(self, label):
        sample = np.zeros((6, self.window_size), dtype=np.float32)
        for channel in range(6):
            noise_level = self.rng.uniform(0.05, 0.2)
            sample[channel] = self.rng.normal(
                0, noise_level, self.window_size
            )
            sample[channel] += self.rng.normal(0, 0.05)
            sample[channel] += np.linspace(
                0, self.rng.normal(0, 0.03), self.window_size
            )

        if label == 0:
            return sample
        if label == -1:
            for _ in range(self.rng.randint(1, 4)):
                channel = self.rng.randint(0, 6)
                position = self.rng.randint(20, self.window_size - 20)
                width = self.rng.uniform(0.1, 0.4)
                sign = 1 if self.rng.rand() > 0.5 else -1
                amplitude = self.rng.uniform(1.0, 3.0) * sign
                points = np.arange(self.window_size)
                sample[channel] += amplitude * np.exp(
                    -((points - position) / (width * 20)) ** 2
                )
            return sample

        time_shift = self.rng.randint(-self.window_size // 3, self.window_size // 3)
        duration = self.rng.randint(50, 80)
        start = max(0, self.window_size // 2 - duration // 2 + time_shift)
        end = min(self.window_size, start + duration)
        t = np.linspace(-5, 5, end - start)
        variation = self.rng.uniform(0.8, 1.2)
        amplitude_scale = self.rng.uniform(0.8, 1.2)

        def spike(amplitude, std):
            return amplitude * np.exp(-t ** 2 / (2 * (std * variation) ** 2))

        def smooth_curve(amplitude, period):
            scaled_period = period * variation
            return (amplitude * np.sin(t / scaled_period)
                    * (t > 0) * (t < np.pi * scaled_period))

        def punch_recoil(amplitude, std):
            return (spike(amplitude, std)
                    - amplitude * 0.4 * np.exp(
                        -(t - std * 2) ** 2
                        / (2 * (std * 0.8 * variation) ** 2)))

        if label == 1:
            sample[0, start:end] -= spike(1.5 * amplitude_scale, 0.8)
            sample[2, start:end] += spike(1.2 * amplitude_scale, 0.8)
        elif label == 2:
            sample[0, start:end] += spike(2.5 * amplitude_scale, 0.4)
            sample[4, start:end] += spike(2.0 * amplitude_scale, 0.4)
            sample[2, start:end] += spike(0.5 * amplitude_scale, 0.8)
        elif label == 3:
            sample[0, start:end] += spike(1.0 * amplitude_scale, 1.0)
            sample[2, start:end] -= spike(1.0 * amplitude_scale, 1.0)
        elif label == 4:
            sample[0, start:end] += punch_recoil(3.0 * amplitude_scale, 0.3)
            sample[4, start:end] += spike(0.4 * amplitude_scale, 0.5)
        elif label == 5:
            sample[2, start:end] -= spike(2.8 * amplitude_scale, 0.4)
        elif label == 6:
            sample[1, start:end] += smooth_curve(1.8 * amplitude_scale, 2.0)
            sample[5, start:end] += smooth_curve(1.5 * amplitude_scale, 2.0)

        time_points = np.linspace(-5, 5, self.window_size)
        warped_points = time_points * self.rng.uniform(0.8, 1.2)
        final_sample = np.zeros_like(sample)
        for channel in range(6):
            final_sample[channel] = np.interp(
                time_points, warped_points, sample[channel]
            )
        return final_sample


class NPZIMUDataSource:
    """Load real/pre-recorded windows from an NPZ containing X and y arrays."""

    def __init__(self, path):
        with np.load(path) as dataset:
            self.windows = np.asarray(dataset["X"], dtype=np.float32).copy()
            self.labels = np.asarray(dataset["y"], dtype=np.int64).copy()
            self.class_names = (
                dataset["class_names"].tolist()
                if "class_names" in dataset else [str(index) for index in range(7)]
            )
        if self.windows.ndim != 3 or self.windows.shape[1:] != (6, 128):
            raise ValueError("X must have shape [number_of_samples, 6, 128]")
        if self.labels.shape != (len(self.windows),):
            raise ValueError("y must have one label per window")
        if len(self.class_names) != 7:
            raise ValueError("class_names must contain seven entries")

    def __iter__(self):
        return iter(zip(self.windows, self.labels))
