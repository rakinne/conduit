#!/usr/bin/env python3
"""
make_templates.py — synthesize vocaset/templates.pkl for FaceFormer

FaceFormer's demo expects vocaset/templates.pkl: a dict mapping VOCASET
subject names to neutral (5023, 3) head meshes. That file normally comes
from registering for VOCASET. For conduit's pipeline it isn't needed:
FaceFormer outputs template + motion, and tools/bake_anim.py takes
deltas vs frame 0, so the template cancels exactly. Any FLAME-topology
neutral head therefore works — we use the FLAME 2023 Open mean head.

Usage:
  python3 tools/make_templates.py assets/flame2023_Open.pkl templates.pkl
Then copy templates.pkl to FaceFormer/vocaset/templates.pkl
"""
import pickle
import sys

import numpy as np

from flame_io import load_flame   # shared chumpy-shim FLAME loader (RI-003)

SUBJECTS = [
    # train
    'FaceTalk_170728_03272_TA', 'FaceTalk_170904_00128_TA',
    'FaceTalk_170725_00137_TA', 'FaceTalk_170915_00223_TA',
    'FaceTalk_170811_03274_TA', 'FaceTalk_170913_03279_TA',
    'FaceTalk_170904_03276_TA', 'FaceTalk_170912_03278_TA',
    # val
    'FaceTalk_170811_03275_TA', 'FaceTalk_170908_03277_TA',
    # test
    'FaceTalk_170809_00138_TA', 'FaceTalk_170731_00024_TA',
]


def main(flame_pkl, out_path):
    d = load_flame(flame_pkl)
    v = np.asarray(d['v_template'], np.float64)
    assert v.shape == (5023, 3), v.shape
    templates = {name: v for name in SUBJECTS}
    with open(out_path, 'wb') as f:
        pickle.dump(templates, f, protocol=2)
    print(f"{out_path}: {len(SUBJECTS)} subjects -> FLAME mean head {v.shape}")


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'assets/flame2023_Open.pkl',
         sys.argv[2] if len(sys.argv) > 2 else 'templates.pkl')
