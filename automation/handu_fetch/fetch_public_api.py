import json, sys, subprocess
from pathlib import Path
import requests

SRC = sys.argv[1]
OUT = Path("handu_fetch_output")
OUT.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Mobile Safari/537.36"

providers = [
    ("btstu", "https://download.btstu.cn/dyjx/api.php", {"url": SRC}),
]

def collect_urls(obj):
    found=[]
    def walk(x,path="$"):
        if isinstance(x,dict):
            for k,v in x.items():
                p=path+"."+str(k)
                if isinstance(v,str) and v.startswith(("http://","https://")):
                    score=0
                    low=(k+" "+v).lower()
                    if any(t in low for t in ("videourl","play_url","video_url","video","play")): score += 60
                    if ".mp4" in low: score += 30
                    if any(t in low for t in ("cover","img","image","avatar")): score -= 80
                    found.append((score,v,p))
                else:
                    walk(v,p)
        elif isinstance(x,list):
            for i,v in enumerate(x):
                walk(v,f"{path}[{i}]")
    walk(obj)
    out=[]; seen=set()
    for x in sorted(found,key=lambda z:z[0],reverse=True):
        if x[1] not in seen:
            seen.add(x[1]); out.append(x)
    return out

logs=[]
for name,endpoint,params in providers:
    try:
        r=requests.get(endpoint,params=params,headers={"User-Agent":UA,"Referer":"https://v.douyin.com/"},timeout=45)
        logs.append({"provider":name,"status":r.status_code,"url":r.url,"prefix":r.text[:500]})
        (OUT/f"{name}_response.txt").write_text(r.text,encoding="utf-8",errors="ignore")
        if r.status_code != 200:
            continue
        try:
            obj=r.json()
        except Exception:
            continue
        (OUT/f"{name}_response.json").write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
        urls=collect_urls(obj)
        (OUT/f"{name}_candidates.json").write_text(json.dumps([{"score":s,"url":u,"path":p} for s,u,p in urls],ensure_ascii=False,indent=2),encoding="utf-8")
        for i,(score,u,path) in enumerate(urls[:20]):
            if score < 0: continue
            try:
                rr=requests.get(u,headers={"User-Agent":UA,"Referer":"https://www.douyin.com/"},stream=True,allow_redirects=True,timeout=120)
                if rr.status_code != 200:
                    continue
                tmp=OUT/f"{name}_candidate_{i}.bin"
                with open(tmp,"wb") as f:
                    for ch in rr.iter_content(1024*1024):
                        if ch: f.write(ch)
                if tmp.stat().st_size < 100000:
                    tmp.unlink(missing_ok=True); continue
                p=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type,width,height,codec_name","-of","json",str(tmp)],capture_output=True,text=True)
                if p.returncode != 0:
                    tmp.unlink(missing_ok=True); continue
                pr=json.loads(p.stdout)
                if not any(st.get("codec_type")=="video" for st in pr.get("streams",[])):
                    tmp.unlink(missing_ok=True); continue
                tmp.replace(OUT/"source.mp4")
                (OUT/"ffprobe.json").write_text(json.dumps(pr,ensure_ascii=False,indent=2),encoding="utf-8")
                (OUT/"source_url.txt").write_text(u,encoding="utf-8")
                (OUT/"provider.txt").write_text(name,encoding="utf-8")
                sys.exit(0)
            except Exception as e:
                logs.append({"provider":name,"candidate":i,"error":repr(e)})
    except Exception as e:
        logs.append({"provider":name,"error":repr(e)})
(OUT/"public_api_attempts.json").write_text(json.dumps(logs,ensure_ascii=False,indent=2),encoding="utf-8")
raise RuntimeError("Public parser did not yield a valid video")
