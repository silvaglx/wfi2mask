"""Demonstration plots: true color and true color + water-mask overlay."""

from __future__ import annotations

import numpy as np


def stretch(arr: np.ndarray, pct: float = 98) -> np.ndarray:
    valid = arr[arr > 0]
    if valid.size == 0:
        return np.zeros_like(arr)
    return np.clip(arr / max(np.percentile(valid, pct), 1e-6), 0, 1)


def plot_overlay(true_color: np.ndarray, confidence: np.ndarray,
                 title: str, out_png: str) -> None:
    """Side-by-side true color and mask overlay (4 confidence classes)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    class_colors = {
        1: (0.0, 0.85, 1.0),   # WATER   — cyan
        2: (0.1, 0.5, 1.0),    # WATER95 — blue
        3: (0.6, 0.4, 1.0),    # WATER90 — violet
        4: (1.0, 0.55, 0.1),   # WATER80 — orange
    }
    labels = {1: "WATER (maior confiança)", 2: "WATER95", 3: "WATER90",
              4: "WATER80 (menor confiança)"}

    overlay = true_color.copy()
    for code, color in class_colors.items():
        overlay[confidence == code] = color

    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    axes[0].imshow(true_color)
    axes[0].set_title("Cor verdadeira", fontsize=11)
    axes[0].axis("off")

    axes[1].imshow(overlay)
    axes[1].set_title(f"Máscara d'água — {title}\nNamikawa et al. (2016)", fontsize=11)
    axes[1].axis("off")

    handles = [
        Patch(facecolor=class_colors[c], label=f"{labels[c]}: {(confidence == c).sum():,d} px")
        for c in (1, 2, 3, 4) if (confidence == c).any()
    ]
    if handles:
        fig.legend(handles=handles, loc="lower center", ncol=min(len(handles), 4),
                   fontsize=9, frameon=True, bbox_to_anchor=(0.5, 0.02))
    plt.tight_layout(rect=[0, 0.08, 1, 1])
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
