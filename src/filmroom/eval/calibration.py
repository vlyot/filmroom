"""Model calibration: out-of-fold predictions against real SoccER pass and shot outcomes."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from filmroom.engine.pass_model import BAND_EDGES, EngineModels
from filmroom.engine.training import TrainingRows

PLOT_MIN_N = 20


@dataclass(frozen=True)
class Bin:
    lo: float
    hi: float
    n: int
    mean_p: float
    observed: float


@dataclass(frozen=True)
class CalibrationReport:
    n: int
    observed_rate: float
    brier: float
    base_rate_brier: float  # Brier score of always predicting the observed rate
    ece: float
    bins: list[Bin]
    bands: dict[str, Bin]


def out_of_fold(
    rows: dict[str, TrainingRows], models: dict[str, EngineModels]
) -> tuple[np.ndarray, np.ndarray]:
    """Each match's passes predicted by the model that was fitted without that match."""
    p = np.concatenate([models[m].pass_p(r.pass_X, r.pass_keys) for m, r in rows.items()])
    return p, np.concatenate([r.pass_y for r in rows.values()]).astype(float)


def shot_out_of_fold(
    rows: dict[str, TrainingRows], models: dict[str, EngineModels]
) -> tuple[np.ndarray, np.ndarray]:
    """Each match's shots given xG by the model fitted without that match, against whether they went in."""
    p = np.concatenate([models[m].xg(r.shot_X) for m, r in rows.items()])
    return p, np.concatenate([r.shot_goal for r in rows.values()]).astype(float)


def _bin(p: np.ndarray, y: np.ndarray, lo: float, hi: float) -> Bin:
    inside = (p >= lo) & (p < hi)
    n = int(inside.sum())
    return Bin(lo, hi, n, float(p[inside].mean()) if n else 0.0, float(y[inside].mean()) if n else 0.0)


def calibration_report(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> CalibrationReport:
    edges = np.linspace(0, 1, n_bins + 1)
    edges[-1] = 1.0 + 1e-9
    bins = [_bin(p, y, lo, hi) for lo, hi in zip(edges[:-1], edges[1:], strict=True)]
    band_edges = (0.0, *BAND_EDGES, 1.0 + 1e-9)
    bands = {
        name: _bin(p, y, lo, hi)
        for name, lo, hi in zip(("low", "medium", "high"), band_edges[:-1], band_edges[1:], strict=True)
    }
    return CalibrationReport(
        n=len(p),
        observed_rate=float(y.mean()),
        brier=float(np.mean((p - y) ** 2)),
        base_rate_brier=float(np.mean((y.mean() - y) ** 2)),
        ece=sum(b.n * abs(b.mean_p - b.observed) for b in bins) / len(p),
        bins=bins,
        bands=bands,
    )


def plot(report: CalibrationReport, path: Path) -> None:
    import matplotlib  # dev-only dependency: the API image never draws plots

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    filled = [b for b in report.bins if b.n >= PLOT_MIN_N]  # a bin of a handful of passes is noise
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], color="0.7", linewidth=1, label="perfect calibration")
    ax.plot(
        [b.mean_p for b in filled],
        [b.observed for b in filled],
        marker="o",
        color="#2563eb",
        label="pass model",
    )
    for b in filled:
        ax.annotate(str(b.n), (b.mean_p, b.observed), textcoords="offset points", xytext=(4, -10), fontsize=7)
    ax.set(
        xlim=(0, 1),
        ylim=(0, 1),
        xlabel="Predicted completion probability (out of fold)",
        ylabel="Observed completion rate",
        title=f"Pass model calibration: {report.n} real passes, ECE {report.ece:.3f}",
    )
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
