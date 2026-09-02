#!/usr/bin/env python3
from __future__ import annotations
import base64
import gzip
import runpy
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAYLOAD = Path(__file__).with_name('run_v34.py.gz.b64')
if not PAYLOAD.exists():
    raise SystemExit('RUNNER_NOT_READY: missing V3.4 engine payload')
raw = gzip.decompress(base64.b64decode(PAYLOAD.read_text(encoding='ascii')))
with tempfile.NamedTemporaryFile('wb', suffix='.py', delete=False) as fh:
    fh.write(raw)
    target = Path(fh.name)
runpy.run_path(str(target), run_name='__main__')
