"""Installer-only network access and model activation. Never run at app startup."""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sawti import models, paths  # noqa: E402


def save_profile(data):
    target = paths.install_dir() / 'runtime/model-profile.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2))
    tmp.chmod(0o600)
    os.replace(tmp, target)


def activate_chat(tag):
    import urllib.request
    from sawti import store
    if tag not in models.CHAT_MODELS:
        raise ValueError('Unsupported chat model.')
    # Caller must own the installer Ollama process; no shared port service is started here.
    req = urllib.request.Request('http://127.0.0.1:11439/api/show',
                                 data=json.dumps({'model': tag}).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as response:
        info = json.load(response)
    if tag == models.CHAT_MODEL:
        details = info.get('details', {})
        if details.get('quantization_level') != 'Q4_K_M' or 'qwen3' not in details.get('family', ''):
            raise RuntimeError('Downloaded model is not the expected Qwen3 Q4_K_M model; existing selection retained.')
        if 'tools' not in info.get('capabilities', []):
            raise RuntimeError('Downloaded model does not advertise tool support; existing selection retained.')
    data = models.profile()
    data.update(chat_model=tag, chat_details=info.get('details', {}), mac_qualified=False)
    save_profile(data)
    store.put('llm_model', tag)
    print('Selected verified local model:', tag)


def install_specialists():
    from huggingface_hub import model_info, snapshot_download
    # Import checks do not qualify audio hardware or voice accuracy.
    import mlx.core  # noqa: F401
    import mlx_whisper  # noqa: F401
    import sentence_transformers  # noqa: F401
    import pypdf  # noqa: F401
    check = models.compatibility(required_free_gb=15)
    if not check['eligible']:
        raise RuntimeError(' '.join(check['reasons']))
    data = models.profile()
    records = data.setdefault('specialists', {})
    parent = paths.install_dir() / 'models/specialists'
    parent.mkdir(parents=True, exist_ok=True)
    for role, repo in models.REPOSITORIES.items():
        print('Downloading', repo, flush=True)
        info = model_info(repo)
        revision = info.sha
        if not revision:
            raise RuntimeError('Could not resolve an immutable model revision.')
        with tempfile.TemporaryDirectory(prefix='.download-', dir=parent) as folder:
            staged = Path(folder) / 'model'
            snapshot_download(repo_id=repo, revision=revision, local_dir=str(staged), max_workers=4,
                              allow_patterns=['*.json', '*.safetensors', '*.npz', '*.model', '*.tiktoken',
                                              '*.txt', '*.md', 'LICENSE*'],
                              ignore_patterns=['onnx/*', 'openvino/*', '*/onnx/*', '*.py'])
            # mlx-whisper 0.4.3 expects weights.*, rather than model.safetensors.
            if role == 'speech' and (staged / 'model.safetensors').is_file() and not (staged / 'weights.safetensors').exists():
                (staged / 'model.safetensors').rename(staged / 'weights.safetensors')
            weights = ('weights.safetensors', 'weights.npz') if role == 'speech' else ('model.safetensors',)
            if not (staged / 'config.json').is_file() or not any((staged / name).is_file() for name in weights):
                raise RuntimeError('Model layout is unsupported; existing model retained: ' + repo)
            if role == 'speech' and 'n_audio_ctx' not in json.loads((staged / 'config.json').read_text()):
                raise RuntimeError('Speech checkpoint is not in the required MLX Whisper format.')
            dest, backup = models.specialist_path(role), Path(folder) / 'previous'
            if dest.exists():
                dest.rename(backup)
            try:
                staged.rename(dest)
            except Exception:
                if backup.exists():
                    backup.rename(dest)
                raise
            records[role] = dict(repository=repo, revision=revision, runtime_tested=False)
            save_profile(data)
    print('All specialist files downloaded. Run the in-app local model check before studio use.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--specialists', action='store_true')
    parser.add_argument('--activate-chat', choices=models.CHAT_MODELS)
    args = parser.parse_args()
    try:
        if args.check:
            result = models.compatibility()
            print(json.dumps(result))
            sys.exit(0 if result['eligible'] else 1)
        if args.specialists:
            install_specialists()
        if args.activate_chat:
            activate_chat(args.activate_chat)
    except Exception as exc:
        print('Model setup incomplete:', str(exc), file=sys.stderr)
        sys.exit(1)
