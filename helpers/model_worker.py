"""One private, offline specialist task. Never opens audio devices or calls studio actions."""
import gc
import json
import sys
from pathlib import Path


def retrieve(models, payload):
    import numpy as np
    import torch
    from sentence_transformers import CrossEncoder, SentenceTransformer
    torch.set_num_threads(2)
    device = 'mps' if torch.backends.mps.is_available() else 'cpu'
    chunks = payload['chunks']
    embedder = SentenceTransformer(str(models / 'embedding'), device=device, local_files_only=True,
                                  trust_remote_code=False, model_kwargs={'use_safetensors': True})
    embedder.max_seq_length = 512
    vectors = embedder.encode([payload['query']] + [c['text'] for c in chunks], batch_size=4,
                             normalize_embeddings=True, show_progress_bar=False)
    scores = vectors[1:] @ vectors[0]
    indices = np.argsort(scores)[::-1][:12].tolist()
    candidates = [chunks[i] for i in indices]
    del embedder, vectors
    gc.collect()
    if device == 'mps':
        torch.mps.empty_cache()
    reranker = CrossEncoder(str(models / 'reranker'), device=device, max_length=512,
                           trust_remote_code=False, local_files_only=True,
                           model_kwargs={'use_safetensors': True})
    ranked = reranker.predict([(payload['query'], c['text']) for c in candidates], batch_size=2,
                              show_progress_bar=False)
    order = np.argsort(np.asarray(ranked).reshape(-1))[::-1][:4].tolist()
    return [candidates[i] for i in order]


def execute(request):
    payload, models = request['payload'], Path(request['models'])
    if request['operation'] == 'transcribe':
        import mlx_whisper
        result = mlx_whisper.transcribe(payload['path'], path_or_hf_repo=str(models / 'speech'),
                                        language=payload.get('language'), verbose=False,
                                        condition_on_previous_text=False, fp16=True)
        return {'text': result['text'].strip()}
    if request['operation'] == 'retrieve':
        return retrieve(models, payload)
    if request['operation'] == 'selftest':
        import numpy as np
        import mlx_whisper
        # Synthetic silence, no microphone, output device or production session.
        mlx_whisper.transcribe(np.zeros(16000, dtype=np.float32), path_or_hf_repo=str(models / 'speech'),
                               language='en', verbose=False, fp16=True, condition_on_previous_text=False)
        # Drop MLX's cached model before exercising the document models.
        from mlx_whisper.transcribe import ModelHolder
        ModelHolder.model = None
        gc.collect()
        result = retrieve(models, {'query': 'headphone outputs', 'chunks': [
            {'text': 'Headphone monitoring uses a separate output pair.'},
            {'text': 'Recordings are stored in the session folder.'}]})
        if len(result) != 2:
            raise RuntimeError('Model probe failed.')
        return {'passed': True, 'hardware_qualified': False,
                'message': 'Speech, embedding and reranker inference completed using synthetic data. Studio audio and language accuracy still need testing.'}
    if request['operation'] == 'extract':
        from pypdf import PdfReader
        reader = PdfReader(payload['path'])
        if reader.is_encrypted or len(reader.pages) > 500:
            raise ValueError('Use an unencrypted manual with at most 500 pages.')
        pages, total = [], 0
        for number, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or '').strip()
            total += len(text)
            if total > 600_000:
                raise ValueError('This manual is too large; import the relevant chapters separately.')
            if text:
                pages.append({'page': number, 'text': text})
        if not pages:
            raise ValueError('No selectable text found. Scanned manuals need OCR before import.')
        return pages
    raise ValueError('Unknown operation.')


if __name__ == '__main__':
    try:
        result = {'ok': True, 'result': execute(json.loads(Path(sys.argv[1]).read_text()))}
    except ValueError as exc:
        result = {'ok': False, 'error': str(exc)}
    except Exception:
        result = {'ok': False, 'error': 'Specialist inference failed. Check the installed model files and Mac compatibility.'}
    output = Path(sys.argv[2])
    output.write_text(json.dumps(result, ensure_ascii=False))
    output.chmod(0o600)
