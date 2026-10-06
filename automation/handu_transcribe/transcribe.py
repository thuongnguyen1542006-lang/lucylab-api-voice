import json, subprocess, sys
from pathlib import Path
from faster_whisper import WhisperModel

src=Path(sys.argv[1])
out=Path(sys.argv[2])
out.mkdir(parents=True,exist_ok=True)

model=WhisperModel("small", device="cpu", compute_type="int8")
segments,info=model.transcribe(str(src),language="zh",beam_size=5,vad_filter=True,word_timestamps=True)
segs=[]; words=[]; lines=[]
for i,s in enumerate(segments,1):
    ws=[]
    for w in (s.words or []):
        d={"start":w.start,"end":w.end,"word":w.word,"probability":getattr(w,"probability",None)}
        ws.append(d); words.append(d)
    text=s.text.strip()
    segs.append({"id":i,"start":s.start,"end":s.end,"text":text,"words":ws})
    lines.append(f"[{s.start:.2f}-{s.end:.2f}] {text}")
(out/"transcript.json").write_text(json.dumps({"language":info.language,"language_probability":info.language_probability,"segments":segs},ensure_ascii=False,indent=2),encoding="utf-8")
(out/"words.json").write_text(json.dumps(words,ensure_ascii=False,indent=2),encoding="utf-8")
(out/"transcript.txt").write_text("\n".join(lines),encoding="utf-8")
