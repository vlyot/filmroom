"""The turning point is the possession's final decision: the action that lost the ball or ended the move. It
is flagged when the best alternative was clearly worth more. The 13 Oct gate showed that earlier causes can't
be picked out reliably, so none are claimed (PRD v3.3)."""

from pathlib import Path

import numpy as np
from pydantic import BaseModel

PARAMS_PATH = Path(__file__).with_name("params.json")
FLAG_QUANTILE = 0.85  # flag the top 15% of possessions by regret at the turning point
SEVERITY_QUANTILE = 0.99


class EngineParams(BaseModel):
    flag_threshold: float  # minimum regret at the turning point for a possession to be flagged
    severity_scale: float  # regret that counts as severity 1


def load_params(path: Path = PARAMS_PATH) -> EngineParams:
    return EngineParams.model_validate_json(path.read_text(encoding="utf-8"))


def save_params(params: EngineParams, path: Path = PARAMS_PATH) -> None:
    path.write_text(params.model_dump_json(indent=1) + "\n", encoding="utf-8")


def regret(values: dict[str, float], chosen_id: str) -> float:
    """How much more the best alternative was worth than the action taken (0 if nothing beat it)."""
    return max(0.0, max(v for k, v in values.items() if k != chosen_id) - values[chosen_id])


def fit_params(regrets: list[float]) -> EngineParams:
    """Flag threshold and severity scale from the regret at every turning point in every match; no labels."""
    return EngineParams(
        flag_threshold=round(float(np.quantile(regrets, FLAG_QUANTILE)), 4),
        severity_scale=round(float(np.quantile(regrets, SEVERITY_QUANTILE)), 4),
    )
