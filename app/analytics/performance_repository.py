"""Repository for cross-session performance analytics queries."""

from dataclasses import dataclass
from datetime import datetime
import math

import numpy as np

from app.utils.config import SCORE_MAX


@dataclass
class SessionPerformance:
    session_number: int
    session_id: int
    started_at: datetime
    error_count: int
    has_error_data: bool
    duration_seconds: float
    error_rate_per_session: float
    performance_error: float | None
    performance_score: float | None
    avg_rmssd: float | None
    avg_cli: float | None


def _coerce_datetime(value: datetime | str) -> datetime:
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def _normalise(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values
    lo = float(values.min())
    hi = float(values.max())
    if hi == lo:
        return np.zeros_like(values, dtype=float)
    return (values - lo) / (hi - lo)


def _compute_error_rate_per_session(error_count: int) -> float:
    return float(error_count)


def z_scores_to_percentages(
    values: list[float | None],
    *,
    invert: bool = False,
    neutral_percentage: float = 50.0,
) -> list[float]:
    """Convert a metric series into comparable percentile-like percentages.

    The series is first standardised to z-scores and then mapped to a
    0-100 percentage via the standard normal CDF. This keeps unlike metrics
    comparable on the same chart while preserving whether values are above or
    below the cohort mean.

    Missing values fall back to ``neutral_percentage``. When the cohort does
    not have enough variance to compute a stable z-score, every value maps to
    the neutral midpoint.
    """
    present_values = np.asarray([value for value in values if value is not None], dtype=float)
    if present_values.size == 0:
        return [neutral_percentage for _ in values]

    std = float(present_values.std(ddof=0))
    if std <= 0.0:
        return [neutral_percentage for _ in values]

    mean = float(present_values.mean())
    percentages: list[float] = []
    for value in values:
        if value is None:
            percentages.append(neutral_percentage)
            continue

        z_score = (float(value) - mean) / std
        if invert:
            z_score *= -1.0

        cdf = 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0)))
        percentages.append(float(max(0.0, min(100.0, cdf * 100.0))))

    return percentages


def get_session_series(db) -> list[SessionPerformance]:
    """Return completed sessions with derived dashboard performance metrics."""
    conn = db.get_connection()

    query = """
    SELECT
        s.id,
        s.started_at,
        s.ended_at,
        s.error_count,
        AVG(DISTINCT h.rmssd) AS avg_rmssd,
        AVG(DISTINCT c.cli) AS avg_cli
    FROM sessions s
    LEFT JOIN hrv_samples h ON h.session_id = s.id
    LEFT JOIN cli_samples c ON c.session_id = s.id
    WHERE s.ended_at IS NOT NULL
    GROUP BY s.id
    ORDER BY s.started_at ASC
    """

    rows = conn.execute(query).fetchall()
    base_series: list[dict] = []

    for i, row in enumerate(rows, start=1):
        started_at = _coerce_datetime(row["started_at"])
        ended_at = _coerce_datetime(row["ended_at"])
        raw_error_count = row["error_count"]
        has_error_data = raw_error_count is not None
        error_count = int(raw_error_count or 0)
        duration_seconds = max(0.0, (ended_at - started_at).total_seconds())

        base_series.append(
            {
                "session_number": i,
                "session_id": row["id"],
                "started_at": started_at,
                "error_count": error_count,
                "has_error_data": has_error_data,
                "duration_seconds": duration_seconds,
                "error_rate_per_session": _compute_error_rate_per_session(error_count),
                "avg_rmssd": row["avg_rmssd"],
                "avg_cli": row["avg_cli"],
            }
        )

    if not base_series:
        return []

    durations = np.array([item["duration_seconds"] for item in base_series], dtype=float)
    error_rates = np.array([item["error_rate_per_session"] for item in base_series], dtype=float)
    composite_errors = (0.5 * _normalise(durations) + 0.5 * _normalise(error_rates)) * SCORE_MAX

    series: list[SessionPerformance] = []
    for item, performance_error in zip(base_series, composite_errors):
        performance_error = float(performance_error)
        series.append(
            SessionPerformance(
                session_number=item["session_number"],
                session_id=item["session_id"],
                started_at=item["started_at"],
                error_count=item["error_count"],
                has_error_data=item["has_error_data"],
                duration_seconds=item["duration_seconds"],
                error_rate_per_session=item["error_rate_per_session"],
                performance_error=performance_error,
                performance_score=float(SCORE_MAX - performance_error),
                avg_rmssd=item["avg_rmssd"],
                avg_cli=item["avg_cli"],
            )
        )

    return series
