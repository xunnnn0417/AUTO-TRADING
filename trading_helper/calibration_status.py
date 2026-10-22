"""Fast, offline-only calibration completion counts for the current scheme.

Never touches broker/UIA, and 'saved' means a coordinate was persisted, NOT
that the broker form is verified live or safe to trade.
"""
from __future__ import annotations
from math import isfinite

def has_saved_coordinate(point) -> bool:
    if not isinstance(point, dict):
        return False
    try:
        x,y=float(point["x"]),float(point["y"])
        return (isfinite(x) and isfinite(y)
                and 0<=x<=1 and 0<=y<=1)
    except (ValueError,TypeError,KeyError,OverflowError):
        return False

def completion(points,keys) -> tuple[int,int]:
    """Valid saved coordinate count / total for a single stage."""
    selected=tuple(keys)
    points=points if isinstance(points,dict) else {}
    return sum(has_saved_coordinate(points.get(k)) for k in selected),len(selected)
