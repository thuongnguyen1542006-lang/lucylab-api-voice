import json, re, sys, subprocess, os
from pathlib import Path
import requests

VID = sys.argv[1]
OUT = Path("handu_fetch_output")
OUT.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Mobile Safari/537.36"
share = f"https://www.iesdouyin.com/share/video/{VID}"
headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7", "Referer":"https://www.douyin.com/"}


# Public no-key parser fallbacks for short links that Douyin blocks on datacenter IPs.
SRC_URL = os.environ.get("SRC_URL", "").strip()
PUBLIC_APIS = [
    ("qsy", "https://qsy.aiwyuw.cn/api/short_videos.php"),
    ("devtool", "https://www.devtool.top/api/douyin/parse"),
    ("jxcxin", "https://apis.jxcxin.cn/api/douyin"),
    ("mxin", "https://api.mxin.moe/api/v1/douyin"),
]

def _pick_media_url(obj):
    preferred = []
    fallback = []
    def rec(x, path=""):
        if isinstance(x, dict):
            for k, v in x.items():
                p = f"{path}.{k}" if path else str(k)
                if isinstance(v, str) and v.startswith("http"):
                    lk = k.lower()
                    lp = p.lower()
                    if any(t in lk for t in ("video", "play")) or any(t in lp for t in ("video.url", "video_url", "play_addr", "playurl")):
                        preferred.append(v)
                    elif lk == "url" or lp.endswith(".url"):
                        fallback.append(v)
                elif isinstance(v, (dict, list)):
                    rec(v, p)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                rec(v, f"{path}[{i}]")
    rec(obj)
    urls=[]
    for u in preferred + fallback:
        u=u.replace("\\/","/")
        if u not in urls:
            urls.append(u)
    return urls

