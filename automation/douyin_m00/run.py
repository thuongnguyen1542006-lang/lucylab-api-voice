import asyncio, json, os, re, subprocess
from pathlib import Path
import requests

OUT = Path("handu_m00")
OUT.mkdir(parents=True, exist_ok=True)
URL = os.environ["DOUYIN_URL"]
UA = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Mobile Safari/537.36"

def write_json(name, obj):
    (OUT/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def extract_json_object(html, start):
    depth = 0; in_str = False; esc = False
    for i in range(start, len(html)):
        c = html[i]
        if esc:
            esc = False; continue
        if c == "\\" and in_str:
            esc = True; continue
        if c == '"':
            in_str = not in_str; continue
        if in_str: continue
        if c == "{": depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return html[start:i+1]
    return None

def find_video_info_res(obj):
    if isinstance(obj, dict):
        if "videoInfoRes" in obj and isinstance(obj["videoInfoRes"], dict):
            return obj["videoInfoRes"]
        for v in obj.values():
            r = find_video_info_res(v)
            if r: return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_video_info_res(v)
            if r: return r
    return None

def fetch_ies(aweme_id):
    share = f"https://www.iesdouyin.com/share/video/{aweme_id}"
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9"
    }
    r = requests.get(share, headers=headers, timeout=60)
    (OUT/"ies_page.html").write_text(r.text, encoding="utf-8", errors="ignore")
    r.raise_for_status()
    m = re.search(r"window\._ROUTER_DATA\s*=\s*", r.text)
    if not m:
        raise RuntimeError("_ROUTER_DATA not found")
    js = extract_json_object(r.text, m.end())
    if not js:
        raise RuntimeError("_ROUTER_DATA JSON not extractable")
    router = json.loads(js)
    vir = find_video_info_res(router)
    if not vir:
        raise RuntimeError("videoInfoRes not found")
    items = vir.get("item_list") or []
    if not items:
        raise RuntimeError("item_list empty")
    item = items[0]
    write_json("ies_item.json", item)
    video = item.get("video") or {}
    play = video.get("play_addr") or video.get("play_addr_h264") or {}
    video_urls = []
    for u in (play.get("url_list") or []):
        if u:
            u = u.replace("playwm", "play")
            if u not in video_urls: video_urls.append(u)
    music = item.get("music") or {}
    audio_urls = (music.get("play_url") or {}).get("url_list") or []
    meta = {
        "description": item.get("desc") or "",
        "duration_ms": video.get("duration") or item.get("duration"),
        "author": (item.get("author") or {}).get("nickname") or "",
        "video_urls": video_urls,
        "audio_urls": audio_urls,
    }
    write_json("ies_meta.json", meta)
    return meta

async def resolve_id():
    from playwright.async_api import async_playwright
    meta = {"input_url": URL}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox","--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(user_agent=UA, locale="zh-CN", viewport={"width":1280,"height":900})
        await context.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = await context.new_page()
        try:
            resp = await page.goto(URL, wait_until="domcontentloaded", timeout=120000)
            meta["navigation_status"] = resp.status if resp else None
        except Exception as e:
            meta["navigation_error"] = str(e)
        await page.wait_for_timeout(5000)
        meta["final_url"] = page.url
        try:
            await page.screenshot(path=str(OUT/"page.png"), full_page=False)
        except Exception:
            pass
        html = await page.content()
        (OUT/"page.html").write_text(html, encoding="utf-8", errors="ignore")
        m = re.search(r"/video/(\d{15,22})", page.url)
        aweme_id = m.group(1) if m else None
        if not aweme_id:
            ids = re.findall(r'(?:aweme_id|awemeId).{0,60}?(\d{15,22})', html)
            if ids: aweme_id = ids[0]
        meta["aweme_id"] = aweme_id
        await browser.close()
    write_json("metadata.json", meta)
    if not aweme_id:
        raise RuntimeError("Could not resolve aweme id")
    return aweme_id, meta

def probe(path):
    p = subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type,width,height,codec_name","-of","json",str(path)],
        capture_output=True, text=True
    )
    if p.returncode != 0:
        return None
    return json.loads(p.stdout)

def stream_download(url, path, referer="https://www.douyin.com/"):
    headers={"User-Agent":UA,"Referer":referer}
    with requests.get(url,headers=headers,allow_redirects=True,stream=True,timeout=180) as r:
        r.raise_for_status()
        with open(path,"wb") as f:
            for chunk in r.iter_content(1024*1024):
                if chunk: f.write(chunk)

