"""Incremental import, bounded candidate discovery and AI scoring.

Rows and scored pairs are published in short transactions. Pair numbers only
append: reviewing a pair can never retarget that decision when more arrive.
One scan owns .scan.lock; short .lock sections serialize review/model writes.
"""
import hashlib
import json
import time
import uuid
from pathlib import Path
import numpy as np
import ai_model as ai
import storage
import twin_core as core

ALIASES = {
    'title': {'title', 'publicationtitle', 'articletitle', 'papertitle'},
    'authors': {'authors', 'author', 'authornames', 'creators'},
    'venue': {'venue', 'journal', 'publicationvenue', 'conference'},
    'year': {'year', 'publicationyear', 'pubyear'},
}


def detect_mapping(columns):
    """Never silently choose between two plausible columns."""
    mapping, ambiguous = {}, []
    for field, aliases in ALIASES.items():
        matches = [c for c in columns if ''.join(ch for ch in c.casefold() if ch.isalnum()) in aliases]
        mapping[field] = matches[0] if len(matches) == 1 else None
        if len(matches) > 1 or (field == 'title' and not matches):
            ambiguous.append(field)
    return mapping, ambiguous


def identity(source, mapping):
    source = Path(source).resolve(); st = source.stat()
    return {'path': str(source), 'size': st.st_size, 'mtime': st.st_mtime_ns, 'mapping': mapping}


def _get(db, key):
    return json.loads(db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])


def _put(db, key, value):
    db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, json.dumps(value)))


