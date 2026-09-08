#!/usr/bin/env python3
from __future__ import annotations
import hashlib, importlib.util, json, os, re, subprocess, time, urllib.error
from pathlib import Path

VOICE_ID='vobfq29MDccJJPpsVLHZxV'

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def fingerprint(scene): return hashlib.sha256(json.dumps({'text':scene['text'],'voiceAlias':'co-nhan','speed':1.0},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def safe_id(v):
    if not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,100}',v): raise ValueError('Invalid id')
    return v
def write_json(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); tmp.replace(path)
def load_bridge(root):
    p=root/'automation/lucylab_bridge.py'; spec=importlib.util.spec_from_file_location('lucylab_bridge',p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m,digest(p)
def safe_download(bridge,url,path):
    last=None
    for attempt in range(4):
        try: bridge.download(url,path); return
        except Exception as e:
            last=e
            if attempt<3: time.sleep(2**attempt)
    raise last

def main():
    root=Path(__file__).resolve().parents[2]
    resume_paths=json.loads(Path('resume_requests.json').read_text())
    key=os.environ.get('LUCYLAB_API_KEY','').strip()
    if not key: raise SystemExit('Missing LUCYLAB_API_KEY')
    bridge,bridge_hash=load_bridge(root)
    for rp in resume_paths:
        resume=json.loads((root/rp).read_text(encoding='utf-8'))
        request=json.loads((root/resume['requestPath']).read_text(encoding='utf-8'))
        if request.get('bridgeSha256')!=bridge_hash or request.get('voiceAlias')!='co-nhan' or request.get('voiceSpeed')!=1.0: raise ValueError('Request contract mismatch')
        jobid=safe_id(request['jobId']); dest=Path('tts_output')/jobid; write_json(dest/'request.json',request)
        metadata={'jobId':jobid,'githubRunId':os.environ.get('GITHUB_RUN_ID'),'githubRunAttempt':os.environ.get('GITHUB_RUN_ATTEMPT'),'githubCommit':os.environ.get('GITHUB_SHA'),'bridgeSha256':bridge_hash}
        if int(os.environ.get('GITHUB_RUN_ATTEMPT','1'))!=1: raise RuntimeError('Do not rerun resume jobs')
        resume_map=resume.get('resumeExportIds',{})
        results=[]
        for scene in request['scenes']:
            sid=safe_id(scene['sceneId']); folder=dest/sid; folder.mkdir(parents=True,exist_ok=True)
            fp=fingerprint(scene); export_id=str(resume_map.get(sid) or '')
            state={**metadata,'sceneId':sid,'fingerprint':fp,'voiceAlias':'co-nhan','voiceId':VOICE_ID,'speed':1.0,'state':'polling' if export_id else 'creation-pending'}
            if export_id: state['projectExportId']=export_id
            write_json(folder/'tts.json',state)
            if not export_id:
                created=bridge.rpc('ttsLongText',{'text':scene['text'],'userVoiceId':VOICE_ID,'speed':1.0},key,retries=1)
                export_id=str(created.get('projectExportId') or '')
                if not export_id: raise RuntimeError('TTS_CREATION_UNCERTAIN')
                state.update(state='polling',projectExportId=export_id); write_json(folder/'tts.json',state)
            deadline=time.monotonic()+900
            while time.monotonic()<deadline:
                status=bridge.rpc('getExportStatus',{'projectExportId':export_id},key,retries=3)
                if status.get('state')=='failed': raise RuntimeError(f'LucyLab export failed: {sid}')
                if status.get('state')=='completed':
                    if not status.get('url') or not status.get('srtUrl'): raise RuntimeError('Completed export missing URLs')
                    safe_download(bridge,status['url'],folder/'voice.wav'); safe_download(bridge,status['srtUrl'],folder/'subtitles.original.srt')
                    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(folder/'voice.wav')]))
                    duration=round(float(probe['format']['duration'])*1000)
                    subprocess.run(['ffmpeg','-v','error','-i',str(folder/'voice.wav'),'-f','null','-'],check=True)
                    state.update(state='completed',durationMs=duration,mediaFormat=probe['format']['format_name'],files={n:digest(folder/n) for n in ['voice.wav','subtitles.original.srt']}); write_json(folder/'tts.json',state); results.append(state); break
                time.sleep(2.5)
            else: raise TimeoutError(f'Polling timed out: {sid}')
        write_json(dest/'timing.json',{'schemaVersion':4,**metadata,'scenes':results})

if __name__=='__main__': main()
