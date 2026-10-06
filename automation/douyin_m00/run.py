import json, os, re, subprocess, base64
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import requests
from Crypto.Cipher import AES

OUT=Path("handu_m00")
OUT.mkdir(parents=True,exist_ok=True)
URL=os.environ.get("DOUYIN_URL","https://v.douyin.com/YA0Q_ckY824/")
AWEME_ID=os.environ.get("AWEME_ID","6901971287422422286")
UA="Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"

def write_json(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")

def extract_json_object(s,start):
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

def attr(html_text, element_id, attr_name):
    m=re.search(r'<[^>]+id=[\'"]?'+re.escape(element_id)+r'[\'"]?[^>]*>',html_text,re.I)
    if not m: return ""
    tag=m.group(0)
    m2=re.search(r'\b'+re.escape(attr_name)+r'=([\'"])(.*?)\1',tag,re.I|re.S)
    if m2: return m2.group(2)
    m2=re.search(r'\b'+re.escape(attr_name)+r'=([^\s>]+)',tag,re.I)
    return m2.group(1) if m2 else ""

def router_data(html_text):
    m=re.search(r'window\._ROUTER_DATA\s*=\s*',html_text)
    if not m: return {}
    js=extract_json_object(html_text,m.end())
    return json.loads(js) if js else {}

def video_page(router):
    ld=router.get("loaderData") or {}
    for k,v in ld.items():
        if isinstance(v,dict) and k.endswith("/page") and ("video" in k or "slides" in k):
            return v
    return {}

def pkcs7(data,block=16):
    n=block-(len(data)%block)
    return data+bytes([n])*n

def reflow_id(xsstoken,web_id):
    key=web_id[:16].encode()
    cipher=AES.new(key,AES.MODE_CBC,iv=key)
    return base64.b64encode(cipher.encrypt(pkcs7(xsstoken.encode()))).decode()

def get_iteminfo():
    sess=requests.Session()
    headers={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8","Accept-Language":"zh-CN,zh;q=0.9"}
    share=f"https://www.iesdouyin.com/share/video/{AWEME_ID}"
    r=sess.get(share,headers=headers,timeout=60,allow_redirects=True)
    r.raise_for_status()
    html_text=r.text
    (OUT/"ies_page.html").write_text(html_text,encoding="utf-8",errors="ignore")
    router=router_data(html_text); vp=video_page(router)
    write_json("router_data.json",router)
    web_id=attr(html_text,"douyin_reflow_webId","webId") or str(vp.get("webId") or ((vp.get("commonContext") or {}).get("webId") or ""))
    user_cip=attr(html_text,"douyin_reflow_webId","usercip")
    xs=attr(html_text,"douyin_reflow_token","xsstoken")
    item_id=str(vp.get("itemId") or vp.get("lastPath") or AWEME_ID)
    if not web_id or not xs:
        raise RuntimeError(f"missing web_id/xsstoken: web_id={web_id!r}, xs={bool(xs)}")
    query=vp.get("query") or {}
    ab=vp.get("abParams") or {}
    use_new=str(((ab.get("select_pool_data") or {}).get("use_new_select_scope",0)))
    rid=reflow_id(xs,web_id)
    attempts=[]
    aids=[]
    for a in [str(query.get("from_aid") or ""), "1128","6383"]:
        if a and a not in aids: aids.append(a)
    for aid in aids:
        params={
            "reflow_source":"reflow_page",
            "web_id":web_id,
            "device_id":web_id,
            "aid":aid,
            "use_new_select_scope":use_new,
            "item_ids":item_id,
            "reflow_id":rid,
        }
        if user_cip: params["user_cip"]=user_cip
        for src,dst in [("did","from_did"),("aweme_type","aweme_type"),("share_scene","share_scene"),("share_token","share_token"),("scene_from","scene_from")]:
            if query.get(src) not in (None,""): params[dst]=str(query[src])
        api="https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/"
        ah={"User-Agent":UA,"Accept":"application/json, text/plain, */*","Accept-Language":"zh-CN,zh;q=0.9","Content-Type":"application/json","Referer":r.url}
        resp=sess.get(api,params=params,headers=ah,timeout=60)
        try: data=resp.json()
        except Exception: data={"_raw":resp.text[:2000]}
        write_json(f"iteminfo_aid_{aid}.json",data)
        attempts.append({"aid":aid,"status":resp.status_code,"url":resp.url,"keys":list(data) if isinstance(data,dict) else []})
        if isinstance(data,dict) and data.get("item_list"):
            write_json("iteminfo.json",data)
            write_json("iteminfo_attempts.json",attempts)
            return data,r.url
    write_json("iteminfo_attempts.json",attempts)
    raise RuntimeError("iteminfo returned no item_list")

def collect_urls(item):
    out=[]
    def add(arr):
        for u in arr or []:
            if u:
                u=u.replace("playwm","play")
                if u not in out: out.append(u)
    v=item.get("video") or {}
    # prefer muxed/play addresses first, then bitrate variants
    for key in ["play_addr","play_addr_h264","download_addr"]:
        x=v.get(key) or {}
        if isinstance(x,dict): add(x.get("url_list"))
    for br in v.get("bit_rate") or []:
        pa=(br or {}).get("play_addr") or {}
        add(pa.get("url_list"))
    return out

def probe(path):
    p=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type,width,height,codec_name","-of","json",str(path)],capture_output=True,text=True)
    return json.loads(p.stdout) if p.returncode==0 and p.stdout.strip() else None

def download_source(item,referer):
    urls=collect_urls(item)
    write_json("video_urls.json",urls)
    sess=requests.Session()
    h={"User-Agent":UA,"Referer":referer}
    errors=[]
    best_silent=None
    for idx,u in enumerate(urls):
        tmp=OUT/f"candidate_{idx}.mp4"
        try:
            with sess.get(u,headers=h,stream=True,timeout=180,allow_redirects=True) as rr:
                rr.raise_for_status()
                with tmp.open("wb") as fo:
                    for chunk in rr.iter_content(1024*1024):
                        if chunk: fo.write(chunk)
            pr=probe(tmp)
            if not pr:
                errors.append({"idx":idx,"reason":"ffprobe_failed","size":tmp.stat().st_size}); tmp.unlink(missing_ok=True); continue
            dur=float((pr.get("format") or {}).get("duration") or 0)
            types=[s.get("codec_type") for s in pr.get("streams",[])]
            if dur<4 or "video" not in types:
                errors.append({"idx":idx,"reason":"invalid","duration":dur,"types":types}); tmp.unlink(missing_ok=True); continue
            if "audio" in types:
                final=OUT/"source.mp4"; tmp.replace(final); write_json("ffprobe.json",pr); return final
            if best_silent is None: best_silent=(tmp,pr)
            else: tmp.unlink(missing_ok=True)
        except Exception as e:
            errors.append({"idx":idx,"error":str(e)})
    write_json("download_errors.json",errors)
    if best_silent:
        p,pr=best_silent
        (OUT/"source_silent.mp4").write_bytes(p.read_bytes())
    raise RuntimeError("no muxed source candidate with audio")

def make_frames(video):
    frames=OUT/"frames"; frames.mkdir(exist_ok=True)
    subprocess.run(["ffmpeg","-y","-i",str(video),"-vf","fps=1/2,scale=576:-2","-q:v","3",str(frames/"f_%03d.jpg")],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(["ffmpeg","-y","-i",str(video),"-vf","fps=1/2,scale=288:-2,tile=4x4:padding=4:margin=4","-frames:v","1",str(OUT/"contact.jpg")],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def fmt(sec):
    ms=int(round(sec*1000)); h=ms//3600000; ms%=3600000; m=ms//60000; ms%=60000; s=ms//1000; ms%=1000
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def transcribe(video):
    from faster_whisper import WhisperModel
    model=WhisperModel("small",device="cpu",compute_type="int8")
    segments,info=model.transcribe(str(video),language="zh",beam_size=5,vad_filter=True,word_timestamps=True)
    segs=[]; words=[]; srt=[]
    for n,seg in enumerate(segments,1):
        it={"id":n,"start":seg.start,"end":seg.end,"text":seg.text.strip(),"words":[]}
        for w in seg.words or []:
            wi={"start":w.start,"end":w.end,"word":w.word,"probability":getattr(w,"probability",None)}
            it["words"].append(wi); words.append(wi)
        segs.append(it); srt += [str(n),f"{fmt(seg.start)} --> {fmt(seg.end)}",it["text"],""]
    write_json("transcript.json",{"language":info.language,"language_probability":info.language_probability,"segments":segs})
    write_json("words.json",words)
    (OUT/"transcript.txt").write_text("\n".join(x["text"] for x in segs),encoding="utf-8")
    (OUT/"transcript.srt").write_text("\n".join(srt),encoding="utf-8")

def main():
    data,referer=get_iteminfo()
    item=data["item_list"][0]
    write_json("item.json",item)
    meta={"input_url":URL,"aweme_id":AWEME_ID,"description":item.get("desc") or "","duration_ms":(item.get("video") or {}).get("duration") or item.get("duration"),"author":(item.get("author") or {}).get("nickname") or ""}
    write_json("metadata.json",meta)
    video=download_source(item,referer)
    make_frames(video)
    transcribe(video)

if __name__=="__main__":
    main()
