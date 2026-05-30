from __future__ import annotations
import math
import numpy as np

from app.model.types import Move


def simulate(
    moves: list[Move],
    workpiece_x: float,
    workpiece_y: float,
    workpiece_w: float,
    workpiece_h: float,
    tool_diameter: float,
    px_per_mm: float = 2.0,
) -> np.ndarray:
    """
    Simulate material removal.

    Returns a float32 array of shape (height_px, width_px).
    Value = maximum cutting depth reached at that pixel (mm, positive).
    Zero means untouched.
    """
    width_px  = max(1, round(workpiece_w * px_per_mm))
    height_px = max(1, round(workpiece_h * px_per_mm))
    depth = np.zeros((height_px, width_px), dtype=np.float32)

    tool_r_px = max(0.5, (tool_diameter / 2.0) * px_per_mm)

    for move in moves:
        if not move.pen_down or not move.xy_move:
            continue

        # World-mm → pixel coords (Y is flipped: machine Y-up → row 0 = top)
        x1 = (move.from_pos.x - workpiece_x) * px_per_mm
        y1 = (workpiece_y + workpiece_h - move.from_pos.y) * px_per_mm
        x2 = (move.to_pos.x - workpiece_x) * px_per_mm
        y2 = (workpiece_y + workpiece_h - move.to_pos.y) * px_per_mm

        cut_depth = abs(move.to_pos.z)
        _draw_swept_circle(depth, x1, y1, x2, y2, tool_r_px, cut_depth)

    return depth


def _draw_swept_circle(
    depth: np.ndarray,
    x1: float, y1: float,
    x2: float, y2: float,
    r: float,
    cut_depth: float,
):
    """Mark all pixels within radius r of the line segment (x1,y1)–(x2,y2)."""
    h, w = depth.shape

    min_col = max(0, int(math.floor(min(x1, x2) - r)))
    max_col = min(w - 1, int(math.ceil(max(x1, x2) + r)))
    min_row = max(0, int(math.floor(min(y1, y2) - r)))
    max_row = min(h - 1, int(math.ceil(max(y1, y2) + r)))

    if min_col > max_col or min_row > max_row:
        return

    cols = np.arange(min_col, max_col + 1, dtype=np.float32) + 0.5
    rows = np.arange(min_row, max_row + 1, dtype=np.float32) + 0.5
    gc, gr = np.meshgrid(cols, rows)

    dx, dy = x2 - x1, y2 - y1
    seg_len_sq = dx * dx + dy * dy

    if seg_len_sq < 1e-6:
        dist_sq = (gc - x1) ** 2 + (gr - y1) ** 2
    else:
        t = np.clip(((gc - x1) * dx + (gr - y1) * dy) / seg_len_sq, 0.0, 1.0)
        dist_sq = (gc - (x1 + t * dx)) ** 2 + (gr - (y1 + t * dy)) ** 2

    mask = dist_sq <= r * r
    patch = depth[min_row:max_row + 1, min_col:max_col + 1]
    depth[min_row:max_row + 1, min_col:max_col + 1] = np.where(
        mask, np.maximum(patch, cut_depth), patch
    )


def depth_to_rgba(depth: np.ndarray, thickness: float) -> np.ndarray:
    """
    Convert depth map to RGBA uint8 array (H, W, 4).
    Untouched material: light tan.  Deepest cut: dark brown.
    """
    max_d = max(thickness, 1e-6)
    norm  = np.clip(depth / max_d, 0.0, 1.0)

    r = (222 * (1.0 - norm) + 61  * norm).astype(np.uint8)
    g = (184 * (1.0 - norm) + 28  * norm).astype(np.uint8)
    b = (135 * (1.0 - norm) +  2  * norm).astype(np.uint8)
    a = np.full(depth.shape, 255, dtype=np.uint8)
    return np.stack([r, g, b, a], axis=2)


