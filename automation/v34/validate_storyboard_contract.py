#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

RUNNER_VERSION='3.4.0'
S3={'top','mid','bottom'}
S4={'tl','tr','bl','br'}

def fail(msg:str):
    raise SystemExit(f'STORYBOARD_CONTRACT_FAIL: {msg}')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('path'); args=ap.parse_args()
    p=Path(args.path); data=json.loads(p.read_text(encoding='utf-8')); job=data.get('job',data)
    if str(job.get('runnerVersion')) != RUNNER_VERSION: fail('runnerVersion')
    if int(job.get('schemaVersion',0)) != 4: fail('schemaVersion')
    if job.get('stage') != 'production': fail('stage')
    sb=job.get('storyboard') or {}
    if sb.get('locked') is not True: fail('storyboard.locked')
    if not isinstance(sb.get('revision'),int) or sb['revision'] < 1: fail('storyboard.revision')
    pages=sb.get('pages') or []
    if not pages: fail('no pages')
    seen=set()
    for i,page in enumerate(pages,1):
        els=page.get('elements') or []
        if len(els) not in (3,4): fail(f'page {i} element count')
        slots={str(e.get('slot')) for e in els}; exp=S3 if len(els)==3 else S4
        if slots != exp: fail(f'page {i} slots {slots}')
        if page.get('sourceMethod') != 'chatgpt-web-image-generation': fail(f'page {i} sourceMethod')
        if not str(page.get('sourcePath','')).strip(): fail(f'page {i} sourcePath')
        if int(page.get('startCue',0)) < 1 or int(page.get('endCue',0)) < int(page.get('startCue',0)): fail(f'page {i} cue range')
        vqc=page.get('sourceVisualQc') or {}
        for k in ('approvedSketchStyle','notFlatVectorOrClipart','organicLineTexture','believableObjectDetail'):
            if vqc.get(k) is not True: fail(f'page {i} sourceVisualQc.{k}')
        if page.get('containsCharacter') and vqc.get('matchesCharacterStyle') is not True: fail(f'page {i} character QC')
        seq=[]
        for e in els:
            eid=str(e.get('id',''))
            if not eid or eid in seen: fail(f'duplicate/missing element id {eid!r}')
            seen.add(eid); seq.append(int(e.get('sequence',0)))
            for k in ('label','narrativeRole','anchorText','visualWhy','mustRenderAs'):
                if not str(e.get(k,'')).strip(): fail(f'{eid} missing {k}')
            fs=e.get('forbiddenSubstitutions')
            if not isinstance(fs,list) or not fs: fail(f'{eid} forbiddenSubstitutions')
            box=e.get('box')
            if not isinstance(box,list) or len(box)!=4: fail(f'{eid} box')
            start,end=int(e.get('startMs',-1)),int(e.get('endMs',-1))
            if not (0 <= start < end): fail(f'{eid} timing')
        if seq != sorted(seq) or len(set(seq)) != len(seq): fail(f'page {i} sequence')
        if i < len(pages) and int(page.get('eraseMs',0)) <= 0: fail(f'page {i} eraseMs')
        if i == len(pages) and int(page.get('eraseMs',0)) != 0: fail('last page eraseMs')
    print('validate_storyboard_contract: PASS')

if __name__=='__main__': main()
