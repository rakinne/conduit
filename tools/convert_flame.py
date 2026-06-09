#!/usr/bin/env python3
"""
convert_flame.py — FLAME 2023 Open -> head_data.js for conduit

Pipeline:
 1. Load flame2023_Open.pkl (chumpy shim for legacy array wrappers)
 2. Find connected components; separate head from the two eyeballs
 3. Solve 5 identity beta vectors by least squares against target
    craniofacial metric profiles (so the forms are deliberately
    distinct, not random draws)
 4. Bake identity vertex sets from shapedirs[:, :, :300]
 5. Strip eyeball geometry, reindex, record per-identity eye centroids
    + radii and a mouth anchor for the void-eye / mouth-slit props
 6. Normalize to scene scale, cylindrical UV unwrap with seam fix
 7. Generate 2 chaos noise targets (x-biased smear, face-weighted)
 8. Emit head_data.js: base64 Float32/Uint16 buffers + rig JSON

Usage: python3 tools/convert_flame.py assets/flame2023_Open.pkl
License note: FLAME 2023 Open is CC-BY-4.0 (cite Li et al., SIGGRAPH
Asia 2017). The pkl itself is gitignored; derived head_data.js ships.
"""
import base64
import hashlib
import json
import sys

import numpy as np

from flame_io import load_flame   # shared chumpy-shim FLAME loader (RI-003)

N_SHAPE = 300          # identity components (last 100 are expression)
N_IDENTITIES = 5
BETA_CLIP = 3.0        # stay within +/-3 std of the shape space
SCENE_HEIGHT = 2.05    # world units chin..crown, matches procedural head

# ------------------------------------------------- connected components
def components(n_verts, faces):
    parent = np.arange(n_verts)
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for tri in faces:
        a = find(tri[0])
        for v in tri[1:]:
            b = find(v)
            parent[b] = a
    roots = np.array([find(i) for i in range(n_verts)])
    labels = {r: i for i, r in enumerate(np.unique(roots))}
    return np.array([labels[r] for r in roots])

# -------------------------------------------------- craniofacial metrics
def metrics(v, head_mask):
    """Measure a baked head. v: (5023,3). Returns metric vector."""
    h = v[head_mask]
    ymin, ymax = h[:, 1].min(), h[:, 1].max()
    yr = ymax - ymin
    def band(lo, hi):
        return h[(h[:, 1] > ymin + lo * yr) & (h[:, 1] < ymin + hi * yr)]
    cheek = band(0.45, 0.60)      # mid-face width band
    jaw   = band(0.15, 0.30)      # jaw width band
    front = h[h[:, 2] > h[:, 2].max() - 0.02]   # nose tip region
    return np.array([
        yr,                                   # face length
        cheek[:, 0].max() - cheek[:, 0].min(),# cheek width
        jaw[:, 0].max() - jaw[:, 0].min(),    # jaw width
        h[:, 2].max(),                        # nose protrusion
        h[:, 2].max() - h[:, 2].min(),        # head depth
    ])

def solve_identities(v_template, shapedirs, head_mask):
    """Least-squares betas hitting 5 distinct metric profiles."""
    base_m = metrics(v_template, head_mask)
    n_pc = 20  # leading PCs carry the gross skull variation
    # finite-difference metric gradient per PC
    G = np.zeros((len(base_m), n_pc))
    for i in range(n_pc):
        beta = np.zeros(N_SHAPE); beta[i] = 2.0
        v = v_template + shapedirs[:, :, :N_SHAPE] @ beta
        G[:, i] = (metrics(v, head_mask) - base_m) / 2.0
    # target profiles: relative change per metric
    #            len    cheek   jaw    nose   depth
    profiles = {
        '01 \u00b7 MONOLITH': [-0.04,  0.14,  0.17,  0.08,  0.05],
        '02 \u00b7 BLADE':    [ 0.11, -0.09, -0.14,  0.22, -0.02],
        '03 \u00b7 ORB':      [-0.09,  0.11,  0.05, -0.12,  0.04],
        '04 \u00b7 WRAITH':   [ 0.14, -0.16, -0.19,  0.13, -0.07],
        '05 \u00b7 TITAN':    [ 0.05,  0.18,  0.22,  0.16,  0.08],
    }
    out = []
    for name, rel in profiles.items():
        target = base_m * np.array(rel)
        beta_lead, *_ = np.linalg.lstsq(G, target, rcond=None)
        beta_lead = np.clip(beta_lead, -BETA_CLIP, BETA_CLIP)
        beta = np.zeros(N_SHAPE)
        beta[:n_pc] = beta_lead
        # sprinkle mid-band character so faces differ beyond gross metrics.
        # Seed from a STABLE hash of the name: Python's built-in hash() of a str
        # is salted per process (PYTHONHASHSEED), which made the bake — and the
        # committed head_data.js — non-reproducible. sha256 is process-independent
        # so re-running the converter is byte-stable (RI-001).
        seed = int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "big")
        rng = np.random.default_rng(seed)
        beta[n_pc:60] = np.clip(rng.normal(0, 0.9, 60 - n_pc), -2, 2)
        out.append((name, beta))
    return out

