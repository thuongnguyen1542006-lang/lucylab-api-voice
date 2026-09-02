#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://api.lucylab.io/json-rpc"
VOICE_ALIASES = {
    "co-nhan": "vobfq29MDccJJPpsVLHZxV",
    "quang-anh": "24oEtXGic7NhDjXzmDbDvt",
    "huy-vu": "hruBcESGYx2AUWRppNacCd",
    "chi-mai": "cLZiqtzLcKYqwYrWJemAJK",
}


def rpc(method: str, input_data: dict, api_key: str, retries: int = 5) -> dict:
    payload = json.dumps({"method": method, "input": input_data}, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "whiteboard-v34-runner/3.4"}
    last_error = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(ENDPOINT, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if body.get("error"):
                raise RuntimeError(f"LucyLab RPC error: {body['error']}")
            result = body.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("LucyLab response missing result")
            return result
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError("LucyLab authentication failed") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            last_error = exc
        if attempt < retries:
            time.sleep(min(2 ** (attempt - 1), 12))
    raise RuntimeError(f"LucyLab request failed: {last_error}")


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "whiteboard-v34-runner/3.4"})
    with urllib.request.urlopen(req, timeout=120) as resp, path.open("wb") as fh:
        while True:
            chunk = resp.read(262144)
            if not chunk:
                break
            fh.write(chunk)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--voice-alias", default="co-nhan")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not 0.5 <= args.speed <= 2.0:
        raise SystemExit("voice speed must be 0.5..2.0")
    voice_id = VOICE_ALIASES.get(args.voice_alias)
    if not voice_id:
        raise SystemExit(f"unknown voice alias: {args.voice_alias}")
    key = os.environ.get("LUCYLAB_API_KEY", "").strip()
    if not key:
        raise SystemExit("RUNNER_NOT_READY: missing LUCYLAB_API_KEY")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    created = rpc("ttsLongText", {"text": args.text, "userVoiceId": voice_id, "speed": args.speed}, key)
    export_id = str(created.get("projectExportId") or "")
    if not export_id:
        raise RuntimeError("LucyLab missing projectExportId")

    deadline = time.time() + 900
    while time.time() < deadline:
        status = rpc("getExportStatus", {"projectExportId": export_id}, key)
        state = str(status.get("state") or "")
        print(f"LucyLab state={state or 'unknown'}")
        if state == "completed":
            audio_url = str(status.get("url") or "")
            srt_url = str(status.get("srtUrl") or "")
            if not audio_url or not srt_url:
                raise RuntimeError("LucyLab completed without audio/SRT")
            download(audio_url, out / "voice.wav")
            download(srt_url, out / "subtitles.srt")
            (out / "lucylab.json").write_text(json.dumps({"voiceAlias": args.voice_alias, "speed": args.speed, "projectExportId": export_id}, indent=2), encoding="utf-8")
            return 0
        if state == "failed":
            raise RuntimeError("LucyLab export failed")
        time.sleep(2.5)
    raise TimeoutError("LucyLab export timed out")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
