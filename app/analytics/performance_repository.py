"""Repository for cross-session performance analytics queries.

This module provides the data access layer for learning curve fitting and
longitudinal trainee progress tracking.
"""

from dataclasses import dataclass
from datetime import datetime
import sqlite3

from app.storage.database import DatabaseManager

@dataclass
class SessionPerformance:
    """Consolidated performance metrics for a single training session."""
    session_number: int       # Ordinal trial number (1-based, chronological)
    session_id: int           # Primary key in sessions table
    started_at: datetime
    error_count: int          # 0 if NULL in DB
    has_error_data: bool      # False if error_count was NULL in DB
    duration_seconds: float
    avg_rmssd: float | None
    avg_cli: float | None

def get_session_series(db: DatabaseManager) -> list[SessionPerformance]:
    """Fetch performance metrics for all completed sessions.
...

    Only sessions where 'ended_at' is NOT NULL are included. Sessions are
    ordered by 'started_at' ascending and numbered 1..N.

    Args:
        db: The database manager providing the connection.

    Returns:
        A list of SessionPerformance objects ordered chronologically.
    """
    conn = db.get_connection()
    
    # Subqueries are used to compute session-wide means for HRV and CLI.
    query = """
    SELECT 
        s.id, 
        s.started_at, 
        s.ended_at, 
        s.error_count,
        (SELECT AVG(rmssd) FROM hrv_samples WHERE session_id = s.id) as avg_rmssd,
        (SELECT AVG(cli) FROM cli_samples WHERE session_id = s.id) as avg_cli
    FROM sessions s
    WHERE s.ended_at IS NOT NULL
    ORDER BY s.started_at ASC
    """
    
    rows = conn.execute(query).fetchall()
    series = []
    
    for i, row in enumerate(rows, start=1):
        # sqlite3 might return datetime objects or strings depending on configuration.
        # We ensure they are datetime objects.
        started_at = row['started_at']
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)
            
        ended_at = row['ended_at']
        if isinstance(ended_at, str):
            ended_at = datetime.fromisoformat(ended_at)
            
        duration = (ended_at - started_at).total_seconds()
        
        error_count = row['error_count']
        has_error_data = error_count is not None
        
        series.append(SessionPerformance(
            session_number=i,
            session_id=row['id'],
            started_at=started_at,
            error_count=error_count if has_error_data else 0,
            has_error_data=has_error_data,
            duration_seconds=duration,
            avg_rmssd=row['avg_rmssd'],
            avg_cli=row['avg_cli']
        ))
        
    return series