def _download_candidate(u, referer):
    rr=requests.get(
        u,
        headers={"User-Agent":UA,"Referer":referer or "https://www.douyin.com/"},
        stream=True,
        allow_redirects=True,
        timeout=120,
    )
    if rr.status_code != 200:
        return False, f"http_{rr.status_code}"
    tmp=OUT/"public_candidate.bin"
    with open(tmp,"wb") as f:
        for ch in rr.iter_content(1024*1024):
            if ch: f.write(ch)
    if not tmp.exists() or tmp.stat().st_size < 100000:
        sz=tmp.stat().st_size if tmp.exists() else 0
        tmp.unlink(missing_ok=True)
        return False, f"too_small_{sz}"
    p=subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type,width,height,codec_name","-of","json",str(tmp)],
        capture_output=True,text=True
    )
    if p.returncode!=0:
        tmp.unlink(missing_ok=True)
        return False, "ffprobe_failed"
    pr=json.loads(p.stdout)
    if not any(x.get("codec_type")=="video" for x in pr.get("streams",[])):
        tmp.unlink(missing_ok=True)
        return False, "no_video"
    tmp.replace(OUT/"source.mp4")
    (OUT/"ffprobe.json").write_text(json.dumps(pr,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"source_url.txt").write_text(u,encoding="utf-8")
    return True, "ok"

public_diag=[]
if SRC_URL:
    for name, api in PUBLIC_APIS:
        try:
            pr=requests.get(api,params={"url":SRC_URL},headers={"User-Agent":UA},timeout=45)
            entry={"name":name,"status":pr.status_code,"api":api,"final_url":pr.url,"text_prefix":pr.text[:500]}
            public_diag.append(entry)
            if pr.status_code != 200:
                continue
            try:
                data=pr.json()
            except Exception:
                continue
            (OUT/f"public_{name}.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
            for media_url in _pick_media_url(data):
                ok, why=_download_candidate(media_url, SRC_URL)
                public_diag.append({"name":name,"media_url":media_url,"download":why})
                if ok:
                    (OUT/"public_fallback.json").write_text(json.dumps(public_diag,ensure_ascii=False,indent=2),encoding="utf-8")
                    sys.exit(0)
        except Exception as e:
            public_diag.append({"name":name,"error":repr(e)})
    (OUT/"public_fallback.json").write_text(json.dumps(public_diag,ensure_ascii=False,indent=2),encoding="utf-8")


def extract_obj(s, start):
    depth=0; ins=False; esc=False
    for i in range(start,len(s)):
        c=s[i]
        if esc: esc=False; continue
        if c=="\\" and ins: esc=True; continue
        if c=='"': ins=not ins; continue
        if ins: continue
        if c=="{": depth+=1
        elif c=="}":
            depth-=1
            if depth==0: return s[start:i+1]
    return None

def walk(x, path="$"):
    if isinstance(x, dict):
        yield path,x
        for k,v in x.items():
            yield from walk(v, path+"."+str(k))
    elif isinstance(x, list):
        for i,v in enumerate(x):
            yield from walk(v, f"{path}[{i}]")

def url_lists(x):
    urls=[]
    if isinstance(x, dict):
        ul=x.get("url_list")
        if isinstance(ul,list):
            urls += [u for u in ul if isinstance(u,str) and u.startswith("http")]
        for v in x.values():
            if isinstance(v,(dict,list)):
                urls += url_lists(v)
    elif isinstance(x,list):
        for v in x:
            urls += url_lists(v)
    seen=[]
    for u in urls:
        u=u.replace("playwm","play")
        if u not in seen:
            seen.append(u)
    return seen

def find_item(obj):
    best=None
    for path,d in walk(obj):
        if not isinstance(d,dict):
            continue
        aid=str(d.get("aweme_id") or d.get("awemeId") or d.get("id") or "")
        video=d.get("video")
        urls=url_lists(video) if isinstance(video,dict) else []
        if not urls:
            continue
        score=(100 if VID in aid else 0)+(10 if d.get("desc") else 0)+min(5,len(urls))
        cand=(score,path,d,urls)
        if best is None or score>best[0]:
            best=cand
    return best

api_attempts = [
    f"https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids={VID}",
    f"https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?reflow_source=reflow_page&item_ids={VID}",
    f"https://www.douyin.com/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383&channel=channel_pc_web&aweme_id={VID}&request_source=600&origin_type=quick_player",
]
api_log=[]
candidate=None
for idx,api in enumerate(api_attempts):
    try:
        ar=requests.get(api,headers=headers,timeout=45)
        body=ar.text
        (OUT/f"api_{idx}.txt").write_text(body,encoding="utf-8",errors="ignore")
        api_log.append({"url":api,"status":ar.status_code,"content_type":ar.headers.get("content-type",""),"prefix":body[:240]})
        if ar.status_code==200:
            try:
                aj=ar.json()
                candidate=find_item(aj)
                if candidate:
                    break
            except Exception:
                pass
    except Exception as e:
        api_log.append({"url":api,"error":repr(e)})
(OUT/"api_attempts.json").write_text(json.dumps(api_log,ensure_ascii=False,indent=2),encoding="utf-8")

if not candidate:
    r=requests.get(share,headers=headers,timeout=60)
    (OUT/"ies_status.txt").write_text(f"{r.status_code}\n{r.url}\n",encoding="utf-8")
    (OUT/"ies_page.html").write_text(r.text,encoding="utf-8",errors="ignore")
    r.raise_for_status()
    m=re.search(r"window\._ROUTER_DATA\s*=\s*",r.text)
    if not m:
        raise RuntimeError("_ROUTER_DATA missing")
    raw=extract_obj(r.text,m.end())
    if not raw:
        raise RuntimeError("_ROUTER_DATA parse boundary failed")
    router=json.loads(raw)
    candidate=find_item(router)

if not candidate:
    raise RuntimeError("No video candidates found from APIs or router data")

score,path,item,urls=candidate
(OUT/"ies_item.json").write_text(json.dumps(item,ensure_ascii=False,indent=2),encoding="utf-8")
(OUT/"selected_candidate.txt").write_text(f"score={score}\npath={path}\n",encoding="utf-8")

video=item.get("video") or {}
uris=[]
for p,d in walk(video,"video"):
    if not isinstance(d,dict):
        continue
    for key in ("uri","video_id","videoId"):
        v=d.get(key)
        if isinstance(v,str) and len(v)>8 and v not in uris:
            uris.append(v)
for uri in uris:
    urls.insert(0,f"https://www.iesdouyin.com/aweme/v1/play/?video_id={uri}&ratio=1080p&line=0")
    urls.insert(0,f"https://aweme.snssdk.com/aweme/v1/play/?video_id={uri}&ratio=1080p&line=0")

errs=[]
for i,u in enumerate(urls[:40]):
    try:
        rr=requests.get(u,headers={"User-Agent":UA,"Referer":share},stream=True,allow_redirects=True,timeout=120)
        ct=rr.headers.get("content-type","")
        if rr.status_code!=200:
            errs.append({"i":i,"status":rr.status_code,"url":u}); continue
        tmp=OUT/f"candidate_{i}.bin"
        with open(tmp,"wb") as fh:
            for ch in rr.iter_content(1024*1024):
                if ch: fh.write(ch)
        if tmp.stat().st_size < 100000:
            errs.append({"i":i,"reason":"too_small","bytes":tmp.stat().st_size,"ct":ct,"url":u}); tmp.unlink(missing_ok=True); continue
        p=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type,width,height,codec_name","-of","json",str(tmp)],capture_output=True,text=True)
        if p.returncode!=0:
            errs.append({"i":i,"reason":"ffprobe_failed","ct":ct,"stderr":p.stderr[-300:],"url":u}); tmp.unlink(missing_ok=True); continue
        pr=json.loads(p.stdout)
        streams=pr.get("streams",[])
        if not any(s.get("codec_type")=="video" for s in streams):
            errs.append({"i":i,"reason":"no_video","url":u}); tmp.unlink(missing_ok=True); continue
        final=OUT/"source.mp4"
        tmp.replace(final)
        (OUT/"ffprobe.json").write_text(json.dumps(pr,ensure_ascii=False,indent=2),encoding="utf-8")
        (OUT/"source_url.txt").write_text(u,encoding="utf-8")
        sys.exit(0)
    except Exception as e:
        errs.append({"i":i,"error":repr(e),"url":u})
(OUT/"ies_download_errors.json").write_text(json.dumps(errs,ensure_ascii=False,indent=2),encoding="utf-8")
raise RuntimeError("IES/API fallback could not download a valid video")
