"""Schmettow parametric learning curve fitting module.

This module implements the Schmettow model (2026) for fitting and predicting
learning trajectories based on error counts.
"""

import numpy as np
from scipy.optimize import curve_fit
from scipy.special import expit  # sigmoid
from dataclasses import dataclass
from app.utils.config import SCORE_MAX, LC_MIN_SESSIONS

@dataclass
class SessionDataPoint:
    """Data point for a single session in the learning curve."""
    trial: int           # ordinal session number (1-based)
    error_count: int
    performance_score: float   # SCORE_MAX - error_count

@dataclass
class SchmettowFit:
    """Results of a Schmettow model fit."""
    leff: float          # ∈ (0,1) - Learning efficiency. Higher = faster learning.
    pexp: float          # ≥ 0 - Previous experience in trial-equivalents.
    maxp: float          # ≥ 0 - Asymptotic error floor.
    scale: float         # > 0 - Magnitude of trainable component.
    maxp_performance: float    # SCORE_MAX - maxp (display ceiling)
    r_squared: float           # Coefficient of determination
    predicted_errors: np.ndarray
    predicted_performance: np.ndarray

def get_mentor_message(mastery_pct: float) -> str:
    """Generate a context-aware 'Honest Mentor' assessment message.

    Args:
        mastery_pct: Mastery level relative to potential (0-100).

    Returns:
        A human-readable feedback string.
    """
    if mastery_pct >= 80.0:
        return "You're approaching your performance ceiling. Excellent consistency."
    elif mastery_pct >= 40.0:
        remaining = 100.0 - mastery_pct
        return f"You're still {remaining:.0f}% from your potential. Keep grinding."
    else:
        return "Early stage. Each session matters most now — your curve is steepest here."

def fit_schmettow(
    trial_numbers: np.ndarray,
    error_counts: np.ndarray,
    score_max: float = SCORE_MAX,
) -> SchmettowFit | None:
    """Compute the Schmettow parametric learning curve fit.

    The Schmettow model decomposes performance into learning efficiency,
    previous experience, and maximum performance.

    Formula (Error Domain):
        errors(t) = scale * (1 - leff)**(t + pexp) + maxp

    Note: The formula used here ensures that higher 'leff' results in faster
    error reduction, as specified in the design requirements, and that
    parameters remain in their valid domains.

    Args:
        trial_numbers: Array of ordinal session numbers (1-based).
        error_counts: Array of error counts for each session.
        score_max: Maximum possible performance score (default from config).

    Returns:
        A SchmettowFit object containing parameters and predictions,
        or None if data is insufficient or the fit diverges.

    References:
        Schmettow, Chan, Groenier (2026). Parametric learning curve models
        for simulation-based surgery training.
    """
    if len(trial_numbers) < LC_MIN_SESSIONS:
        return None

    # Unbounded parameterization: x = [leff_raw, pexp_raw, maxp_raw, scale_raw]
    def model(t, leff_raw, pexp_raw, maxp_raw, scale_raw):
        leff = expit(leff_raw)
        pexp = np.exp(np.clip(pexp_raw, -100, 100))
        maxp = np.exp(np.clip(maxp_raw, -100, 100))
        scale = np.exp(np.clip(scale_raw, -100, 100))
        # errors(t) = scale * (1 - leff)^(t + pexp) + maxp
        return scale * (1 - leff)**(t + pexp) + maxp

    try:
        # Initial guesses: leff=0.5 (leff_raw=0), pexp=0 (pexp_raw=-inf, use 0),
        # maxp=min_errors, scale=range_errors
        min_errors = np.min(error_counts)
        range_errors = np.max(error_counts) - min_errors
        p0 = [0.0, 0.0, np.log(max(0.1, min_errors)), np.log(max(1.0, range_errors))]

        popt, _ = curve_fit(model, trial_numbers, error_counts, p0=p0, maxfev=2000)

        leff = expit(popt[0])
        pexp = np.exp(popt[1])
        maxp = np.exp(popt[2])
        scale = np.exp(popt[3])

        # If fit results in almost zero learning, we might want to flag it,
        # but for now we follow the requirement "divergent fit (all-zero errors) returns None"
        if np.all(error_counts == error_counts[0]) and error_counts[0] == 0:
            return None

        predicted_errors = model(trial_numbers, *popt)
        predicted_performance = score_max - predicted_errors
        maxp_performance = score_max - maxp

        # Calculate R-squared
        residuals = error_counts - predicted_errors
        ss_res = np.sum(residuals**2)
        ss_tot = np.sum((error_counts - np.mean(error_counts))**2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0.0

        return SchmettowFit(
            leff=leff,
            pexp=pexp,
            maxp=maxp,
            scale=scale,
            maxp_performance=maxp_performance,
            r_squared=r_squared,
            predicted_errors=predicted_errors,
            predicted_performance=predicted_performance
        )
    except Exception:
        return None

def predict_at_trial(fit: SchmettowFit, trial: int, score_max: float = SCORE_MAX) -> float:
    """Compute predicted performance score at a given trial.

    Args:
        fit: The SchmettowFit result.
        trial: The trial number to predict for.
        score_max: Maximum possible score.

    Returns:
        Predicted performance score.
    """
    errors = fit.scale * (1 - fit.leff)**(trial + fit.pexp) + fit.maxp
    return score_max - errors

def mastery_percent(fit: SchmettowFit, current_performance: float) -> float:
    """Calculate mastery percentage relative to predicted ceiling.

    Args:
        fit: The SchmettowFit result.
        current_performance: The current performance score.

    Returns:
        Mastery percentage (0-100), clamped to range.
    """
    # maxp_performance is the ceiling (Score_max - maxp)
    if fit.maxp_performance <= 0:
        return 0.0
    percent = (current_performance / fit.maxp_performance) * 100
    return float(max(0.0, min(100.0, percent)))
