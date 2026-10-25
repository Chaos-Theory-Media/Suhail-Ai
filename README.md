# Sawti 2.0 | Local Studio Controller

Local developer prototype for Mac Studio (M2 Max / Ultra), Scarlett 18i8, Focusrite Control 2, Adobe Audition, Zoom and BlackHole.

## What works

- Distinct Podcast and Zoom Show tabs and diagnostic profiles.
- CoreAudio device discovery, read-only live input metering subject to macOS input permission and device channel configuration.
- Local specialist health agents and supervised text conversation. Plain-language diagnostics work without any LLM.
- Optional Ollama **local-only** language model for open-ended questions.
- Optional faster-whisper **offline** speech-to-text from a press-to-talk browser recording.
- Opt-in presenter voice enrolment and tentative similarity matching using Resemblyzer. Consent and deletion controls.
- Local recording folder and file-naming analysis from the existing v1.3 learning service.
- Existing photo-style microphone troubleshooting visual.

## What does NOT yet work

- This prototype cannot read physical Scarlett gain-knob positions or 48V states. It can warn on silence during a test, not certify the cause.
- Speaker recognition is *not* authentication. Replay or similar voices can fool it. A local pilot threshold of 0.79 is provisional and MUST be calibrated on your presenters and studio microphone; uncertain identification stays unnamed. No voice-driven destructive actions.
- The UI does not automatically control Audition, Zoom, Focusrite routing, or recording transport. There is no automatic gain correction.
- All detected meters are **peak/RMS**, not calibrated PPM. BlackHole channels require correct Aggregate channel order before meaningful live metering.
- Voice relies on local optional Python dependencies and model downloads. Browser audio MIME support must be tested on your Mac; speech transcription may require ffmpeg for some files.
- "Agentic" means locally orchestrated specialist diagnostic components plus an optional language model, **not** fully autonomous studio operation.

## Install

1. Extract the ZIP to a persistent location, such as your Documents folder.
2. Install Python 3.11 or 3.12 and macOS Command Line Tools if required.
3. In Terminal inside the `Sawti_2_0_Mac` folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

4. Open `http://127.0.0.1:8765`. Allow microphone access for the browser only when using voice commands or enrolment.
5. Stop the existing Sawti v1.x server first, because both use port 8765.

### Optional language model

Install Ollama from https://ollama.com and download a model **once**, for example:

```bash
ollama pull qwen3:4b
```

Sawti connects only to `127.0.0.1:11434`, never to cloud APIs. Do not enable Ollama cloud models for this studio. The model may require internet access for the initial download.

### Optional speech-to-text and presenter recognition

```bash
source .venv/bin/activate
python -m pip install -r requirements-voice.txt
brew install ffmpeg
```

Local faster-whisper downloads its speech model on first use; for offline-only studio operation, preload the model while connected to an approved network. `SAWTI_WHISPER=small` (default). Voice recognition loads a local embedding model on first use. After models are cached, disconnect the network and test voice features end-to-end before relying on offline operation.

**Security and privacy:** Presenter voice biometrics are personal data. Enrol only with informed permission, define local retention and deletion procedures, and obtain applicable legal/privacy approval. Embeddings are stored in `~/Library/Application Support/Sawti/sawti.sqlite3` and are not encrypted by the prototype; use FileVault and limit macOS account access. A production system should encrypt these records separately, provide clear consent records, and validate protection against replay attacks.

## Presenter prompt examples

- Sawti, check the studio before recording.
- Sawti, why is microphone one silent?
- Sawti, check all three microphones and talkback.
- Sawti, is Audition running?
- Sawti, is BlackHole available?
- Sawti, help me test Zoom mix-minus.
- Sawti, tell me what to check before recording.
- Sawti, where do we usually save recordings?
- Sawti, suggest a filename for today's podcast.
- Sawti, how can I check if phantom power is needed?
- Sawti, check the remote guest return level.
- Sawti, what should we do if a microphone clips?
- صوتي، افحص الميكروفونات.
- صوتي، هل برنامج أوديشن يعمل؟
- صوتي، افحص إعدادات زوم.

The sample prompts are conversation starters, not a guarantee that the corresponding hardware operation is implemented.

## Operational precautions

- Use a short mic sound check with an operator before every session.
- Do not assume mic silence means the physical gain knob is at zero.
- Do not restart audio hardware or change Aggregate routing during an active recording.
- Preserve Focusrite Control 2 presets and documented physical wiring before future automation upgrades.
- Use manual confirmation for talkback isolation and Zoom mix-minus.
- Speaker output 1-2 and line outputs 3-4 remain unchanged.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Sawti 2.1 safe ON/OFF mode
- Application starts in **OFF** mode. Open localhost:8765 and click SWITCH SAWTI ON to enable diagnostic endpoints and start a **Sawti-owned** Ollama process on 127.0.0.1:11439 if the Ollama executable is installed.
- Qwen model downloads and Python package installation are **not automatic**. Install the model first with `ollama pull qwen3:4b` (Ollama's standard service); Sawti-owned service can then access the same local model files.
- ON never opens microphone capture automatically. Click Start metering when safe to test; browser mic use is also initiated explicitly.
- OFF stops the Sawti meter stream and the **Sawti-owned** Ollama process; it does not touch external Ollama sessions, Focusrite Control, BlackHole, Adobe Audition, or Zoom.
- The lightweight local Sawti control webpage/server remains on so you can switch ON again. To close even the control webpage/backend, press Control+C in the Terminal running Sawti. Closing the browser alone does not stop the backend.
- Do not enable Sawti during live production until verified on your Mac Studio. Do not change audio routing during an active recording.


## Sawti 2.2 assisted AI installation
Run `INSTALL_SAWTI.command` first. On explicit confirmation it downloads official Ollama macOS application into `~/Library/Application Support/Sawti/runtime/`, creates a local Python environment, and downloads `qwen3:4b` into `~/Library/Application Support/Sawti/models/`. No existing `/Applications/Ollama.app` is overwritten. `START_SAWTI.command` launches Sawti; ON starts a dedicated, Sawti-owned Ollama service using those model files, OFF stops that service. Initial downloads require network access; no model weights are bundled in ZIP. Optional voice dependencies are not part of assisted setup. Apple Silicon and Python 3.11/3.12 required. Safety: test while studio idle, do not use on-air until validated.
