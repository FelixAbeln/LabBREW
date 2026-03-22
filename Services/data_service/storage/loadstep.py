"""Loadstep averaging logic."""

from typing import Any


class LoadstepAverager:
    """Averages parameter values over a time period for loadsteps."""

    def __init__(self, parameters: list[str], duration_seconds: float):
        """Initialize the averager.
        
        Args:
            parameters: List of parameter names to average
            duration_seconds: Duration of the loadstep
        """
        self.parameters = parameters
        self.duration_seconds = duration_seconds
        self.samples: list[dict[str, Any]] = []
        self.sample_count = 0

    def add_sample(self, data: dict[str, Any]) -> None:
        """Add a sample to the averager.
        
        Args:
            data: Dictionary of parameter names to values
        """
        sample = {param: data.get(param) for param in self.parameters}
        self.samples.append(sample)
        self.sample_count += 1

    def get_average(self) -> dict[str, float | None]:
        """Calculate and return the average of all samples.
        
        Returns:
            Dictionary of parameter names to average values
        """
        if not self.samples:
            return {param: None for param in self.parameters}

        averages = {}
        for param in self.parameters:
            # Collect all numeric values for this parameter
            values = []
            for sample in self.samples:
                val = sample.get(param)
                if val is not None and isinstance(val, (int, float)):
                    values.append(float(val))

            if values:
                averages[param] = sum(values) / len(values)
            else:
                averages[param] = None

        return averages
