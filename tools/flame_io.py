#!/usr/bin/env python3
"""
flame_io.py — shared FLAME .pkl loader for conduit's offline bake tools.

The FLAME 2023 pkl wraps some arrays in legacy `chumpy` objects and was pickled
under Python 2 (latin1). Both `convert_flame.py` and `make_templates.py` need to
load it the same way; this is the single home for that shim so the chumpy unwrap
can't drift between them (RI-003). Kept separate from `ff_compat`-style concerns:
this is FLAME pkl I/O only, no grab-bag utils.
"""
import pickle
import sys
import types

import numpy as np


def load_flame(path):
    """Load a FLAME .pkl into a dict of plain numpy arrays (chumpy unwrapped)."""
    class Ch:
        def __init__(self, *a, **k): pass
        def __setstate__(self, state):
            self.__dict__.update(state if isinstance(state, dict) else {})
    mod = types.ModuleType('chumpy'); mod.Ch = Ch
    chm = types.ModuleType('chumpy.ch'); chm.Ch = Ch
    mod.ch = chm
    sys.modules.update({'chumpy': mod, 'chumpy.ch': chm, 'chumpy.ch_ops': chm})
    with open(path, 'rb') as f:
        d = pickle.load(f, encoding='latin1')
    def unwrap(v):
        if isinstance(v, Ch):
            for key in ('x', 'a', 'v'):
                if hasattr(v, key):
                    return np.asarray(getattr(v, key))
        return v
    return {k: unwrap(v) for k, v in d.items()}
