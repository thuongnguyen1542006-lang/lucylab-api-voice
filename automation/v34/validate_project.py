#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess, zipfile
from pathlib import Path

RUNNER_VERSION='3.4.0'

def fail(msg:str):
    raise SystemExit(f'PROJECT_VALIDATE_FAIL: {msg}')

def load(p:Path): return json.loads(p.read_text(encoding='utf-8'))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('project_dir'); args=ap.parse_args(); root=Path(args.project_dir)
    required=[root/'final/final.mp4',root/'project.zip',root/'status.json',root/'qc-report.json',root/'qc/v34-runner-qc.json',root/'qc/source-contact-sheet.jpg',root/'qc/final-contact-sheet.jpg',root/'storyboard/locked-storyboard.json',root/'project.json']
    for p in required:
        if not p.is_file() or p.stat().st_size <= 0: fail(f'missing {p.relative_to(root)}')
    status=load(root/'status.json'); qc=load(root/'qc-report.json'); rq=load(root/'qc/v34-runner-qc.json')
    if status.get('state')!='completed': fail('status.state')
    if status.get('runnerVersion')!=RUNNER_VERSION: fail('status.runnerVersion')
    if status.get('execution')!='github-actions': fail('status.execution')
    if status.get('sourceProvider')!='chatgpt-web-image-generation': fail('status.sourceProvider')
    if status.get('requiresChatGPTVisionGate') is not True: fail('requiresChatGPTVisionGate')
    if qc.get('pass') is not True or rq.get('pass') is not True: fail('machine QC')
    if rq.get('eraserCleanupPass') is not True: fail('eraser cleanup')
    if any(int(x)!=0 for x in rq.get('transitionResidualPixels',[])): fail('transition residuals')
    scenes=sorted((root/'scenes').glob('scene-*'))
    if not scenes: fail('no scenes')
    for d in scenes:
        if not (d/'source.png').is_file(): fail(f'{d.name}/source.png')
        sq=load(d/'scene-qc.json')
        if sq.get('pass') is not True: fail(f'{d.name} scene QC')
        if float(sq.get('maskArtworkCoverage',0)) < 0.995: fail(f'{d.name} mask coverage')
        if int(sq.get('maskOverlapPixels',-1)) != 0: fail(f'{d.name} mask overlap')
        if int(sq.get('captionZoneArtworkPixels',-1)) != 0: fail(f'{d.name} caption zone')
    mp4=root/'final/final.mp4'
    cp=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(mp4)],capture_output=True,text=True)
    if cp.returncode!=0: fail('ffprobe final')
    meta=json.loads(cp.stdout); vids=[s for s in meta.get('streams',[]) if s.get('codec_type')=='video']; auds=[s for s in meta.get('streams',[]) if s.get('codec_type')=='audio']
    if not vids or vids[0].get('codec_name')!='h264' or int(vids[0].get('width',0))!=1080 or int(vids[0].get('height',0))!=1920: fail('video stream')
    if not auds or auds[0].get('codec_name')!='aac': fail('audio stream')
    cp=subprocess.run(['ffmpeg','-v','error','-i',str(mp4),'-f','null','-'])
    if cp.returncode!=0: fail('full-frame decode')
    with zipfile.ZipFile(root/'project.zip') as z:
        names=set(z.namelist())
        for name in ('final/final.mp4','status.json','qc-report.json','qc/v34-runner-qc.json','storyboard/locked-storyboard.json'):
            if name not in names: fail(f'project.zip missing {name}')
    print('validate_project: PASS')

if __name__=='__main__': main()
