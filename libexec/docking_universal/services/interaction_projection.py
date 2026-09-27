"""Local 3D-to-2D projection and readable interaction-anchor layout."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.optimize import minimize


@dataclass(frozen=True)
class InteractionAnchor:
    """A residue/contact point in the receptor coordinate frame."""

    identifier: str
    label: str
    xyz: tuple[float, float, float]
    weight: float = 1.0


@dataclass(frozen=True)
class ProjectedAnchor:
    identifier: str
    label: str
    xy: tuple[float, float]
    source_xyz: tuple[float, float, float]


def _coordinates(values: Iterable[Iterable[float]], *, name: str) -> np.ndarray:
    array = np.asarray(list(values), dtype=float)
    if array.ndim != 2 or array.shape[1] != 3 or not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite 3D coordinates")
    if array.shape[0] == 0:
        raise ValueError(f"{name} cannot be empty")
    return array


def _stable_plane(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return centroid and deterministic in-plane axes from a 3D point cloud."""
    centroid = points.mean(axis=0)
    centered = points - centroid
    if np.linalg.matrix_rank(centered) < 2:
        raise ValueError("Interaction coordinates do not define a stable 2D projection plane")
    _u, _singular, vh = np.linalg.svd(centered, full_matrices=False)
    first, second = vh[0], vh[1]
    # Eigenvectors have arbitrary signs. Orient against the first non-zero
    # coordinate so the same pose always receives the same drawing orientation.
    for axis in (first, second):
        index = int(np.argmax(np.abs(axis)))
        if axis[index] < 0:
            axis *= -1
    normal = np.cross(first, second)
    normal /= np.linalg.norm(normal)
    return centroid, first, second


def project_interaction_anchors(
    ligand_xyz: Iterable[Iterable[float]],
    anchors: Iterable[InteractionAnchor],
    *,
    scale: float = 1.0,
) -> list[ProjectedAnchor]:
    """Project receptor contacts into a ligand-centered local tangent plane.

    The ligand centroid defines the origin. PCA preserves the dominant local
    binding-site directions; it is deliberately a geometric projection, not a
    claim that the 2D image is a literal view of the molecular surface.
    """
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Projection scale must be finite and positive")
    ligand = _coordinates(ligand_xyz, name="ligand_xyz")
    anchor_list = list(anchors)
    if not anchor_list:
        return []
    contact_points = _coordinates((anchor.xyz for anchor in anchor_list), name="anchor xyz")
    frame_points = np.vstack((ligand, contact_points))
    centroid, first, second = _stable_plane(frame_points)
    projected = (contact_points - ligand.mean(axis=0)) @ np.vstack((first, second)).T * scale
    return [ProjectedAnchor(
        identifier=anchor.identifier, label=anchor.label,
        xy=(float(point[0]), float(point[1])), source_xyz=anchor.xyz,
    ) for anchor, point in zip(anchor_list, projected)]


def optimize_anchor_layout(
    anchors: Iterable[ProjectedAnchor],
    *,
    min_separation: float = 2.4,
    displacement_weight: float = 1.0,
    iterations: int = 250,
) -> list[ProjectedAnchor]:
    """Spread overlapping labels while softly preserving projected positions."""
    values = list(anchors)
    if not values:
        return []
    if min_separation <= 0 or displacement_weight <= 0 or iterations < 1:
        raise ValueError("Layout parameters must be positive")
    initial = np.asarray([anchor.xy for anchor in values], dtype=float)
    if not np.isfinite(initial).all():
        raise ValueError("Projected anchors must contain finite coordinates")

    def objective(flat: np.ndarray) -> float:
        points = flat.reshape((-1, 2))
        displacement = displacement_weight * np.sum((points - initial) ** 2)
        overlap = 0.0
        for index in range(len(points)):
            for other in range(index):
                distance = float(np.linalg.norm(points[index] - points[other]))
                overlap += max(0.0, min_separation - distance) ** 2
        return displacement + 8.0 * overlap

    result = minimize(
        objective, initial.ravel(), method="L-BFGS-B",
        options={"maxiter": int(iterations), "ftol": 1e-10},
    )
    # A failed optimization is not allowed to fabricate a layout. The PCA
    # projection remains a valid, deterministic fallback for unusual geometry.
    points = result.x.reshape((-1, 2)) if np.isfinite(result.x).all() else initial
    return [ProjectedAnchor(
        identifier=anchor.identifier, label=anchor.label,
        xy=(float(point[0]), float(point[1])), source_xyz=anchor.source_xyz,
    ) for anchor, point in zip(values, points)]


def project_and_optimize(
    ligand_xyz: Iterable[Iterable[float]],
    anchors: Iterable[InteractionAnchor],
    *,
    scale: float = 1.0,
    min_separation: float = 2.4,
) -> list[ProjectedAnchor]:
    """Convenience entry point used by the 2D renderer."""
    return optimize_anchor_layout(
        project_interaction_anchors(ligand_xyz, anchors, scale=scale),
        min_separation=min_separation,
    )