def export_stl(
    path: str,
    depth: np.ndarray,
    workpiece_x: float,
    workpiece_y: float,
    workpiece_w: float,
    workpiece_h: float,
    thickness: float,
    px_per_mm: float,
):
    """
    Write a binary STL of the machined workpiece (closed solid mesh).

    Top surface follows the depth map.  Bottom is flat at z = 0.
    Side walls connect them.
    """
    import struct

    H, W = depth.shape
    step = 1.0 / px_per_mm   # mm per pixel

    # Vertex grid: (H+1) x (W+1) corner points.
    # Corner (r, c):
    #   x = workpiece_x + c * step
    #   y = workpiece_y + (H - r) * step    (Y-flip)
    #   z_top = thickness - avg depth of neighbouring pixels
    r_idx = np.arange(H + 1)
    c_idx = np.arange(W + 1)
    vx = workpiece_x + c_idx * step                        # shape (W+1,)
    vy = workpiece_y + (H - r_idx) * step                  # shape (H+1,)

    # Corner depths: average of up-to-4 neighbouring pixels
    padded = np.pad(depth, 1, mode='edge')
    corner_depth = (
        padded[0:H+1, 0:W+1] +
        padded[0:H+1, 1:W+2] +
        padded[1:H+2, 0:W+1] +
        padded[1:H+2, 1:W+2]
    ) / 4.0                                                 # shape (H+1, W+1)
    vz_top = (thickness - corner_depth).astype(np.float32)
    vz_bot = np.zeros_like(vz_top)

    # --- Build mesh using vectorised numpy operations ---

    # STL triangle dtype (50 bytes per triangle: 12 floats + 1 uint16 attr)
    _tri_dtype = np.dtype([
        ('n',  np.float32, (3,)),
        ('v1', np.float32, (3,)),
        ('v2', np.float32, (3,)),
        ('v3', np.float32, (3,)),
        ('attr', np.uint16),
    ])

    def _surface_tris(vx_grid, vy_grid, vz_grid, flip_winding: bool):
        """Vectorised quad → 2 triangles for an (H,W) pixel grid of quads."""
        # Corner coords: tl/tr/bl/br for each quad (r,c)
        Rr = np.arange(H)
        Cc = np.arange(W)
        RR, CC = np.meshgrid(Rr, Cc, indexing='ij')   # (H, W)

        def corner(r_off, c_off):
            return np.stack([
                vx_grid[CC + c_off],
                vy_grid[RR + r_off],
                vz_grid[RR + r_off, CC + c_off],
            ], axis=2).reshape(-1, 3).astype(np.float32)  # (H*W, 3)

        tl = corner(0, 0)
        tr = corner(0, 1)
        bl = corner(1, 0)
        br = corner(1, 1)

        if flip_winding:
            a1, b1, c1 = tl, br, tr
            a2, b2, c2 = tl, bl, br
        else:
            a1, b1, c1 = tl, tr, br
            a2, b2, c2 = tl, br, bl

        N = len(tl) * 2
        out = np.zeros(N, dtype=_tri_dtype)
        out['v1'][:len(tl)] = a1;  out['v2'][:len(tl)] = b1;  out['v3'][:len(tl)] = c1
        out['v1'][len(tl):] = a2;  out['v2'][len(tl):] = b2;  out['v3'][len(tl):] = c2

        e1 = out['v2'] - out['v1']
        e2 = out['v3'] - out['v1']
        n  = np.cross(e1, e2).astype(np.float32)
        ln = np.linalg.norm(n, axis=1, keepdims=True)
        ln[ln == 0] = 1.0
        out['n'] = n / ln
        return out

    # Top surface
    top_tris = _surface_tris(vx, vy, vz_top, flip_winding=False)

    # Bottom surface (flat z=0, winding reversed so normal faces down)
    vz_bot_grid = np.zeros((H + 1, W + 1), dtype=np.float32)
    bot_tris = _surface_tris(vx, vy, vz_bot_grid, flip_winding=True)

    # Side walls — vectorised, one edge at a time
    # Vertices: (x, y, z_3d) in machine coords, z_3d = remaining height
    def _edge_tris(xs, ys, zt, flip: bool) -> np.ndarray:
        """
        Build quads for one straight edge.
        xs, ys: 1-D arrays of x/y positions along the edge (length N+1).
        zt:     1-D array of top-z per vertex (length N+1).
        Returns array of 2*N triangles with dtype _tri_dtype.
        """
        N = len(xs) - 1
        tl = np.stack([xs[:-1], ys[:-1], zt[:-1]], axis=1).astype(np.float32)
        tr = np.stack([xs[1:],  ys[1:],  zt[1:]],  axis=1).astype(np.float32)
        bl = np.stack([xs[:-1], ys[:-1], np.zeros(N, np.float32)], axis=1)
        br = np.stack([xs[1:],  ys[1:],  np.zeros(N, np.float32)], axis=1)

        out = np.zeros(N * 2, dtype=_tri_dtype)
        if flip:
            out['v1'][:N] = bl; out['v2'][:N] = br; out['v3'][:N] = tr
            out['v1'][N:] = bl; out['v2'][N:] = tr; out['v3'][N:] = tl
        else:
            out['v1'][:N] = bl; out['v2'][:N] = tr; out['v3'][:N] = br
            out['v1'][N:] = bl; out['v2'][N:] = tl; out['v3'][N:] = tr

        e1 = out['v2'] - out['v1']
        e2 = out['v3'] - out['v1']
        n  = np.cross(e1, e2).astype(np.float32)
        ln = np.linalg.norm(n, axis=1, keepdims=True)
        ln[ln == 0] = 1.0
        out['n'] = n / ln
        return out

    c_range  = np.arange(W + 1)
    r_range  = np.arange(H + 1)
    xs_c     = (workpiece_x + c_range * step).astype(np.float32)
    ys_r     = (workpiece_y + (H - r_range) * step).astype(np.float32)

    wall_f = _edge_tris(xs_c,                  np.full(W+1, vy[0],  np.float32), vz_top[0,  :], flip=False)
    wall_b = _edge_tris(xs_c[::-1],            np.full(W+1, vy[H],  np.float32), vz_top[H,  :][::-1], flip=False)
    wall_l = _edge_tris(np.full(H+1, vx[0],  np.float32), ys_r[::-1], vz_top[:, 0][::-1], flip=False)
    wall_r = _edge_tris(np.full(H+1, vx[W],  np.float32), ys_r,       vz_top[:, W],        flip=False)

    all_tris = np.concatenate([top_tris, bot_tris, wall_f, wall_b, wall_l, wall_r])

    # --- Write binary STL ---
    with open(path, 'wb') as f:
        f.write(b'Mimaki simulation export' + b'\x00' * 56)   # 80-byte header
        f.write(struct.pack('<I', len(all_tris)))
        f.write(all_tris.tobytes())
