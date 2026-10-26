# Sawti 3.2.0: M1 Ultra local model integration preview

The reported Mac Studio has an Apple M1 Ultra and 128 GB unified memory. This is an appropriate hardware class for the recommended stack below. The actual Mac, its available disk space and OS installation are not accessible from this cloud workspace. The reported “Golden Gate 27.0.1” name/version is operator-supplied; the installer reads the real `sw_vers` value rather than relying on that name.

## Selected stack

| Role | Exact model / runtime | Qualification |
|---|---|---|
| Main assistant | `qwen3:30b-a3b-q4_K_M` through private Ollama | Native M-series support documented; exact tag, Q4_K_M details and tool capability checked on download; Mac latency and bilingual quality pending |
| English/Arabic recognition | `mlx-community/whisper-large-v3-turbo`, `mlx-whisper==0.4.3`, `mlx==0.25.2` | Apple Silicon MLX path; replaces the existing small CPU recogniser when installed; real presenter accuracy/latency pending |
| Reference embeddings | `BAAI/bge-m3` via Sentence Transformers / PyTorch | Multilingual dense retrieval; MPS when available, otherwise CPU; real reference relevance pending |
| Reranking | `BAAI/bge-reranker-v2-m3` via CrossEncoder | Reorders the top 12 passages and supplies four to Qwen; real reference relevance pending |
| Spoken output | Existing installed macOS English/Arabic voices | Retains separately commissioned Scarlett Playback 3–4 output. No new speech synthesis model or routing change |

Whisper is speech **recognition**, not Sawti's speaking voice. A larger model does not supply the missing Audition track/transport adapter, full autonomous recording sequence or a Mic 1 wake listener. Those remain separate work.

The standard Qwen3 4B profile and optional faster-whisper/Resemblyzer features are retained. Changing the chat model in Settings requires OFF. Selecting a model does not download it; downloads happen only during installation. If the enhanced download fails, no automatic substitution is presented as a successful upgrade.

## Compatibility evidence and limits

- Ollama's official macOS documentation specifies macOS 14+ and Apple M-series GPU support. Qwen's official documentation supports local Ollama deployment and warns that unqualified aliases can change model variants. Sawti therefore requests an explicit quantisation tag.
- Apple's MLX Whisper example documents local-path inference. The published `mlx-whisper 0.4.3` source was inspected: its loader uses `weights.safetensors` / `weights.npz`. The installer normalises a downloaded `model.safetensors` filename if needed and rejects non-MLX configurations.
- The BGE maintainer lists BGE-M3 and the v2-M3 reranker as multilingual. The published Sentence Transformers 5.2.0 API was inspected for local-only loading; executable remote model code is disabled and PyTorch models require safetensors.
- **Pinned Python 3.12 Apple Silicon dependencies resolve with binary wheels only.** `requirements-models-macos.lock` records the resolution. Resolution is evidence of package availability, not successful native imports or inference on the Mac.
- The cloud proxy blocks the Ollama and Hugging Face model registries (HTTP 403). No full weights were downloaded or benchmarked here. The Mac installer must resolve and download them; it records immutable Hugging Face revisions in private `runtime/model-profile.json`.
- The full profile requires native arm64 macOS 14+, at least 64 GB memory and 60 GB free before installation. These are conservative Sawti installation policies. The user’s reported 128 GB passes the memory policy. Actual available space remains unknown. The specialist phase requires 15 GB remaining after the chat download.
- Expect tens of GB of downloads/storage; the ZIP contains source, not model weights. Initial downloads require internet; ordinary inference uses private local services, local model paths and offline flags.

Source links and content digests are in [results/sources.json](results/sources.json). Dependency resolution evidence is in [results/dependency-resolution.txt](results/dependency-resolution.txt).

## Install and use without everyday Terminal commands

1. Finish production recording, quit Sawti, extract the 3.2.0 source ZIP into a permanent Documents folder and run `INSTALL_SAWTI.command` by double-clicking it. Retain the previous source as a rollback copy. Existing recordings, templates and learning are preserved.
2. Choose local AI and the **enhanced M1 Ultra / 128 GB profile**. The installer refreshes only Sawti's private signed Ollama, downloads the exact chat model and activates it after model checks. Shared Ollama installations are preserved. The legacy voice/recognition option is separate and optional.
3. The specialist packages install into private `runtime/models-venv`, separate from the working audio/monitoring venv. Hugging Face checkpoints are staged and swapped per model after file-layout validation. A failed role retains its previous files; partial installation is reported and can be retried by rerunning setup. Revisions are resolved at install time, not at every launch.
4. Launch Sawti and switch ON. In **Settings → Local AI models**, refresh status, then run **Test specialist models while idle**. This runs synthetic silence/text through the specialists and requests a short response from Qwen; it does not open microphones or play sound. A pass is a runtime probe, not production qualification.
5. Test English, Arabic and mixed speech using the existing **Tap to speak** button. It still uses the browser-selected microphone. Always-listening/wake-word operation specifically on Mic 1 is not added.
6. Recommission private headset speech through its existing setup if desired. The new recognition model does not change its routing or isolation requirements.

