# V3.4 Web Control Plane Architecture

ChatGPT Web creates the narration, reads the real LucyLab timing artifact, builds and locks the storyboard, and generates one 1080x1920 source page image per storyboard page. GitHub Actions does not require an OpenAI API key. GitHub owns LucyLab TTS, timing artifacts, deterministic line-to-color reveal, drawing-hand animation, hold/erase transitions, captions, encoding, and machine QC.

Production source images must use `sourceMethod: chatgpt-web-image-generation` and be committed before the production job is dispatched.
