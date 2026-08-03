"""Pinta el trazado del circuito por sectores según deltas.
Genera un PNG con la línea del circuito coloreada: rojo = pierdes, verde = ganas,
intensidad proporcional al delta. El S1 empieza en la bandera de meta detectada.
"""
import io

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.ndimage import binary_dilation
from skimage import measure
from skimage.morphology import skeletonize

_RADIUS = 4  # grosor de la banda pintada (dilatación del trazado original)


def _extract_axis(arr: np.ndarray):
    """Devuelve (band, order): máscara de la banda del trazado y polilínea ordenada del eje."""
    h, w, _ = arr.shape
    r = arr[:, :, 0].astype(int)
    g = arr[:, :, 1].astype(int)
    b = arr[:, :, 2].astype(int)

    mask = (r > 150) & (g < 120) & (b < 120)

    # Componentes grandes (quitar ruido de curvas grises)
    labeled, n = ndimage.label(mask)
    sizes = ndimage.sum(mask, labeled, range(1, n + 1))
    big_labels = [i + 1 for i, s in enumerate(sizes) if s > 300]
    clean = np.isin(labeled, big_labels)

    # Dilatar para cerrar huecos (números de curva, bandera)
    struct = np.ones((2 * _RADIUS + 1, 2 * _RADIUS + 1), dtype=bool)
    dilated = binary_dilation(clean, structure=struct)
    labeled2, n2 = ndimage.label(dilated)
    sizes2 = ndimage.sum(dilated, labeled2, range(1, n2 + 1))
    big2 = [i + 1 for i, s in enumerate(sizes2) if s > 1000]
    band = np.isin(labeled2, big2)

    # Skeleton = línea central
    skel = skeletonize(band)
    skel_pts = np.argwhere(skel)

    # Grafo de vecindad y poda de hojas -> ciclo principal
    from scipy.spatial import cKDTree
    tree = cKDTree(skel_pts)
    pairs = tree.query_pairs(r=3.0)
    adj = {i: set() for i in range(len(skel_pts))}
    for a, b in pairs:
        adj[a].add(b)
        adj[b].add(a)

    deg = {i: len(adj[i]) for i in range(len(skel_pts))}
    leaf_q = [i for i, d in deg.items() if d <= 1]
    in_cycle = set(range(len(skel_pts)))
    while leaf_q:
        i = leaf_q.pop()
        if i not in in_cycle:
            continue
        in_cycle.discard(i)
        for j in adj[i]:
            if j in in_cycle:
                deg[j] -= 1
                if deg[j] <= 1:
                    leaf_q.append(j)

    if not in_cycle:
        return band, np.empty((0, 2))

    cycle_idx = sorted(in_cycle)
    adj2 = {i: [j for j in adj[i] if j in in_cycle] for i in cycle_idx}
    start = next(iter(in_cycle))
    # Recorrido greedy: siempre al vecino NO visitado más cercano (geométricamente continuo).
    # Un DFS con stack salta (backtracking) y rompe el camino; aquí seguimos la línea.
    order_idx = [start]
    visited = {start}
    prev = start
    while len(order_idx) < len(in_cycle):
        best, best_d = None, None
        for j in adj2[prev]:
            if j not in visited:
                d2 = (skel_pts[prev][0] - skel_pts[j][0]) ** 2 + (skel_pts[prev][1] - skel_pts[j][1]) ** 2
                if best_d is None or d2 < best_d:
                    best, best_d = j, d2
        if best is None:
            # callejón sin salida: saltar al no visitado más cercano en global
            best = min((i for i in in_cycle if i not in visited),
                       key=lambda i: (skel_pts[prev][0] - skel_pts[i][0]) ** 2 + (skel_pts[prev][1] - skel_pts[i][1]) ** 2)
        order_idx.append(best)
        visited.add(best)
        prev = best
    order = skel_pts[order_idx]
    return band, order


