#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RUNNER_VERSION = "3.4.0"
FORBIDDEN_PROVIDERS = {"local-doodle", "local-doodle-v2", "procedural", "pil", "opencv", "svg", "icon-library"}


def parse_timestamp(value: str) -> int:
    h, m, rest = value.strip().replace('.', ',').split(':')
    s, ms = rest.split(',')
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms.ljust(3, '0')[:3])


def parse_srt(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", text.strip())
    cues = []
    for block in blocks:
        lines = [x.strip() for x in block.splitlines() if x.strip()]
        if len(lines) < 2:
            continue
        time_line = lines[1] if '-->' in lines[1] else lines[0]
        if '-->' not in time_line:
            continue
        start, end = [x.strip() for x in time_line.split('-->', 1)]
        body_start = 2 if time_line == lines[1] else 1
        cues.append({
            "index": len(cues) + 1,
            "startMs": parse_timestamp(start),
            "endMs": parse_timestamp(end),
            "text": " ".join(lines[body_start:]),
        })
    if not cues:
        raise RuntimeError("SRT contains no cues")
    return cues


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_common(job: dict) -> None:
    if int(job.get("schemaVersion", 0)) != 3:
        raise SystemExit("JOB_CONTRACT_ERROR: schemaVersion must be 3")
    if str(job.get("runnerVersion") or RUNNER_VERSION) != RUNNER_VERSION:
        raise SystemExit("JOB_CONTRACT_ERROR: runnerVersion must be 3.4.0")
    if job.get("enabled") is not True:
        raise SystemExit("JOB_CONTRACT_ERROR: job must be enabled")


def run_timing(job: dict, out: Path, root: Path) -> None:
    script = str(job.get("script") or "").strip()
    if not script:
        raise SystemExit("JOB_CONTRACT_ERROR: timing job script is empty")
    voice = str(job.get("voiceAlias") or "co-nhan")
    speed = float(job.get("voiceSpeed", 1.0))
    audio_dir = out / "audio"
    subprocess.run([
        sys.executable,
        str(root / "automation/lucylab_bridge.py"),
        "--text", script,
        "--voice-alias", voice,
        "--speed", str(speed),
        "--out", str(audio_dir),
    ], check=True)
    cues = parse_srt(audio_dir / "subtitles.srt")
    write_json(out / "timing/timing.json", {
        "jobId": job.get("jobId"),
        "voiceAlias": voice,
        "voiceSpeed": speed,
        "cueCount": len(cues),
        "durationMs": cues[-1]["endMs"],
        "cues": cues,
    })
    write_json(out / "status.json", {
        "state": "completed",
        "runnerVersion": RUNNER_VERSION,
        "execution": "github-actions",
        "stage": "timing",
        "jobId": job.get("jobId"),
        "voiceAlias": voice,
    })


def require_production_contract(job: dict, root: Path) -> None:
    if not isinstance(job.get("timingRunId"), int):
        raise SystemExit("JOB_CONTRACT_ERROR: production job requires integer timingRunId")
    storyboard = job.get("storyboard") or {}
    if storyboard.get("locked") is not True:
        raise SystemExit("JOB_CONTRACT_ERROR: storyboard must be locked")
    pages = storyboard.get("pages") or []
    if not pages:
        raise SystemExit("JOB_CONTRACT_ERROR: storyboard pages are empty")
    visual = job.get("visual") or {}
    if visual.get("providerPolicy") != "image-generation-only":
        raise SystemExit("JOB_CONTRACT_ERROR: providerPolicy must be image-generation-only")
    provider = os.environ.get("VISUAL_PROVIDER", "").strip().lower()
    if not provider:
        raise SystemExit("RUNNER_NOT_READY: VISUAL_PROVIDER is not configured")
    if provider in FORBIDDEN_PROVIDERS:
        raise SystemExit(f"RUNNER_POLICY_ERROR: forbidden source provider {provider}")
    required_assets = [
        root / "assets/main-character-sheet.png",
        root / "assets/approved-visual-reference-01.png",
        root / "assets/approved-visual-reference-02.png",
        root / "assets/drawing-hand.png",
        root / "assets/eraser-hand.png",
    ]
    missing = [str(p.relative_to(root)) for p in required_assets if not p.exists()]
    if missing:
        raise SystemExit("RUNNER_NOT_READY: missing approved assets: " + ", ".join(missing))


def run_production(job: dict, out: Path, root: Path) -> None:
    require_production_contract(job, root)
    # V3.4 intentionally refuses to fall back to the V3.3 local-doodle renderer.
    # The image-generation provider adapter and full render engine must be installed here.
    write_json(out / "status.json", {
        "state": "blocked",
        "runnerVersion": RUNNER_VERSION,
        "execution": "github-actions",
        "stage": "production",
        "jobId": job.get("jobId"),
        "sourcePolicy": "image-generation-only",
        "reason": "production visual-model adapter not installed yet",
    })
    raise SystemExit("RUNNER_NOT_READY: V3.4 production visual-model adapter is not installed yet; no procedural fallback is allowed")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[2]
    job = json.loads(Path(args.job).read_text(encoding="utf-8"))
    validate_common(job)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stage = str(job.get("stage") or "")
    if stage == "timing":
        run_timing(job, out, root)
        return 0
    if stage == "production":
        run_production(job, out, root)
        return 0
    raise SystemExit("JOB_CONTRACT_ERROR: stage must be timing or production")


if __name__ == "__main__":
    raise SystemExit(main())