# ----------------------------------------------------------------- UVs
def cylindrical_uv_with_seam_fix(verts, faces, deltas, orig):
    """Cylindrical unwrap around Y. Triangles crossing the u-seam get
    duplicated vertices so the texture doesn't smear across the back.
    deltas: list of (n,3) arrays duplicated consistently.
    orig: (n,) original-FLAME vertex index per vertex, kept in sync."""
    x, y, z = verts[:, 0], verts[:, 1], verts[:, 2]
    u = np.arctan2(x, z) / (2 * np.pi) + 0.5          # seam at back (z<0,x~0)
    v = (y - y.min()) / (y.max() - y.min())
    verts = verts.copy(); faces = faces.copy()
    u = u.copy(); v = v.copy()
    deltas = [d.copy() for d in deltas]
    orig = orig.copy()
    dup_cache = {}
    def dup(idx, shift):
        key = (idx, shift)
        if key in dup_cache:
            return dup_cache[key]
        nonlocal verts, u, v, deltas, orig
        verts = np.vstack([verts, verts[idx][None]])
        u = np.append(u, u[idx] + shift)
        v = np.append(v, v[idx])
        orig = np.append(orig, orig[idx])
        for i in range(len(deltas)):
            deltas[i] = np.vstack([deltas[i], deltas[i][idx][None]])
        dup_cache[key] = len(verts) - 1
        return dup_cache[key]
    for fi, tri in enumerate(faces):
        us = u[tri]
        if us.max() - us.min() > 0.5:               # crosses the seam
            for c in range(3):
                if u[tri[c]] < 0.5:
                    faces[fi, c] = dup(tri[c], 1.0) # unwrap past 1.0
    return verts, faces, u, v, deltas, orig

