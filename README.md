# Whiteboard V3.4 Runner

GitHub production runner for the **Tạo video bảng trắng V3.4** ChatGPT Skill.

This repository is intentionally isolated from the Work/local pipeline of **Whiteboard Story Cổ Nhân** and from the V3.3 production repo.

## Architecture

V3.4 uses ChatGPT Web as the visual/storyboard control plane and GitHub Actions as the heavy production plane:

1. ChatGPT writes the narration.
2. GitHub `timing` runs LucyLab TTS first and returns the real `voice.wav`, `subtitles.srt`, and timing metadata in `whiteboard-v34-timing`.
3. ChatGPT reads that real timing, splits pages semantically without cutting an SRT cue, builds the storyboard, visually generates one 1080x1920 hand-drawn editorial-sketch source page per page, checks the sources, and locks the storyboard.
4. ChatGPT commits the locked storyboard job and source PNGs to this repository.
5. GitHub `production` downloads the exact timing artifact, validates the storyboard/source contract, performs masks, line-to-color reveal, drawing-hand animation, silent hold/eraser transitions, captions, FFmpeg encoding and machine QC, then returns `whiteboard-v34-current`.
6. ChatGPT performs the independent final vision gate before delivery.

GitHub does **not** require an OpenAI API key or any visual-provider API key. Source artwork must come from ChatGPT Web image generation. If Web image generation is unavailable, production must stop; never fall back to local-doodle, flat vector, icons or procedural source artwork.

## Production contract

- Branch: `main`
- Job path: `automation/jobs/current.json`
- Workflow: `.github/workflows/whiteboard-production-v34.yml`
- Workflow name: `Whiteboard Production V3.4`
- Runner version: `3.4.0`
- Timing artifact: `whiteboard-v34-timing`
- Production artifact: `whiteboard-v34-current`
- Source method: `chatgpt-web-image-generation`

## Required GitHub configuration

Only one repository secret is required:

- `LUCYLAB_API_KEY`

No `OPENAI_API_KEY`, `VISUAL_API_KEY`, or `VISUAL_PROVIDER` is required.

## Visual references

Approved visual references and the Cổ Nhân character sheet belong in the ChatGPT Skill bundle so ChatGPT Web can use them while generating source pages. They are not visual-provider dependencies of the GitHub runner.

The GitHub renderer owns only deterministic production assets such as drawing/eraser overlays. Source illustrations must never be drawn by PIL/OpenCV/SVG/procedural code.

## Hard gates

Production must pass all of these before the artifact is considered machine-complete:

- `automation/v34/validate_storyboard_contract.py`
- source image and source visual-QC validation
- mask ownership/coverage and caption-zone validation
- `automation/v34/validate_project.py`
- `ffprobe` stream checks
- full-frame FFmpeg decode
- zero residual artwork after every erase transition
- locked storyboard included in `project.zip`

A successful GitHub job is still not FINAL until ChatGPT Web visually checks semantic order, approved sketch style, character consistency, drawing hand, line-before-color, captions, eraser cleanup and the end of the final video.
