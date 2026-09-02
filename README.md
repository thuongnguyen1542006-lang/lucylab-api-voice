# Whiteboard V3.4 Runner

GitHub-only production runner for the **Tạo video bảng trắng V3.4** ChatGPT Skill.

This repository is intentionally isolated from:

- `skyred1205/whiteboard-story-runner`
- the Work/local pipeline of **Whiteboard Story Cổ Nhân**

## Architecture

V3.4 uses two GitHub phases:

1. **timing** — LucyLab TTS + real SRT first, producing `whiteboard-v34-timing`.
2. **production** — reuse the exact timing run, then generate source artwork with an approved visual model, render line→color, drawing hand, silent eraser transitions, captions and QC, producing `whiteboard-v34-current`.

The skill must never fabricate timing and must never fall back to local-doodle, icon, vector or Work/local rendering.

## Production contract

- Branch: `main`
- Job path: `automation/jobs/current.json`
- Workflow: `.github/workflows/whiteboard-production-v34.yml`
- Workflow name: `Whiteboard Production V3.4`
- Runner version: `3.4.0`

## Required GitHub configuration

### Secrets

- `LUCYLAB_API_KEY` — required for timing stage.
- `VISUAL_API_KEY` — reserved for the approved image-generation provider used by production.

### Repository variable

- `VISUAL_PROVIDER` — must identify the approved visual-model adapter. Forbidden values include `local-doodle`, `procedural`, `pil`, `opencv`, `svg`, and `icon-library`.

## Required approved assets before production

The production engine must have these exact files:

- `assets/main-character-sheet.png`
- `assets/approved-visual-reference-01.png`
- `assets/approved-visual-reference-02.png`
- `assets/drawing-hand.png`
- `assets/eraser-hand.png`

If any approved visual reference or visual provider is missing, production must fail `RUNNER_NOT_READY`; no procedural fallback is allowed.

## Current bootstrap state

- Isolated repo: ready.
- Timing stage: implemented.
- Workflow/job contract: implemented.
- Production visual-model adapter: intentionally **not copied from V3.3** because V3.3 used local-doodle and a broken portable character asset. V3.4 will only become production-ready after an approved visual-model adapter and approved reference images are installed.
