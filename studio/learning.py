"""Local, opt-in metadata learning. Never opens or reads recording audio."""
import collections, datetime, json, re, sqlite3, threading, time
from pathlib import Path
BASE=Path(__file__).resolve().parent.parent
STORE=BASE/'local_data'
DB=STORE/'learning.sqlite3'
MEDIA={'.wav','.aif','.aiff','.mp3','.flac','.sesx'}
LOCK=threading.Lock()

def init():
    STORE.mkdir(exist_ok=True)
    with sqlite3.connect(DB) as db:
        db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS observations (path TEXT PRIMARY KEY, directory TEXT, filename TEXT, suffix TEXT, modified REAL, seen REAL)')

def setting(key,default=None):
    init()
    with sqlite3.connect(DB) as db:
        r=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return json.loads(r[0]) if r else default

def save_setting(key,value):
    init()
    with sqlite3.connect(DB) as db: db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,json.dumps(value)))

def configure(root, enabled):
    if enabled:
        p=Path(root).expanduser().resolve()
        if not p.is_dir():raise ValueError('Folder does not exist')
        if p==Path('/'):raise ValueError('Choose a dedicated recording folder')
        save_setting('folder',str(p));save_setting('enabled',True)
    else: save_setting('enabled',False)
    return summary()

def token_shape(name):
    stem=Path(name).stem
    stem=re.sub(r'\d{4}[-_]\d{2}[-_]\d{2}', '{DATE}',stem)
    stem=re.sub(r'\d{8}', '{DATE8}',stem)
    stem=re.sub(r'\d+', '{N}',stem)
    return stem[:120]

def scan(max_files=3000):
    if not setting('enabled',False):return {'scanned':0,'message':'Learning disabled'}
    root=Path(setting('folder',''))
    if not root.is_dir():return {'scanned':0,'message':'Configured folder is unavailable'}
    latest=[]
    try:
        for p in root.rglob('*'):
            try:
                if p.is_file() and p.suffix.lower() in MEDIA and not p.is_symlink():
                    stat=p.stat();latest.append((stat.st_mtime,str(p),str(p.parent),p.name,p.suffix.lower()))
            except (OSError,PermissionError):pass
    except (OSError,PermissionError):pass
    latest=sorted(latest,reverse=True)[:max_files]
    init()
    with LOCK,sqlite3.connect(DB) as db:
        db.executemany('INSERT OR REPLACE INTO observations VALUES (?,?,?,?,?,?)',[(path,directory,name,suffix,mtime,time.time()) for mtime,path,directory,name,suffix in latest])
    return {'scanned':len(latest),'message':'Metadata only; no recording content read'}

def summary():
    init()
    enabled=setting('enabled',False);folder=setting('folder','')
    with sqlite3.connect(DB) as db:
        rows=db.execute('SELECT directory,filename,suffix FROM observations ORDER BY modified DESC LIMIT 3000').fetchall()
    folders=collections.Counter(r[0] for r in rows)
    patterns=collections.Counter(token_shape(r[1]) for r in rows)
    types=collections.Counter(r[2] for r in rows)
    return {'enabled':enabled,'folder':folder,'observations':len(rows), 'top_folders':folders.most_common(5), 'naming_patterns':patterns.most_common(6),'types':types.most_common(6), 'recommendation':{'folder':folders.most_common(1)[0][0] if folders else None,'pattern':patterns.most_common(1)[0][0] if patterns else None},'note':'Suggestions only; learning observes file names, paths and timestamps. It does not change Audition settings.'}