The model worker exits after each task, releasing its memory. This deliberately prioritises ownership, cancellation and isolation over warm-model latency; cold starts may be noticeable. There is one enhanced task at a time, one loaded Ollama model and one parallel Ollama request, with an 8K chat context and short answers. A new request while a specialist is busy is rejected with a retry message; it is not silently queued.

**Enhanced inference is held during Sawti Live until actual Mac performance is qualified.** Built-in fresh-level answers and truthful recording-status guidance remain available. A pending enhanced task also prevents Sawti's Go Live / Record admission until it finishes. These guards cannot observe a recording started manually in another application: run the new checks and enhanced workflows while production is idle. OFF stops owned workers and the private AI service, discards stale results and does not send production Record/Stop or routing commands.

## Local manuals and studio notes

Settings supports importing text-based PDF, UTF-8 text and Markdown with a title and application/manual version. The operator confirms rights and idle production. Manufacturer manuals are **not bundled or automatically scraped**. Import legitimately obtained editions matching Focusrite Control / Scarlett 18i8 3rd Gen, Audition 26.3, Apple Audio MIDI Setup, Zoom and BlackHole. Original files are preserved; extracted copies stay private under Sawti's `knowledge` folder.

Type a question and choose **Ask manuals**. BGE embeds the question and library passages, the reranker selects relevant passages across documents, and Qwen produces one answer with numbered source labels. The normal Send button retains the existing studio intent handling. Retrieval currently embeds the bounded library per query; a persistent vector index is not implemented. Arabic questions can retrieve English passages, subject to actual relevance testing.

Limits: 6 MB per import, at most 500 PDF pages, 600,000 extracted PDF characters and **400 passages across the library**. Import selected chapters if needed; excess capacity is rejected explicitly rather than silently omitted. Text is chunked with overlap. Scanned PDFs require external OCR. Text-file page numbers are always 1. A source label identifies a retrieved passage; it does not independently prove the generated claim is correct. Version conflicts and missing evidence must be checked during acceptance.

Reference text is untrusted data. Reference answers receive no tools and cannot show action buttons, even if a model returns tool calls. Prompt instructions distinguish references from live settings; this is not a guarantee against every misleading generated answer. No chat text, manual content or transcripts are added to the existing redacted learning export. Reviewed engineering notes may be imported manually; an automatic observer of every Focusrite/Audition setting change is not part of this release.

Clean uninstall recognises the owned model-worker identity, private runtime/model/cache trees and the imported reference folder. Selecting data removal moves reference copies to Trash; the original manuals, recording locations and shared tools are preserved.

## Actual Mac acceptance still required

- Verify real OS/architecture, available space, signed Ollama, all downloads/revisions and actual selected tag/quantisation.
- Pass the synthetic check, then measure cold and warm English/Arabic answer and transcription times. Test accents, noise, silence, studio names and mixed-language commands. No model may bypass scoped action approval.
- Check useful cross-document retrieval, correct version handling, citations, insufficient evidence, and hostile instructions embedded in a test reference. No transport/routing action may execute.
- With production idle, create an isolated engineering test session and measure resource use, audio continuity and recorded-file integrity under expected load. Qualify long takes separately; do not infer production readiness from a synthetic model probe.
- Test OFF during each specialist task, a failed download, missing ffmpeg, malformed/encrypted/scanned PDF, busy-model requests, reinstall, fallback selection and clean uninstall.
- Recheck the independently commissioned private speech path and electrical/acoustic recording exclusion. No speaker-quality or isolation claim follows from upgrading recognition.

Automated evidence in `results/` covers Linux simulation, controlled worker substitutions and API/safety logic. It does not establish actual Mac inference, language accuracy, model throughput, Safari behaviour, audio continuity or production readiness.

Final cloud validation: **209 Python tests, 35 JavaScript checks and 56 live HTTP checks passed**. Installer shell syntax and diff whitespace checks passed. The Apple Silicon binary-only dependency resolution contains 39 pinned packages. Raw results are included alongside the source evidence.
