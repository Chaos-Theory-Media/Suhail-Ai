"""Operator-imported, local reference passages. References are untrusted data, never commands."""
import json
import os
import re
import tempfile
import uuid
from pathlib import Path

from . import paths

MAX_CHUNKS = 400


def folder():
    p = paths.sub('knowledge')
    p.chmod(0o700)
    return p


def documents():
    result = []
    for path in sorted(folder().glob('*.json')):
        if path.is_symlink():
            continue
        try:
            data = json.loads(path.read_text())
            result.append(data)
        except (OSError, ValueError):
            continue
    return result


def inventory():
    return [{k: d[k] for k in ('id', 'title', 'version', 'chunks')} for d in documents()]


def import_document(studio, content, filename, title, version):
    epoch = studio.power_epoch
    if studio.live:
        raise RuntimeError('Import references while production is idle.')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
        raise ValueError('Give this reference a title (at most 120 characters).')
    if not isinstance(version, str) or not 1 <= len(version.strip()) <= 80:
        raise ValueError('Give the application/manual version, or label it as unknown.')
    if not content or len(content) > 6 * 1024**2:
        raise ValueError('Import a nonempty reference of at most 6 MB.')
    suffix = Path(filename).suffix.lower()
    if suffix == '.pdf':
        with tempfile.TemporaryDirectory(prefix='manual-', dir=paths.sub('cache')) as temp:
            source = Path(temp) / 'manual.pdf'
            source.write_bytes(content)
            source.chmod(0o600)
            pages = studio.local_models.run('extract', {'path': str(source)})
    elif suffix in ('.txt', '.md'):
        try:
            pages = [{'page': 1, 'text': content.decode('utf-8')}]
        except UnicodeDecodeError:
            raise ValueError('Text references must use UTF-8 encoding.') from None
    else:
        raise ValueError('Use a text-based PDF, UTF-8 .txt or .md reference.')
    passages = []
    for page in pages:
        text = re.sub(r'\s+', ' ', page['text']).strip()
        for start in range(0, len(text), 1100):
            part = text[start:start + 1400]
            if part:
                passages.append(dict(page=page['page'], text=part))
    if not passages:
        raise ValueError('No readable text found.')
    with studio.lock:
        if not studio.lifecycle.on or epoch != studio.power_epoch or studio.live:
            raise RuntimeError('Studio state changed; this reference was not imported.')
        count = sum(d['chunks'] for d in documents())
        if count + len(passages) > MAX_CHUNKS:
            raise ValueError('Reference library limit is 400 passages; remove unused references or import selected chapters.')
        doc = dict(id=uuid.uuid4().hex, title=title.strip(), version=version.strip(),
                   chunks=len(passages), passages=passages)
        target = folder() / (doc['id'] + '.json')
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(doc, ensure_ascii=False))
        temp.chmod(0o600)
        os.replace(temp, target)
    return inventory()


def remove(doc_id):
    if not re.fullmatch(r'[a-f0-9]{32}', doc_id):
        raise ValueError('Invalid reference identifier.')
    (folder() / (doc_id + '.json')).unlink(missing_ok=True)


def retrieve(studio, query):
    chunks = []
    for doc in documents():
        for passage in doc['passages']:
            chunks.append(dict(title=doc['title'], version=doc['version'], page=passage['page'], text=passage['text']))
    if not chunks:
        return []
    return studio.local_models.run('retrieve', {'query': query[:2000], 'chunks': chunks[:MAX_CHUNKS]}, timeout=120)
