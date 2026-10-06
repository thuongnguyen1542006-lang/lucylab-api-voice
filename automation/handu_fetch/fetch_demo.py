import json, sys, subprocess
from pathlib import Path
from urllib.parse import urlparse
import requests

SRC = sys.argv[1]
OUT = Path("handu_fetch_output")
OUT.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36"

s = requests.Session()
demo = s.get("https://demo.douyin.wtf/api/v1/auth/demo", timeout=30)
demo.raise_for_status()
dj = demo.json()
password = ((dj.get("data") or {}).get("password") if isinstance(dj,dict) else None)
if not password:
    raise RuntimeError("Demo password missing")

login = s.post("https://demo.douyin.wtf/api/v1/auth/login",
               json={"username":"demo","password":password},
               headers={"content-type":"application/json","user-agent":UA},
               timeout=30)
(OUT/"demo_login_status.txt").write_text(f"{login.status_code}\n{login.text[:500]}\n",encoding="utf-8")
login.raise_for_status()

resp = s.post("https://demo.douyin.wtf/api/v1/parse?wait=25",
              json={"url":SRC},
              headers={"content-type":"application/json","user-agent":UA},
              timeout=40)
(OUT/"demo_parse_status.txt").write_text(f"{resp.status_code}\n",encoding="utf-8")
(OUT/"demo_parse_raw.txt").write_text(resp.text,encoding="utf-8",errors="ignore")
resp.raise_for_status()
obj = resp.json()
(OUT/"demo_parse.json").write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")

cands=[]
def add(url, hdrs=None, path="$"):
    if not isinstance(url,str) or not url.startswith(("http://","https://")):
        return
    host=urlparse(url).netloc.lower()
    score=0
    low=url.lower()
    for term,w in [(".mp4",50),("video",25),("play",20),("download",20),("douyinvod",40),("zjcdn",35),("byte",15),("aweme",10)]:
        if term in low or term in host:
            score += w
    if any(x in low for x in (".jpg",".jpeg",".png",".webp","cover","avatar")):
        score -= 80
    cands.append((score,url,hdrs or {},path))

def walk(x,path="$"):
    if isinstance(x,dict):
        hdr=x.get("headers") if isinstance(x.get("headers"),dict) else {}
        for k,v in x.items():
            p=path+"."+str(k)
            if isinstance(v,str) and v.startswith(("http://","https://")):
                add(v,hdr,p)
            else:
                walk(v,p)
    elif isinstance(x,list):
        for i,v in enumerate(x):
            walk(v,f"{path}[{i}]")

walk(obj)
seen=set(); ranked=[]
for score,url,hdr,path in sorted(cands,key=lambda x:x[0],reverse=True):
    if url in seen: continue
    seen.add(url); ranked.append((score,url,hdr,path))
(OUT/"demo_candidates.json").write_text(json.dumps([{"score":a,"url":b,"headers":c,"path":d} for a,b,c,d in ranked],ensure_ascii=False,indent=2),encoding="utf-8")

errs=[]
for i,(score,url,hdr,path) in enumerate(ranked[:50]):
    if score < 0:
        continue
    h={"User-Agent":UA,"Referer":"https://www.douyin.com/"}
    for k,v in hdr.items():
        if isinstance(k,str) and isinstance(v,str):
            h[k]=v
    try:
        rr=requests.get(url,headers=h,stream=True,allow_redirects=True,timeout=120)
        ct=rr.headers.get("content-type","")
        if rr.status_code!=200:
            errs.append({"i":i,"score":score,"status":rr.status_code,"ct":ct,"url":url}); continue
        tmp=OUT/f"demo_candidate_{i}.bin"
        with open(tmp,"wb") as f:
            for ch in rr.iter_content(1024*1024):
                if ch: f.write(ch)
        size=tmp.stat().st_size
        if size<100000:
            errs.append({"i":i,"score":score,"reason":"too_small","bytes":size,"ct":ct,"url":url}); tmp.unlink(missing_ok=True); continue
        p=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type,width,height,codec_name","-of","json",str(tmp)],capture_output=True,text=True)
        if p.returncode!=0:
            errs.append({"i":i,"score":score,"reason":"ffprobe_failed","ct":ct,"stderr":p.stderr[-300:],"url":url}); tmp.unlink(missing_ok=True); continue
        pr=json.loads(p.stdout)
        if not any(st.get("codec_type")=="video" for st in pr.get("streams",[])):
            errs.append({"i":i,"score":score,"reason":"no_video","url":url}); tmp.unlink(missing_ok=True); continue
        tmp.replace(OUT/"source.mp4")
        (OUT/"ffprobe.json").write_text(json.dumps(pr,ensure_ascii=False,indent=2),encoding="utf-8")
        (OUT/"source_url.txt").write_text(url,encoding="utf-8")
        sys.exit(0)
    except Exception as e:
        errs.append({"i":i,"score":score,"error":repr(e),"url":url})

(OUT/"demo_download_errors.json").write_text(json.dumps(errs,ensure_ascii=False,indent=2),encoding="utf-8")
raise RuntimeError("Demo parser returned no downloadable video candidate")
