# HANDU autonomous migration

Status: connection preflight only. Automatic rendering and posting are **not enabled**.

The existing repository has separate Douyin intake and LucyLab workflows. Those workflows
do not implement an autonomous HANDU M00–M12 pipeline. ChatGPT skills are instructions,
not an executable GitHub worker; source understanding, faithful Vietnamese scripting,
Chinese subtitle tracking, cleanup, and independent visual QA need an AI service plus
deterministic rendering and validation code.

## Connection setup

Add secrets in repository Settings → Secrets and variables → Actions:

- `GOOGLE_SERVICE_ACCOUNT_JSON`: service-account JSON. Enable Google Sheets API and
  share the configured HANDU Sheet with its `client_email` as Editor.
- `METRICOOL_API_TOKEN`: Metricool API token. Account and brand IDs are already configured.
- `OPENAI_API_KEY`: proposed AI backend for understanding, scripting, and visual QA.
  An API account is billed separately from ChatGPT; select the backend before production.
- `LUCYLAB_API_KEY`: existing LucyLab bridge secret; reuse it rather than copying credentials.

Never commit secret values. The preflight logs only presence and sanitized checks.
It never writes to the Sheet, creates paid TTS, generates AI content, or publishes.
Use the Actions tab to rerun **HANDU Auto Migration Preflight** after adding secrets.

## Locked production requirements

See `config.json`: one link per scan, up to three Reels per day, publication slots
09:00/13:00/19:00 Vietnam time, minimum 60-minute scheduling buffer, Chi Mai voice,
Be Vietnam Pro Bold, and mandatory M12 PASS. An hourly scan at minute 17 UTC is planned;
no scheduled scan is enabled while the production worker is incomplete.

Before enabling production, implement and exercise: durable per-job state and immutable
TTS recovery; queue reconciliation and duplicate protection; verified M00 bytes; M01–M12
source-specific processing and evidence; durable final-MP4 storage and Metricool upload;
slot reconciliation; uncertain-publish recovery without repeating a post; and writeback to
the exact Sheet row. A green authentication check is not an end-to-end production PASS.

Metricool authentication reference: https://app.metricool.com/resources/apidocs/index.html

The pilot PR and installed HANDU skill remain unchanged by this migration preparation.