def download_video(video_urls, audio_urls):
    errors=[]; silent_fallback=None
    for idx,u in enumerate(video_urls):
        tmp=OUT/f"candidate_{idx}.mp4"
        try:
            stream_download(u,tmp)
            if tmp.stat().st_size < 100_000:
                errors.append({"url":u,"reason":"too_small","bytes":tmp.stat().st_size}); tmp.unlink(missing_ok=True); continue
            pr=probe(tmp)
            if not pr:
                errors.append({"url":u,"reason":"ffprobe_failed"}); tmp.unlink(missing_ok=True); continue
            dur=float((pr.get("format") or {}).get("duration") or 0)
            types=[x.get("codec_type") for x in pr.get("streams",[])]
            if dur < 4:
                errors.append({"url":u,"reason":"too_short","duration":dur}); tmp.unlink(missing_ok=True); continue
            if "video" not in types:
                errors.append({"url":u,"reason":"no_video"}); tmp.unlink(missing_ok=True); continue
            if "audio" in types:
                final=OUT/"source.mp4"; tmp.replace(final); write_json("ffprobe.json",pr); return str(final)
            if silent_fallback is None:
                silent_fallback=(tmp,pr)
            else:
                tmp.unlink(missing_ok=True)
        except Exception as e:
            errors.append({"url":u,"error":str(e)})
    # mux separate audio if required
    if silent_fallback and audio_urls:
        vpath,vpr=silent_fallback
        for j,u in enumerate(audio_urls):
            apath=OUT/f"audio_{j}.bin"
            try:
                stream_download(u,apath)
                out=OUT/"source.mp4"
                p=subprocess.run(["ffmpeg","-y","-i",str(vpath),"-i",str(apath),"-c:v","copy","-c:a","aac","-shortest",str(out)],capture_output=True,text=True)
                if p.returncode==0:
                    pr=probe(out)
                    if pr and "audio" in [x.get("codec_type") for x in pr.get("streams",[])]:
                        write_json("ffprobe.json",pr); return str(out)
                errors.append({"audio_url":u,"reason":"mux_failed","stderr":p.stderr[-500:]})
            except Exception as e:
                errors.append({"audio_url":u,"error":str(e)})
    write_json("download_errors.json",errors)
    raise RuntimeError("No valid muxed source video found")

def make_frames(video):
    frames=OUT/"frames"; frames.mkdir(exist_ok=True)
    subprocess.run(["ffmpeg","-y","-i",video,"-vf","fps=1/2,scale=576:-2","-q:v","3",str(frames/"f_%03d.jpg")],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(["ffmpeg","-y","-i",video,"-vf","fps=1/2,scale=288:-2,tile=4x4:padding=4:margin=4","-frames:v","1",str(OUT/"contact.jpg")],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def fmt_srt_time(sec):
    ms=int(round(sec*1000)); h=ms//3600000; ms%=3600000; m=ms//60000; ms%=60000; ss=ms//1000; ms%=1000
    return f"{h:02}:{m:02}:{ss:02},{ms:03}"

def transcribe(video):
    from faster_whisper import WhisperModel
    model=WhisperModel("small",device="cpu",compute_type="int8")
    segments,info=model.transcribe(video,language="zh",beam_size=5,vad_filter=True,word_timestamps=True)
    segs=[]; words=[]; srt=[]
    for idx,seg in enumerate(segments,1):
        item={"id":idx,"start":seg.start,"end":seg.end,"text":seg.text.strip(),"words":[]}
        for w in (seg.words or []):
            wi={"start":w.start,"end":w.end,"word":w.word,"probability":getattr(w,"probability",None)}
            item["words"].append(wi); words.append(wi)
        segs.append(item)
        srt += [str(idx), f"{fmt_srt_time(seg.start)} --> {fmt_srt_time(seg.end)}", item["text"], ""]
    write_json("transcript.json",{"language":info.language,"language_probability":info.language_probability,"segments":segs})
    write_json("words.json",words)
    (OUT/"transcript.txt").write_text("\n".join(x["text"] for x in segs),encoding="utf-8")
    (OUT/"transcript.srt").write_text("\n".join(srt),encoding="utf-8")

async def main():
    aweme_id,meta=await resolve_id()
    ies=fetch_ies(aweme_id)
    meta.update({k:v for k,v in ies.items() if k not in ("video_urls","audio_urls")})
    write_json("metadata.json",meta)
    video=download_video(ies["video_urls"],ies["audio_urls"])
    make_frames(video)
    transcribe(video)

if __name__=="__main__":
    asyncio.run(main())