# ---------------------------------------------------------------- main
def main(pkl_path):
    d = load_flame(pkl_path)
    v_t = np.asarray(d['v_template'], np.float64)
    faces = np.asarray(d['f'], np.int64)
    shapedirs = np.asarray(d['shapedirs'], np.float64)

    comp = components(len(v_t), faces)
    sizes = [(c, (comp == c).sum()) for c in np.unique(comp)]
    sizes.sort(key=lambda t: -t[1])
    print('components:', sizes)
    head_c = sizes[0][0]
    eye_cs = [c for c, _ in sizes[1:3]]
    head_mask = comp == head_c
    eye_masks = [comp == c for c in eye_cs]
    # order eyeballs L(-x), R(+x)
    eye_masks.sort(key=lambda m: v_t[m][:, 0].mean())

    identities = solve_identities(v_t, shapedirs, head_mask)

    baked, eye_rigs = [], []
    for name, beta in identities:
        v = v_t + shapedirs[:, :, :N_SHAPE] @ beta
        baked.append(v)
        rig = {}
        for label, m in zip(('L', 'R'), eye_masks):
            c = v[m].mean(axis=0)
            r = float(np.linalg.norm(v[m] - c, axis=1).mean())
            rig[label] = {'c': c, 'r': r}
        # mouth anchor: front-most band ~32% up from chin toward eyes.
        # Use only forward-facing vertices so the neck (which hangs
        # lower and further back than the chin) can't pollute either
        # the chin estimate or the band's depth.
        h = v[head_mask]
        zmax = h[:, 2].max()
        front = h[(h[:, 2] > 0.45 * zmax) & (np.abs(h[:, 0]) < 0.04)]
        chin_y = front[:, 1].min()
        eye_y = (rig['L']['c'][1] + rig['R']['c'][1]) / 2
        my = chin_y + 0.32 * (eye_y - chin_y)
        band = front[np.abs(front[:, 1] - my) < 0.006]
        mz = band[:, 2].max() if len(band) else zmax * 0.9
        rig['mouth'] = np.array([0.0, my, mz])
        eye_rigs.append((name, rig))
        print(f"{name}: betas[:6]={np.round(beta[:6],2)} "
              f"eyeR_r={rig['R']['r']:.4f}")

    # ---- strip eyeballs, reindex ----------------------------------
    keep = head_mask
    new_idx = -np.ones(len(v_t), np.int64)
    new_idx[keep] = np.arange(keep.sum())
    face_keep = keep[faces].all(axis=1)
    faces_h = new_idx[faces[face_keep]]
    base = baked[0][keep]                       # identity 0 is the base
    target_deltas = [b[keep] - base for b in baked[1:]]  # 4 deltas vs base
    print(f"head mesh: {len(base)} verts, {len(faces_h)} faces")

    # ---- normalize: center between eyes-ish, scale to scene -------
    rig0 = eye_rigs[0][1]
    eye_mid = (rig0['L']['c'] + rig0['R']['c']) / 2
    h0 = base
    span = h0[:, 1].max() - h0[:, 1].min()
    scale = SCENE_HEIGHT / span
    center = np.array([eye_mid[0],
                       (h0[:, 1].max() + h0[:, 1].min()) / 2,
                       eye_mid[2] * 0.25])
    base_n = (base - center) * scale
    target_deltas = [td * scale for td in target_deltas]
    def xf(p): return (np.asarray(p) - center) * scale
    rigs_json = []
    for name, rig in eye_rigs:
        rigs_json.append({
            'name': name,
            'eyeL': {'c': xf(rig['L']['c']).round(4).tolist(),
                     'r': round(rig['L']['r'] * scale, 4)},
            'eyeR': {'c': xf(rig['R']['c']).round(4).tolist(),
                     'r': round(rig['R']['r'] * scale, 4)},
            'mouth': xf(rig['mouth']).round(4).tolist(),
        })

    # ---- chaos noise targets (deltas over base) --------------------
    def chaos(seed):
        x, y, z = base_n[:, 0], base_n[:, 1], base_n[:, 2]
        n1 = np.sin(x * 9 + seed) * np.cos(y * 7 + seed * 1.7) * np.sin(z * 8 + x * 3)
        dx = np.sin(y * 11 + seed) * 0.10 + n1 * 0.06
        dy = n1 * 0.045
        dz = np.cos(x * 8 + seed * 2) * 0.06 * np.clip(z, 0, None)
        return np.stack([dx, dy, dz], axis=1)
    all_deltas = target_deltas + [chaos(1.3), chaos(7.8)]

    # ---- UVs with seam duplication (applies to all delta sets) -----
    orig_idx = np.where(keep)[0]                 # original FLAME index per vert
    verts_f, faces_f, u, v, all_deltas, orig_idx = cylindrical_uv_with_seam_fix(
        base_n, faces_h, all_deltas, orig_idx)
    print(f"after seam fix: {len(verts_f)} verts "
          f"(+{len(verts_f)-len(base_n)} duplicated)")
    assert len(verts_f) < 65536, "indices must fit Uint16"

    # ---- emit ------------------------------------------------------
    def b64(arr, dtype):
        return base64.b64encode(
            np.ascontiguousarray(arr, dtype=dtype).tobytes()).decode()
    payload = {
        'count': len(verts_f),
        'pos': b64(verts_f.ravel(), np.float32),
        'uv': b64(np.stack([u, v], 1).ravel(), np.float32),
        'idx': b64(faces_f.ravel(), np.uint16),
        'targets': [b64(d.ravel(), np.float32) for d in all_deltas],
        'origIdx': b64(orig_idx, np.uint16),
        'xform': {'center': center.round(6).tolist(),
                  'scale': round(float(scale), 6)},
        'rigs': rigs_json,
        'meta': {'source': 'FLAME 2023 Open (CC-BY-4.0), Li et al. 2017',
                 'identities': [n for n, _ in identities],
                 'chaosTargets': 2,
                 'note': 'targets are deltas vs base (= identity 0); '
                         'morphTargetsRelative'}
    }
    js = ('// generated by tools/convert_flame.py — do not edit\n'
          '// derived from FLAME 2023 Open, CC-BY-4.0, '
          'https://flame.is.tue.mpg.de\n'
          'const HEAD_DATA = ' + json.dumps(payload) + ';\n')
    with open('head_data.js', 'w') as f:
        f.write(js)
    print(f"head_data.js written: {len(js)/1024:.0f} KB")

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'assets/flame2023_Open.pkl')
