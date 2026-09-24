#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time

ALLOWED_VOICES = {
    "my-review": "vcXEe1p3FxPfpswf3BhwbG",
}

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def fingerprint(scene, voice_alias, voice_id, speed):
    return hashlib.sha256(json.dumps({
        "text": scene["text"],
        "voiceAlias": voice_alias,
        "voiceId": voice_id,
        "speed": speed,
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,100}", value):
        raise ValueError("Invalid job/scene ID")
    return value

def validate_request(job):
    if job.get("schemaVersion") != 1 or job.get("stage") != "review_timing":
        raise ValueError("Review TTS requires schemaVersion 1 and stage review_timing")
    voice_alias = job.get("voiceAlias")
    voice_id = job.get("voiceId")
    if voice_alias not in ALLOWED_VOICES or ALLOWED_VOICES[voice_alias] != voice_id:
        raise ValueError("Unsupported review voice")
    speed = float(job.get("voiceSpeed", 1.0))
    if not 0.95 <= speed <= 1.08:
        raise ValueError("Review voice speed must be 0.95..1.08")
    safe_id(job["jobId"])
    scenes = job.get("scenes", [])
    if not 1 <= len(scenes) <= 5 or len({s["sceneId"] for s in scenes}) != len(scenes):
        raise ValueError("Provide 1–5 distinct review scenes")
    for scene in scenes:
        safe_id(scene["sceneId"])
        if not isinstance(scene.get("text"), str) or not 1 <= len(scene["text"].strip()) <= 6000:
            raise ValueError("Invalid review script")

def load_bridge(repo_root):
    path = repo_root / "automation/lucylab_bridge.py"
    spec = importlib.util.spec_from_file_location("lucylab_bridge", path)
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    return bridge, digest(path)

def synthesize(scene, folder, bridge, key, metadata, voice_alias, voice_id, speed):
    folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / "tts.json"
    fp = fingerprint(scene, voice_alias, voice_id, speed)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if state and state.get("fingerprint") != fp:
        raise ValueError("Checkpoint belongs to different review text")
    if state.get("state") == "completed":
        for name, expected in state["files"].items():
            if digest(folder / name) != expected:
                raise ValueError("Corrupt completed TTS checkpoint")
        return state

    export_id = state.get("projectExportId")
    if not export_id and state:
        raise RuntimeError("TTS_CREATION_UNCERTAIN: reconcile previous attempt before another paid request")

    if not export_id:
        state = {
            **metadata,
            "sceneId": scene["sceneId"],
            "fingerprint": fp,
            "voiceAlias": voice_alias,
            "voiceId": voice_id,
            "speed": speed,
            "state": "creation-pending",
        }
        write_json(state_path, state)
        result = bridge.rpc("ttsLongText", {
            "text": scene["text"],
            "userVoiceId": voice_id,
            "speed": speed,
        }, key, retries=1)
        export_id = str(result.get("projectExportId") or "")
        if not export_id:
            raise RuntimeError("TTS_CREATION_UNCERTAIN: no export ID returned")
        state.update(state="polling", projectExportId=export_id)
        write_json(state_path, state)

    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        status = bridge.rpc("getExportStatus", {"projectExportId": export_id}, key, retries=3)
        if status.get("state") == "failed":
            state["state"] = "failed"
            write_json(state_path, state)
            raise RuntimeError("LucyLab export failed")
        if status.get("state") == "completed":
            if not status.get("url") or not status.get("srtUrl"):
                raise RuntimeError("Completed export is missing audio/SRT")
            bridge.download(status["url"], folder / "voice.wav")
            bridge.download(status["srtUrl"], folder / "subtitles.original.srt")
            probe = json.loads(subprocess.check_output([
                "ffprobe","-v","error","-show_format","-show_streams","-of","json",str(folder/"voice.wav")
            ]))
            if not any(x["codec_type"] == "audio" for x in probe["streams"]):
                raise RuntimeError("Missing audio stream")
            duration = round(float(probe["format"]["duration"]) * 1000)
            if duration <= 0 or "-->" not in (folder/"subtitles.original.srt").read_text(encoding="utf-8-sig"):
                raise RuntimeError("Invalid audio duration or SRT")
            subprocess.run(["ffmpeg","-v","error","-i",str(folder/"voice.wav"),"-f","null","-"], check=True)
            state.update(
                state="completed",
                durationMs=duration,
                mediaFormat=probe["format"]["format_name"],
                files={name:digest(folder/name) for name in ["voice.wav","subtitles.original.srt"]},
            )
            write_json(state_path, state)
            return state
        time.sleep(2.5)
    raise TimeoutError("LucyLab polling timed out; export ID preserved")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--requests", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[2]
    bridge, bridge_hash = load_bridge(root)
    key = os.environ.get("LUCYLAB_API_KEY", "").strip()
    if not key:
        raise SystemExit("Missing LUCYLAB_API_KEY secret")

    for relative in json.loads(args.requests.read_text()):
        job = json.loads((root/relative).read_text(encoding="utf-8"))
        validate_request(job)
        if job.get("bridgeSha256") != bridge_hash:
            raise ValueError("LucyLab bridge version changed; review before sending")
        voice_alias = job["voiceAlias"]
        voice_id = job["voiceId"]
        speed = float(job.get("voiceSpeed", 1.0))
        destination = args.out / job["jobId"]
        metadata = {
            "jobId": job["jobId"],
            "githubRunId": os.environ.get("GITHUB_RUN_ID"),
            "githubRunAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "githubCommit": os.environ.get("GITHUB_SHA"),
            "bridgeSha256": bridge_hash,
        }
        if int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")) != 1:
            raise RuntimeError("Do not rerun paid TTS jobs; retrieve preserved export IDs first")
        write_json(destination/"request.json", job)
        results = []
        for scene in job["scenes"]:
            results.append(synthesize(
                scene, destination/scene["sceneId"], bridge, key, metadata,
                voice_alias, voice_id, speed
            ))
        write_json(destination/"timing.json", {"schemaVersion":1, **metadata, "scenes":results})

if __name__ == "__main__":
    main()
