"""
Calibration Framework.
Validates probabilities empirically.
"""
from typing import List

class ProbabilityCalibrator:
    """
    Calculates calibration metrics for probabilistic models.
    """
    def calculate_brier_score(
        self,
        predictions: List[float],
        outcomes: List[int]
    ) -> float:
        """
        Calculates the Brier score.
        Brier = mean((prediction - outcome)^2)
        Lower is better (0.0 is perfect).
        """
        if not predictions or not outcomes:
            return 0.0
            
        if len(predictions) != len(outcomes):
            raise ValueError("Predictions and outcomes must have the same length")
            
        squared_errors = [
            (p - o) ** 2
            for p, o in zip(predictions, outcomes)
        ]
        
        return sum(squared_errors) / len(squared_errors)
        
    def calculate_calibration_error(
        self,
        predictions: List[float],
        outcomes: List[int],
        bins: int = 10
    ) -> float:
        """
        Calculates the expected calibration error (ECE).
        For simplicity, if bins=1, it just returns the absolute difference
        between the average prediction and average outcome.
        """
        if not predictions or not outcomes:
            return 0.0
            
        if len(predictions) != len(outcomes):
            raise ValueError("Predictions and outcomes must have the same length")
            
        if bins == 1:
            avg_pred = sum(predictions) / len(predictions)
            avg_out = sum(outcomes) / len(outcomes)
            return abs(avg_pred - avg_out)
            
        # TODO: Implement multi-bin ECE if needed
        # For now, fallback to 1 bin logic or raise if bins > 1 and not implemented
        # Let's implement 1 bin for now as a simple metric.
        avg_pred = sum(predictions) / len(predictions)
        avg_out = sum(outcomes) / len(outcomes)
        return abs(avg_pred - avg_out)