def initialize(source, job, mapping, maximum, budget):
    if not 1 <= maximum <= 100000 or not 1 <= budget <= 3000000:
        raise ValueError('Use 1–100000 review pairs and 1–3000000 comparisons.')
    job = Path(job); job.mkdir(parents=True, exist_ok=True)
    with storage.job_lock(job, wait=5):
        db = storage.connect(job/'records.sqlite')
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY, payload TEXT NOT NULL, title TEXT NOT NULL, origin TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS records_title ON records(title,id);
                CREATE TABLE IF NOT EXISTS tokens(token TEXT NOT NULL,id INTEGER NOT NULL,PRIMARY KEY(token,id)) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS token_counts(token TEXT PRIMARY KEY,n INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS embeddings(id INTEGER PRIMARY KEY,vector BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS title_embeddings(title TEXT PRIMARY KEY,vector BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS pair_features(a INTEGER,b INTEGER,value TEXT NOT NULL,PRIMARY KEY(a,b)) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS pending_pairs(seq INTEGER PRIMARY KEY,a INTEGER,b INTEGER,sim REAL,cross_source INTEGER,UNIQUE(a,b));
                CREATE INDEX IF NOT EXISTS pending_rank ON pending_pairs(cross_source DESC,sim DESC,seq);
            ''')
            existing = db.execute("SELECT value FROM meta WHERE key='pipeline'").fetchone()
            if existing:
                state = json.loads(existing[0])
                if state['identity'] != identity(source, mapping):
                    raise ValueError('Source file or mapping changed. Open it as a new dataset.')
                return
            if db.execute('SELECT count(*) FROM records').fetchone()[0]:
                raise ValueError('This is an existing legacy job. Open it instead of importing into it.')
            columns = storage.peek_columns(source); storage.validate_mapping(mapping, columns)
            job_id = uuid.uuid4().hex
            meta = {'filename': Path(source).name, 'sha256': None, 'source_bytes': Path(source).stat().st_size,
                    'columns': columns, 'mapping': mapping, 'records': 0, 'created': core.now(),
                    'storage_version': 2, 'engine': core.ENGINE_VERSION, 'job_id': job_id,
                    'feedback_seed': hashlib.sha256(job_id.encode()).hexdigest(), 'import_complete': False}
            stats = {'records': 0, 'comparison_budget': budget, 'iterations': 0, 'compared_pairs': 0,
                     'oversized_token_blocks': 0, 'budget_reached': False, 'max_pairs': maximum,
                     'eligible_pairs': 0, 'returned_pairs': 0, 'queue_truncated': False,
                     'retrieval': 'incremental-v1: prior exact titles and up to 3 rare token blocks; 32 prior records per input row; ready buffer 50; unscored cross-source candidates prioritized when source column exists',
                     'title_prefilter': .5, 'scan_complete': False}
            model = ai.load_base()
            session = {'schema': 1, 'engine': core.ENGINE_VERSION, 'dataset_sha256': None, 'dataset_id': job_id,
                       'mapping': mapping, 'pairs': [], 'candidate_stats': stats, 'events': [], 'updates': [],
                       'created': core.now(), 'ai_model': model, 'model_history': [model], 'model_actions': [],
                       'proposals': [], 'review_revision': 0, 'ai_ready': False, 'progressive': True}
            state = {'identity': identity(source, mapping), 'offset': 0, 'count': 0, 'columns': columns,
                     'status': 'scanning', 'eof': False, 'elapsed_seconds': 0.0,
                     'first_pair_seconds': None, 'first_50_seconds': None}
            _put(db, 'dataset', meta); _put(db, 'live_session', session); _put(db, 'pipeline', state)
            db.commit()
        finally:
            db.close()


def _discover(db, index, title, origin, stats, queued):
    """Each new row is compared against older rows, including prior chunks.

    This intentionally differs from legacy global ranking. The bounded queue
    retains discovery order and is not a set of globally highest-scoring pairs.
    """
    if not title or stats['budget_reached']:return queued
    exact = [r[0] for r in db.execute('SELECT id FROM records WHERE title=? AND id<? ORDER BY id LIMIT 101', (title, index))]
    exact_candidates = set(exact[:32] if len(exact) <= 100 else exact[:1])
    hits = {i:0 for i in exact_candidates}; cross = {}
    blocks = []
    for token in core.tokens(title):
        row = db.execute('SELECT n FROM token_counts WHERE token=?', (token,)).fetchone()
        count = row[0] if row else 0
        if count > 100: stats['oversized_token_blocks'] += 1
        if 0 < count <= 100: blocks.append((count, token))
    for _, token in sorted(blocks)[:3]:
        for other, prior_origin in db.execute('SELECT t.id,r.origin FROM tokens t JOIN records r ON r.id=t.id WHERE t.token=? AND t.id<? ORDER BY t.id LIMIT 100',(token,index)):
            hits[other]=hits.get(other,0)+1
            cross[other]=int(bool(origin and prior_origin and origin!=prior_origin))
    ranked = []
    # A per-row allowance prevents the early source from consuming the entire
    # global budget on this benchmark. Exact titles and multi-token evidence
    # are preferred; source provenance breaks ties, never sets a match label.
    ordered = sorted(hits,key=lambda i:(-int(i in exact_candidates),-hits[i],-cross.get(i,0),i))[:32]
    for other in ordered:
        if stats['iterations'] >= stats['comparison_budget']:
            stats['budget_reached'] = True; break
        stats['iterations'] += 1
        prior, prior_origin = db.execute('SELECT title,origin FROM records WHERE id=?', (other,)).fetchone()
        size = max(len(title), len(prior))
        if not size or abs(len(title)-len(prior))/size >= .5: continue
        stats['compared_pairs'] += 1
        sim = 1 - core.Levenshtein.distance(title, prior)/size
        if sim > .5: ranked.append((sim, other, int(bool(origin and prior_origin and origin!=prior_origin))))
    stats['eligible_pairs'] += len(ranked)
    for sim, other, cross_source in ranked:
        queued += db.execute('INSERT OR IGNORE INTO pending_pairs(a,b,sim,cross_source) VALUES(?,?,?,?)',(other,index,sim,cross_source)).rowcount
    return queued


def _score(job, encoder, cancel, elapsed, progress):
    """Score at most 50 pending pairs outside the writer lock, then publish."""
    db = storage.connect(Path(job)/'records.sqlite')
    try:
        session = _get(db,'live_session')
        limit = min(50,session['candidate_stats']['max_pairs']-len(session['pairs']))
        pairs = db.execute('SELECT seq,a,b FROM pending_pairs ORDER BY cross_source DESC,sim DESC,seq LIMIT ?', (max(0,limit),)).fetchall()
        if not pairs: return encoder, False
        ids = sorted({i for _, a, b in pairs for i in (a,b)})
        rows = {i: db.execute('SELECT payload,title FROM records WHERE id=?',(i,)).fetchone() for i in ids}
        unique = list(dict.fromkeys(rows[i][1] for i in ids))
        vectors = {}
        for title in unique:
            row = db.execute('SELECT vector FROM title_embeddings WHERE title=?',(title,)).fetchone()
            if row: vectors[title] = np.frombuffer(row[0],dtype=np.float32)
        missing = [t for t in unique if t not in vectors]
        if missing:
            if encoder is None:
                if progress: progress('Loading AI model; the first matches will appear shortly…')
                encoder = ai.Encoder()
            for start in range(0,len(missing),8):
                storage.check_cancel(cancel)
                texts = missing[start:start+8]
                vectors.update(zip(texts, encoder.encode(texts,8)))
        storage.check_cancel(cancel)
        with storage.job_lock(job, wait=5):
            session = _get(db,'live_session'); meta = _get(db,'dataset'); state = _get(db,'pipeline')
            mapping = meta['mapping']
            for title in missing:
                db.execute('INSERT OR IGNORE INTO title_embeddings VALUES(?,?)',(title,vectors[title].astype(np.float32).tobytes()))
            for i in ids:
                db.execute('INSERT OR IGNORE INTO embeddings VALUES(?,?)',(i,vectors[rows[i][1]].astype(np.float32).tobytes()))
            for seq,a,b in pairs:
                records = [{k:json.loads(rows[i][0]).get(mapping[k],'') if mapping[k] else '' for k in core.FIELDS} for i in (a,b)]
                values = ai.features(*records,vectors[rows[a][1]],vectors[rows[b][1]])
                db.execute('INSERT OR IGNORE INTO pair_features VALUES(?,?,?)',(a,b,json.dumps(values.tolist())))
                session['pairs'].append([a,b])
                db.execute('DELETE FROM pending_pairs WHERE seq=?',(seq,))
            session['ai_ready'] = True
            session['candidate_stats']['returned_pairs'] = len(session['pairs'])
            now = elapsed()
            if state['first_pair_seconds'] is None: state['first_pair_seconds'] = now
            if len(session['pairs']) >= 50 and state['first_50_seconds'] is None: state['first_50_seconds'] = now
            state['elapsed_seconds'] = now
            _put(db,'live_session',session); _put(db,'pipeline',state); db.commit()
        if progress: progress(f"{len(session['pairs']):,} AI-scored pairs ready · {meta['records']:,} records read · scan continues")
        return encoder, True
    finally:
        db.close()


def run(source, job, mapping=None, max_pairs=10000, budget=3000000, progress=None, cancel=None, encoder=None):
    source = Path(source).resolve(); job = Path(job)
    if mapping is None:
        mapping, ambiguous = detect_mapping(storage.peek_columns(source))
        if ambiguous: raise ValueError('Please confirm these column mappings: '+', '.join(ambiguous))
    # A separate scanner lock prevents two imports, while allowing human review
    # to take the ordinary writer lock between short published batches.
    with storage.job_lock(job, name='.scan.lock'):
        initialize(source,job,mapping,max_pairs,budget)
        db = storage.connect(job/'records.sqlite')
        state = _get(db,'pipeline'); began = time.perf_counter(); prior_elapsed = state['elapsed_seconds']
        elapsed = lambda: prior_elapsed + time.perf_counter()-began
        try:
            if state['status'] == 'complete': return snapshot(job)
            position = [state['offset']]
            reader = storage.source_rows(source,state['offset'],state['columns'],position)
            eof = state['eof']
            while not eof:
                storage.check_cancel(cancel)
                batch = []
                for _ in range(250):
                    try: batch.append(next(reader))
                    except StopIteration: eof = True; break
                with storage.job_lock(job, wait=5):
                    meta = _get(db,'dataset'); state = _get(db,'pipeline'); session = _get(db,'live_session')
                    queued = len(session['pairs']) + db.execute('SELECT count(*) FROM pending_pairs').fetchone()[0]
                    stats = session['candidate_stats']
                    for row in batch:
                        storage.check_cancel(cancel)
                        index = meta['records']; title = core.norm(row.get(mapping['title']))
                        for key in row:
                            if key not in meta['columns']: meta['columns'].append(key)
                        storage.validate_columns(meta['columns'])
                        origin=str(row.get('source','')).strip()
                        queued = _discover(db,index,title,origin,stats,queued)
                        db.execute('INSERT INTO records VALUES(?,?,?,?)',(index,json.dumps(row,ensure_ascii=False),title,origin))
                        for token in core.tokens(title):
                            db.execute('INSERT INTO tokens VALUES(?,?)',(token,index))
                            db.execute('INSERT INTO token_counts VALUES(?,1) ON CONFLICT(token) DO UPDATE SET n=n+1',(token,))
                        meta['records'] += 1
                    # Bound the unscored disk reservoir; published/reviewed pairs are never evicted.
                    pending_count=db.execute('SELECT count(*) FROM pending_pairs').fetchone()[0]
                    if pending_count>100000:
                        db.execute('DELETE FROM pending_pairs WHERE seq IN (SELECT seq FROM pending_pairs ORDER BY cross_source DESC,sim DESC,seq LIMIT -1 OFFSET 100000)')
                        stats['reservoir_truncated']=True
                    stats['records'] = meta['records']
                    state.update(count=meta['records'],offset=position[0],columns=meta['columns'],eof=eof,status='scanning',elapsed_seconds=elapsed())
                    _put(db,'dataset',meta); _put(db,'live_session',session); _put(db,'pipeline',state); db.commit()
                if progress: progress(f"Read {meta['records']:,} records · {len(session['pairs']):,} pairs ready · scanning")
                storage.space_check(job)
                reviewed=sum(e['decision']!='skip' for e in core.latest_decisions(session).values())
                if len(session['pairs'])-reviewed < 50:
                    encoder, _ = _score(job,encoder,cancel,elapsed,progress)
            reader.close()
            while True:
                storage.check_cancel(cancel)
                encoder, did_work = _score(job,encoder,cancel,elapsed,progress)
                if not did_work: break
            if progress: progress('Finishing source integrity check; ready pairs remain available for review…')
            digest = storage.file_hash(source,cancel)
            if identity(source,mapping) != state['identity']:
                raise ValueError('Source changed during processing. Start a new dataset; export is blocked for this run.')
            with storage.job_lock(job, wait=5):
                meta = _get(db,'dataset'); session = _get(db,'live_session'); state = _get(db,'pipeline')
                meta.update(sha256=digest,import_complete=True)
                session['dataset_sha256'] = digest
                session['candidate_stats']['scan_complete'] = True
                pending=db.execute('SELECT count(*) FROM pending_pairs').fetchone()[0]
                session['candidate_stats']['unselected_candidates']=pending
                session['candidate_stats']['queue_truncated']=pending>0 or session['candidate_stats'].get('reservoir_truncated',False)
                state.update(status='complete',elapsed_seconds=elapsed())
                _put(db,'dataset',meta); _put(db,'live_session',session); _put(db,'pipeline',state); db.commit()
            if progress: progress(f"Scan complete · {meta['records']:,} records · {len(session['pairs']):,} ready pairs")
            return snapshot(job)
        except BaseException as exc:
            db.rollback()
            with storage.job_lock(job, wait=5):
                state = _get(db,'pipeline')
                state.update(status='paused' if isinstance(exc,storage.Cancelled) else 'error',error=str(exc),elapsed_seconds=elapsed())
                _put(db,'pipeline',state); db.commit()
            raise
        finally:
            if 'reader' in locals(): reader.close()
            db.close()


def snapshot(job):
    db = storage.connect(Path(job)/'records.sqlite')
    try:
        db.execute('BEGIN')
        meta = _get(db,'dataset'); state = _get(db,'pipeline'); session = _get(db,'live_session')
        return {'records': meta['records'], 'ready_pairs':len(session['pairs']), 'status':state['status'],
                'source':state['identity']['path'], 'mapping':meta['mapping'], 'stats':session['candidate_stats'],
                'timing':{k:state[k] for k in ('elapsed_seconds','first_pair_seconds','first_50_seconds')},
                'error':state.get('error'), 'version':session['ai_model']['version']}
    finally: db.close()


def is_progressive(job):
    path = Path(job)/'records.sqlite'
    if not path.exists(): return False
    db = storage.connect(path)
    try: return db.execute("SELECT 1 FROM meta WHERE key='live_session'").fetchone() is not None
    finally: db.close()