def _detect_flag(arr: np.ndarray, band: np.ndarray):
    """Posición (y, x) de la bandera de cuadros: cuadros negros pequeños dentro de la banda."""
    h, w, _ = arr.shape
    r = arr[:, :, 0].astype(int)
    g = arr[:, :, 1].astype(int)
    b = arr[:, :, 2].astype(int)
    black = (r < 80) & (g < 80) & (b < 80)
    flab, fn = ndimage.label(black)
    cells = []
    for i in range(1, fn + 1):
        size = (flab == i).sum()
        if 2 <= size <= 25:
            pts = np.argwhere(flab == i)
            if band[pts[:, 0], pts[:, 1]].all():
                cells.append(pts.mean(axis=0))
    if cells:
        fc = np.array(cells)
        return fc.mean(axis=0)
    return None


def _sector_colors(deltas_ms):
    """Colores por sector: rojo si delta>0 (pierdes), verde si <0 (ganas). Intensidad ∝ |delta|."""
    maxd = max(abs(d) for d in deltas_ms) if deltas_ms else 1
    colors = []
    for d in deltas_ms:
        t = abs(d) / maxd if maxd else 0
        if d > 0:
            colors.append((255, int(140 * (1 - t)), int(140 * (1 - t))))
        else:
            colors.append((int(60 * (1 - t)), 255, int(60 * (1 - t))))
    return colors


def paint_trackmap(trackmap_bytes: bytes, deltas_ms, sector_times_ms) -> bytes:
    """trackmap_bytes: PNG del circuito. Devuelve PNG coloreado por sectores."""
    arr = np.array(Image.open(io.BytesIO(trackmap_bytes)).convert('RGB'))
    h, w, _ = arr.shape
    orig = arr.copy()

    band, order = _extract_axis(arr)
    if len(order) < 50:
        raise ValueError('Trazado no detectado en el mapa')

    # Bandera de meta -> inicio del S1
    flag = _detect_flag(arr, band)
    if flag is not None:
        fy, fx = flag
    else:
        fy, fx = h / 2, w / 2

    start_i = min(range(len(order)), key=lambda i: (order[i][0] - fy) ** 2 + (order[i][1] - fx) ** 2)
    order = np.roll(order, -start_i, axis=0)

    # Longitud acumulada
    d = np.diff(order, axis=0)
    seg_len = np.sqrt((d ** 2).sum(axis=1))
    cum = np.concatenate([[0], np.cumsum(seg_len)])
    total = cum[-1]

    # Sectores proporcionales a la duración real
    n_sectors = len(deltas_ms)
    if len(sector_times_ms) != n_sectors or total <= 0:
        raise ValueError('deltas y sector_times deben tener la misma longitud')
    total_ms = sum(sector_times_ms)
    fracs = np.cumsum([t / total_ms for t in sector_times_ms])
    sector_of = np.zeros(len(order), dtype=int)
    for i, frac in enumerate(fracs[:-1]):
        idx = int(np.searchsorted(cum, frac * total))
        sector_of[idx:] = i + 1

    # Voronoi: cada píxel de la banda toma el sector del eje más cercano
    labels_img = np.zeros((h, w), dtype=np.uint8)
    for i, (y, x) in enumerate(order):
        yi, xi = int(round(y)), int(round(x))
        if 0 <= yi < h and 0 <= xi < w:
            labels_img[yi, xi] = sector_of[i] + 1
    axis_mask = labels_img > 0
    _, inds = ndimage.distance_transform_edt(~axis_mask, return_indices=True)
    nearest = labels_img[inds[0], inds[1]]
    band_sector = np.where(band, nearest, 0)

    colors = _sector_colors(deltas_ms)

    out = arr.copy()
    out[band] = (235, 235, 235)
    for s in range(1, n_sectors + 1):
        out[band_sector == s] = colors[s - 1]

    # Restaurar etiquetas amarillas y números negros (texto legible)
    r = orig[:, :, 0].astype(int)
    g = orig[:, :, 1].astype(int)
    b = orig[:, :, 2].astype(int)
    labels_mask = ((r > 190) & (g > 130) & (b < 130)) | ((r < 90) & (g < 90) & (b < 90))
    restore = labels_mask & band
    out[restore] = orig[restore]

    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format='PNG')
    return buf.getvalue()
