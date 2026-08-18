"""
goals_loader.py — Load and validate sales goals from goals.yaml.

Goals are NOT in SLX (Sheryl confirmed: SLX stores computed dues amounts, not sales
targets). They're admin-set values maintained either by editing goals.yaml directly,
or via the future UI form that reads/writes the same structure.

UI compatibility:
    The dict shape returned by load_goals_for_fy() is identical to what a UI form
    would POST as JSON. The save_goals_for_fy() function accepts the same shape
    and writes back to YAML — so the future API endpoints are:

        GET  /api/goals/{fiscal_year}        →  load_goals_for_fy()
        PUT  /api/goals/{fiscal_year}        →  save_goals_for_fy()
        GET  /api/goals/{fiscal_year}/{month}/{territory}  →  get_goal()

Usage:
    from src.config.goals_loader import load_goals_for_fy, get_goal

    goals = load_goals_for_fy("2025-26")
    # → {"EastKing": {"Oct": 3000, "Nov": 2900, ...}, ...}

    pierce_mar = get_goal(goals, "Pierce", "Mar")
    # → returns the goal value, or default, or None
"""

from pathlib import Path
from typing import Dict, Optional, Any

import yaml


# Canonical month abbreviations in fiscal year order (Oct = FY start).
FY_MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
             "Apr", "May", "Jun", "Jul", "Aug", "Sep"]


# ---------------------------------------------------------------------------
# Public API — these are the functions a UI/REST layer would wrap directly.
# ---------------------------------------------------------------------------

def load_goals_file(config_path: Path) -> Dict[str, Any]:
    """Load the entire goals.yaml file. Returns the full structure."""
    with open(config_path, "r") as f:
        data = yaml.safe_load(f) or {}
    return data


def load_goals_for_fy(
    fiscal_year: str,
    config_path: Path = Path("config/goals.yaml"),
) -> Dict[str, Dict[str, Optional[float]]]:
    """
    Load the goals for a specific fiscal year.

    Args:
        fiscal_year: e.g. "2025-26"
        config_path: Path to goals.yaml

    Returns:
        Dict shaped {territory: {month: goal_or_None}}.
        This is the exact shape a UI form's POST body would have.

    Raises:
        ValueError if fiscal_year not present in the config.
    """
    data = load_goals_file(config_path)
    fy_block = data.get("fiscal_years", {}).get(fiscal_year)
    if fy_block is None:
        raise ValueError(
            f"Fiscal year '{fiscal_year}' not found in {config_path}. "
            f"Available: {list(data.get('fiscal_years', {}))}"
        )
    return fy_block.get("territories", {})


def get_default_goal(
    fiscal_year: str,
    config_path: Path = Path("config/goals.yaml"),
) -> Optional[float]:
    """Return the per-month fallback goal for a fiscal year, or None."""
    data = load_goals_file(config_path)
    fy_block = data.get("fiscal_years", {}).get(fiscal_year, {})
    return fy_block.get("default_monthly_goal")


def get_goal(
    goals: Dict[str, Dict[str, Optional[float]]],
    territory: str,
    month: str,
    default: Optional[float] = None,
) -> Optional[float]:
    """
    Look up a single goal cell. Returns default if missing/null.

    This is the per-cell accessor a UI form would call when rendering each input.
    """
    # falsy-zero guard (finding #5): a deliberate 0 goal must NOT collapse to the
    # default ("0 or default" → default). The xlsx parser goes out of its way to
    # distinguish an intentional 0 from a blank; honor it here.
    v = (goals.get(territory, {}) or {}).get(month)
    return default if v is None else v


def goals_as_engine_dict(
    fiscal_year: str,
    months: list,
    config_path: Path = Path("config/goals.yaml"),
) -> Dict[str, Dict[str, Optional[float]]]:
    """
    Return goals in the exact shape the engine expects: goal[territory][month].

    Only the months passed in are included. Defaults are applied so every cell
    has a value (or None if no default).

    This is the integration point — call this from engine._load_goals() to
    replace the xlsx parser entirely.
    """
    raw = load_goals_for_fy(fiscal_year, config_path)
    default = get_default_goal(fiscal_year, config_path)
    return {
        territory: {m: get_goal({territory: per_month}, territory, m, default=default)
                    for m in months}
        for territory, per_month in raw.items()
    }


# ---------------------------------------------------------------------------
# UI write-path — accepts the same dict shape the loader returns
# ---------------------------------------------------------------------------

def save_goals_for_fy(
    fiscal_year: str,
    territories: Dict[str, Dict[str, Optional[float]]],
    default_monthly_goal: Optional[float] = None,
    config_path: Path = Path("config/goals.yaml"),
) -> None:
    """
    Write/replace the goals for a fiscal year and persist to YAML.

    Validates territory names and month keys before writing. Other fiscal years
    in the file are left untouched.

    A UI form would POST {territories: {...}, default_monthly_goal: N} and the
    handler would call this function directly.
    """
    _validate_territories_block(territories)

    data = load_goals_file(config_path) if config_path.exists() else {"fiscal_years": {}}
    data.setdefault("fiscal_years", {})
    data["fiscal_years"][fiscal_year] = {
        "default_monthly_goal": default_monthly_goal,
        "territories": territories,
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_territories_block(territories: Dict[str, Dict[str, Optional[float]]]) -> None:
    """Raise ValueError if any month key or value is malformed."""
    valid_months = set(FY_MONTHS)
    for territory, per_month in territories.items():
        if not isinstance(per_month, dict):
            raise ValueError(f"Territory '{territory}' must map to a dict of month→value")
        for month, value in per_month.items():
            if month not in valid_months:
                raise ValueError(
                    f"Invalid month '{month}' for territory '{territory}'. "
                    f"Expected one of {FY_MONTHS}"
                )
            if value is not None and not isinstance(value, (int, float)):
                raise ValueError(
                    f"Goal for {territory}/{month} must be a number or null, "
                    f"got {type(value).__name__}: {value!r}"
                )
