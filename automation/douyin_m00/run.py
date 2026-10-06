import asyncio, json, os, re, subprocess, sys, time
from pathlib import Path
from urllib.parse import urlparse
import requests

OUT = Path("handu_m00")
OUT.mkdir(parents=True, exist_ok=True)
URL = os.environ["DOUYIN_URL"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"

def write_json(name, obj):
    (OUT/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

async def acquire():
    from playwright.async_api import async_playwright
    media_candidates = []
    meta = {"input_url": URL}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent=UA,
            locale="zh-CN",
            viewport={"width": 1280, "height": 900},
            extra_http_headers={"Accept-Language":"zh-CN,zh;q=0.9,en;q=0.8"}
        )
        page = await context.new_page()

        def on_response(resp):
            u = resp.url
            ct = (resp.headers.get("content-type") or "").lower()
            if ("video" in ct or "douyinvod" in u or "zjcdn" in u or "/aweme/v1/play" in u or ".mp4" in u):
                if u not in media_candidates:
                    media_candidates.append(u)
        page.on("response", on_response)

        try:
            resp = await page.goto(URL, wait_until="domcontentloaded", timeout=120000)
            meta["navigation_status"] = resp.status if resp else None
        except Exception as e:
            meta["navigation_error"] = str(e)
        await page.wait_for_timeout(7000)
        final_url = page.url
        meta["final_url"] = final_url
        title = await page.title()
        meta["page_title"] = title

        m = re.search(r"/video/(\d{15,22})", final_url)
        aweme_id = m.group(1) if m else None
        if not aweme_id:
            html = await page.content()
            ids = re.findall(r'(?:aweme_id|awemeId).{0,40}?(\\d{15,22})', html)
            if ids:
                aweme_id = ids[0]
        meta["aweme_id"] = aweme_id

        data = None
        if aweme_id:
            api_url = f"https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={aweme_id}&device_platform=webapp&aid=6383"
            try:
                data = await page.evaluate("""async (u) => {
                  const r = await fetch(u, {credentials:'include', headers:{'Accept':'application/json','Referer':'https://www.douyin.com/'}});
                  const t = await r.text();
                  return {status:r.status, text:t};
                }""", api_url)
                meta["api_status"] = data.get("status")
                if data.get("text"):
                    payload = json.loads(data["text"])
                    write_json("douyin_api.json", payload)
                    detail = payload.get("aweme_detail") or {}
                    meta["description"] = detail.get("desc") or ""
                    video = detail.get("video") or {}
                    play = video.get("play_addr") or video.get("play_addr_h264") or {}
                    urls = play.get("url_list") or []
                    meta["duration_ms"] = video.get("duration")
                    meta["source_width"] = play.get("width")
                    meta["source_height"] = play.get("height")
                    for u in urls:
                        if u and u not in media_candidates:
                            media_candidates.append(u)
            except Exception as e:
                meta["api_error"] = str(e)

        # Give MSE/network playback another chance to expose direct media.
        try:
            await page.evaluate("""() => {
              const v=document.querySelector('video');
              if(v){v.muted=true; v.play().catch(()=>{});}
            }""")
            await page.wait_for_timeout(5000)
        except Exception:
            pass

        # collect performance resource URLs too
        try:
            perfs = await page.evaluate("performance.getEntriesByType('resource').map(x=>x.name)")
            for u in perfs:
                if any(k in u for k in ["douyinvod","zjcdn","/aweme/v1/play",".mp4"]):
                    if u not in media_candidates:
                        media_candidates.append(u)
        except Exception:
            pass

        meta["media_candidates"] = media_candidates[:100]
        await browser.close()

    write_json("metadata.json", meta)
    return meta, media_candidates

def download_video(candidates):
    headers = {"User-Agent": UA, "Referer": "https://www.douyin.com/"}
    errors = []
    # prefer clean CDN/play urls; later URLs from play_addr are often stable
    ordered = list(reversed(candidates))
    for i,u in enumerate(ordered):
        try:
            r = requests.get(u, headers=headers, allow_redirects=True, stream=True, timeout=120)
            ct=(r.headers.get("content-type") or "").lower()
            if r.status_code != 200:
                errors.append({"url":u,"status":r.status_code,"ct":ct})
                continue
            path = OUT/"source.mp4"
            with path.open("wb") as f:
                total=0
                for chunk in r.iter_content(1024*1024):
                    if chunk:
                        f.write(chunk); total += len(chunk)
            if total < 100_000:
                errors.append({"url":u,"status":"too_small","bytes":total,"ct":ct})
                path.unlink(missing_ok=True)
                continue
            # validate
            p=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type,width,height","-of","json",str(path)],capture_output=True,text=True)
            if p.returncode==0:
                write_json("ffprobe.json", json.loads(p.stdout))
                return str(path)
            errors.append({"url":u,"status":"ffprobe_failed","stderr":p.stderr[-500:]})
            path.unlink(missing_ok=True)
        except Exception as e:
            errors.append({"url":u,"error":str(e)})
    write_json("download_errors.json", errors)
    raise RuntimeError("Could not download a valid MP4")

def make_frames(video):
    frames=OUT/"frames"; frames.mkdir(exist_ok=True)
    subprocess.run(["ffmpeg","-y","-i",video,"-vf","fps=1/2,scale=576:-2","-q:v","3",str(frames/"f_%03d.jpg")],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    # contact sheet
    subprocess.run(["ffmpeg","-y","-i",video,"-vf","fps=1/2,scale=288:-2,tile=4x4:padding=4:margin=4","-frames:v","1",str(OUT/"contact.jpg")],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def fmt_srt_time(sec):
    ms=int(round(sec*1000)); h=ms//3600000; ms%=3600000; m=ms//60000; ms%=60000; s=ms//1000; ms%=1000
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def transcribe(video):
    from faster_whisper import WhisperModel
    model=WhisperModel("small", device="cpu", compute_type="int8")
    segments, info=model.transcribe(video, language="zh", beam_size=5, vad_filter=True, word_timestamps=True)
    segs=[]; words=[]; srt=[]
    for idx,seg in enumerate(segments,1):
        text=seg.text.strip()
        item={"id":idx,"start":seg.start,"end":seg.end,"text":text,"words":[]}
        for w in (seg.words or []):
            wi={"start":w.start,"end":w.end,"word":w.word,"probability":getattr(w,"probability",None)}
            item["words"].append(wi); words.append(wi)
        segs.append(item)
        srt += [str(idx), f"{fmt_srt_time(seg.start)} --> {fmt_srt_time(seg.end)}", text, ""]
    write_json("transcript.json", {"language":info.language,"language_probability":info.language_probability,"segments":segs})
    write_json("words.json", words)
    (OUT/"transcript.txt").write_text("\n".join(x["text"] for x in segs),encoding="utf-8")
    (OUT/"transcript.srt").write_text("\n".join(srt),encoding="utf-8")

async def main():
    meta,cands=await acquire()
    video=download_video(cands)
    make_frames(video)
    transcribe(video)

if __name__=="__main__":
    asyncio.run(main())
