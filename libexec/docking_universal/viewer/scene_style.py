"""Display-only scene defaults, shared by embedded and full PyMOL."""
import math


SELECTED_BOX_RADIUS = 0.22


def expand_scene_clipping(cmd, extra_bounds=None):
    """Show the complete enabled scene without altering framing or a wider slab.

    PyMOL cannot literally disable depth planes. A full bounding-box diagonal
    gives a rotation-safe slab even when the origin moves within the scene.
    CGOs have no atom extent, so the caller supplies its known box bounds.
    This is an initialization/default operation, not a render-loop override.
    """
    bounds = cmd.get_extent('enabled', state=0)
    if extra_bounds is not None:
        if bounds is None:
            bounds = extra_bounds
        else:
            bounds = [[min(bounds[0][i], extra_bounds[0][i]) for i in range(3)],
                      [max(bounds[1][i], extra_bounds[1][i]) for i in range(3)]]
    if bounds is None:
        return
    camera = list(cmd.get_view())
    values = [*bounds[0], *bounds[1], *camera]
    if not all(math.isfinite(float(v)) for v in values):
        return
    diagonal = math.sqrt(sum((bounds[1][i] - bounds[0][i]) ** 2 for i in range(3)))
    outside = math.sqrt(sum(max(bounds[0][i] - camera[12+i],
                                camera[12+i] - bounds[1][i], 0) ** 2 for i in range(3)))
    radius = diagonal + outside + 6.0  # covers surface probes and stick radii
    depth = -camera[11]
    camera[15] = min(camera[15], depth - radius)
    camera[16] = max(camera[16], depth + radius)
    cmd.set_view(camera)
