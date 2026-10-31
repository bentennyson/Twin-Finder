"""Disk-backed CSV/JSONL workflow. Scoring and reviewer decisions use twin_core.

Dataset size is limited by disk, time and filesystem capacity, not an upload MB
setting. Individual records are capped at 8 MiB. Candidate coverage is bounded
and explicitly reported; this does not promise exhaustive duplicate discovery.
"""
import csv
import hashlib
import io
import itertools
import json
import os
import shutil
import sqlite3
import zipfile
import threading
import time
import errno
from collections import deque
from contextlib import contextmanager
from pathlib import Path

import twin_core as core

RECORD_LIMIT = 8 * 1024 * 1024
RESERVE_BYTES = 256 * 1024 * 1024

class Cancelled(Exception):
    pass


class JobBusy(ValueError):
    """A writer did not finish before the bounded waiting period expired."""


_writers_condition = threading.Condition()
_writers = {}


@contextmanager
def _writer_turn(path, deadline):
    """FIFO within this process; the OS lock still protects other processes.

    A scanner that releases and immediately reacquires must not jump ahead of
    a waiting reviewer. Empty queues are removed to avoid retaining old jobs.
    """
    key = os.path.normcase(str(path.resolve()))
    ticket = object()
    with _writers_condition:
        queue = _writers.setdefault(key, deque())
        queue.append(ticket)
        try:
            while queue[0] is not ticket:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise JobBusy('A write to this job is still in progress. Wait briefly and retry the operation.')
                _writers_condition.wait(remaining)
        except BaseException:
            queue.remove(ticket)
            _writers_condition.notify_all()
            raise
    try:
        yield
    finally:
        with _writers_condition:
            queue.popleft()
            if not queue:del _writers[key]
            _writers_condition.notify_all()

def check_cancel(cancel):
    if cancel and cancel.is_set():
        raise Cancelled('Stopped safely. Reopen the job to continue; completed import and embedding batches are saved.')

@contextmanager
def job_lock(job, name=".lock", wait=0):
    """Ordered local writers plus a cross-process byte lock, with bounded wait."""
    path=Path(job);path.mkdir(parents=True,exist_ok=True)
    deadline=time.monotonic()+wait
    with _writer_turn(path/name,deadline):
        # Windows permits a range lock beyond EOF. No read/write of the locked
        # byte is needed; access and filesystem errors must not masquerade as
        # another application's lock conflict.
        with (path/name).open('a+b',buffering=0) as f:
            while True:
                try:
                    f.seek(0)
                    if os.name=='nt':
                        import msvcrt
                        msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES,errno.EAGAIN,errno.EDEADLK):raise
                    if time.monotonic()>=deadline:
                        raise JobBusy('This job is busy in another application or process. Close the other instance or wait and retry the operation.') from exc
                    time.sleep(min(.02,max(0,deadline-time.monotonic())))
            try:yield
            finally:
                f.seek(0)
                if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(f.fileno(),fcntl.LOCK_UN)


def connect(path):
    db = sqlite3.connect(path, timeout=60)
    db.execute('PRAGMA cache_size=-16384')
    db.execute('PRAGMA temp_store=FILE')
    return db


def space_check(path, needed=0):
    if shutil.disk_usage(path).free < RESERVE_BYTES + needed:
        raise ValueError('Insufficient free disk space. Keep at least 256 MiB free, plus room for this operation.')


def file_hash(path, cancel=None):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            check_cancel(cancel)
            h.update(block)
    return h.hexdigest()


def source_rows(path, offset=0, columns=None, position=None):
    """Stream records, validating syntax without reading the complete input."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in {'.csv', '.jsonl', '.ndjson'}:
        raise ValueError('Large-file mode supports UTF-8 CSV or JSONL/NDJSON. Convert JSON arrays to JSONL first.')
    with path.open('rb') as f:
        f.seek(offset)
        record_bytes = 0
        def lines():
            nonlocal record_bytes
            while True:
                raw = f.readline(RECORD_LIMIT + 1)
                if not raw:
                    return
                if len(raw) > RECORD_LIMIT:
                    raise ValueError('A physical input line exceeds the 8 MiB safety limit.')
                line=raw.decode('utf-8-sig' if f.tell()==len(raw) else 'utf-8')
                record_bytes += len(raw)
                if record_bytes > RECORD_LIMIT:
                    raise ValueError('An input record exceeds the 8 MiB safety limit.')
                yield line
        if suffix == '.csv':
            csv.field_size_limit(RECORD_LIMIT)
            reader = csv.reader(lines(), strict=True)
            columns = next(reader, []) if offset==0 else columns
            validate_columns(columns)
            record_bytes = 0
            for cells in reader:
                record_bytes = 0
                if not cells:
                    continue
                if len(cells) != len(columns):
                    raise ValueError(f'CSV near line {reader.line_num}: expected {len(columns)} cells, found {len(cells)}.')
                row = dict(zip(columns, cells))
                validate_row(row)
                if position is not None: position[0]=f.tell()
                yield row
        else:
            for number, line in enumerate(lines(), 1):
                record_bytes = 0
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    validate_row(row)
                except (ValueError, TypeError) as exc:
                    raise ValueError(f'Invalid JSONL record at line {number}: {exc}') from exc
                if position is not None: position[0]=f.tell()
                yield {k: '' if v is None else str(v) for k, v in row.items()}


def validate_columns(columns):
    if not columns or len(columns) > 256 or len(set(columns)) != len(columns) or any(not isinstance(k, str) or not k.strip() for k in columns):
        raise ValueError('Use 1–256 unique, nonempty column names.')


def validate_row(row):
    if not isinstance(row, dict):
        raise ValueError('Each record must be a flat object.')
    validate_columns(list(row))
    if any(isinstance(v, (list, dict)) for v in row.values()):
        raise ValueError('Nested fields are not supported.')
    if len(json.dumps(row, ensure_ascii=False).encode('utf-8')) > RECORD_LIMIT:
        raise ValueError('A record exceeds the 8 MiB safety limit.')


def peek_columns(path):
    rows = source_rows(path)
    try:
        return list(next(rows))
    except StopIteration:
        raise ValueError('The dataset has no records.')
    finally:
        rows.close()


def validate_mapping(mapping, columns):
    if set(mapping) != set(core.FIELDS) or mapping['title'] not in columns:
        raise ValueError('Map a title column; the other fields are optional.')
    active = [v for v in mapping.values() if v]
    if len(active) != len(set(active)) or any(v not in columns for v in active):
        raise ValueError('Map different, existing columns.')


def import_file(source, job, mapping=None, progress=None, cancel=None):
    """Resume CSV/JSONL at committed record boundaries. Never expose partial data."""
    source, job = Path(source).resolve(), Path(job).resolve()
    columns = peek_columns(source)
    mapping = mapping or {k: next((c for c in columns if c.casefold() == k), None) for k in core.FIELDS}
    validate_mapping(mapping, columns)
    job.mkdir(parents=True, exist_ok=True)
    if (job/'records.sqlite').exists():
        raise ValueError('This job is already imported. Open it or choose a new job folder.')
    scratch = job / 'importing.sqlite'
    db = connect(scratch)
    before = source.stat()
    try:
        db.executescript('CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY, payload TEXT NOT NULL, title TEXT NOT NULL); '
                         'CREATE TABLE IF NOT EXISTS tokens(token TEXT NOT NULL, id INTEGER NOT NULL, PRIMARY KEY(token,id)) WITHOUT ROWID; '
                         'CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);')
        identity={'path':str(source),'size':before.st_size,'mtime':before.st_mtime_ns,'mapping':mapping}
        saved=db.execute("SELECT value FROM meta WHERE key='checkpoint'").fetchone()
        state=json.loads(saved[0]) if saved else {'identity':identity,'offset':0,'count':0,'columns':columns}
        if state['identity']!=identity:
            raise ValueError('Input file or mapping changed. Use a new job folder.')
        count=state['count'];columns=state['columns'];position=[state['offset']]
        def checkpoint():
            state.update(count=count,offset=position[0],columns=columns)
            db.execute("INSERT OR REPLACE INTO meta VALUES('checkpoint',?)",(json.dumps(state),));db.commit()
        checkpoint()
        for count, row in enumerate(source_rows(source,state['offset'],columns,position), state['count']+1):
            check_cancel(cancel)
            for key in row:
                if key not in columns:
                    columns.append(key)
            validate_columns(columns)
            title = core.norm(row.get(mapping['title']))
            db.execute('INSERT INTO records VALUES(?,?,?)', (count-1, json.dumps(row, ensure_ascii=False), title))
            db.executemany('INSERT INTO tokens VALUES(?,?)', ((t, count-1) for t in core.tokens(title)))
            if count % 1000 == 0:
                checkpoint()
                space_check(job)
                if progress:
                    progress(count)
        if not count:
            raise ValueError('The dataset has no records.')
        if progress:
            progress(count)
        # Hash without buffering the file; reject inputs changed during ingestion.
        check_cancel(cancel)
        checkpoint()
        digest = file_hash(source,cancel)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('Input changed during import. Retry with a stable file.')
        db.execute('CREATE INDEX IF NOT EXISTS records_title ON records(title,id)')
        db.execute('CREATE TABLE IF NOT EXISTS embeddings(id INTEGER PRIMARY KEY, vector BLOB NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS pair_features(a INTEGER,b INTEGER,value TEXT NOT NULL, PRIMARY KEY(a,b)) WITHOUT ROWID')
        metadata = {'filename': source.name, 'sha256': digest, 'source_bytes': before.st_size,
                    'columns': columns, 'mapping': mapping, 'records': count, 'created': core.now(),
                    'storage_version': 1, 'engine': core.ENGINE_VERSION}
        db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', ('dataset', json.dumps(metadata)))
        db.commit()
        db.close()
        scratch.replace(job / 'records.sqlite')
        (job / 'dataset.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        return metadata
    except BaseException:
        db.rollback()
        db.close()
        raise


class DiskRows:
    def __init__(self, db, count, columns):
        self.db, self.count, self.columns = db, count, columns

    def __len__(self):
        return self.count

    def decode(self, raw):
        record = json.loads(raw)
        return {c: record.get(c, '') for c in self.columns}

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(self.count))]
        if not 0 <= index < self.count:
            raise IndexError(index)
        return self.decode(self.db.execute('SELECT payload FROM records WHERE id=?', (index,)).fetchone()[0])

    def __iter__(self):
        for row in self.db.execute('SELECT payload FROM records ORDER BY id'):
            yield self.decode(row[0])


def open_dataset(job):
    path = Path(job) / 'records.sqlite'
    if not path.is_file():
        raise ValueError('Dataset import is incomplete or missing.')
    db = connect(path)
    try:
        db.execute('BEGIN')
        meta = json.loads(db.execute("SELECT value FROM meta WHERE key='dataset'").fetchone()[0])
        live = db.execute("SELECT value FROM meta WHERE key='live_session'").fetchone()
        if live: meta['_session'] = json.loads(live[0])
        def feature_lookup(pair):
            import numpy as np
            saved=db.execute('SELECT value FROM pair_features WHERE a=? AND b=?',tuple(pair)).fetchone()
            if not saved: raise ValueError('AI preparation is incomplete. Run Prepare AI before reviewing.')
            return np.asarray(json.loads(saved[0]),dtype=np.float64)
        return db, {**meta, 'rows': DiskRows(db, meta['records'], meta['columns']), 'pair_features':feature_lookup}
    except BaseException:
        db.close()
        raise


def build_session(job, max_pairs=10000, budget=3000000, progress=None, cancel=None):
    """Disk-backed equivalent of core candidate order/filter/ranking, with bounded queue."""
    if not 1 <= max_pairs <= 100000 or not 1 <= budget <= 3000000:
        raise ValueError('Use 1–100000 review pairs and 1–3000000 comparison iterations.')
    job = Path(job)
    if (job / 'session.json').exists():
        raise ValueError('This job already has a session. Import into a new job to change its mapping or queue.')
    db, dataset = open_dataset(job)
    scratch = job / 'candidates.tmp.sqlite'
    scratch.unlink(missing_ok=True)
    tmp = connect(scratch)
    try:
        tmp.execute('CREATE TABLE seen(a INTEGER,b INTEGER,sim REAL,PRIMARY KEY(a,b)) WITHOUT ROWID')
        stats = {'records': len(dataset['rows']), 'comparison_budget': budget, 'iterations': 0,
                 'compared_pairs': 0, 'oversized_token_blocks': 0, 'large_exact_groups': 0,
                 'budget_reached': False, 'max_pairs': max_pairs, 'title_prefilter': .5,
                 'storage': 'SQLite; record payloads and candidate deduplication on disk'}
        stats['oversized_token_blocks'] = db.execute('SELECT count(*) FROM (SELECT token FROM tokens GROUP BY token HAVING count(*)>100)').fetchone()[0]
        stats['large_exact_groups'] = db.execute("SELECT count(*) FROM (SELECT title FROM records WHERE title<>'' GROUP BY title HAVING count(*)>100)").fetchone()[0]

        def proposed():
            # core exact groups are ordered by first source position.
            groups = db.execute("SELECT title,count(*),min(id) FROM records WHERE title<>'' GROUP BY title HAVING count(*)>1 ORDER BY min(id)")
            for title, count, first in groups:
                ids = db.execute('SELECT id FROM records WHERE title=? ORDER BY id', (title,))
                if count > 100:
                    for (other,) in ids:
                        if other != first:
                            yield first, other
                else:
                    yield from itertools.combinations([i for (i,) in ids], 2)
            # A fixed-width id sequence reproduces core's lexicographic list ordering.
            blocks = db.execute("SELECT t.token,t.n,(SELECT group_concat(printf('%020d',id),'') FROM "
                                '(SELECT id FROM tokens WHERE token=t.token ORDER BY id)) AS seq FROM '
                                '(SELECT token,count(*) AS n FROM tokens GROUP BY token HAVING count(*) BETWEEN 2 AND 100) t '
                                'ORDER BY t.n,seq')
            for token, count, seq in blocks:
                ids = [i for (i,) in db.execute('SELECT id FROM tokens WHERE token=? ORDER BY id', (token,))]
                yield from itertools.combinations(ids, 2)

        for i, j in proposed():
            check_cancel(cancel)
            if stats['iterations'] >= budget:
                stats['budget_reached'] = True
                break
            stats['iterations'] += 1
            if tmp.execute('INSERT OR IGNORE INTO seen VALUES(?,?,NULL)', (i, j)).rowcount == 0:
                continue
            x = db.execute('SELECT title FROM records WHERE id=?', (i,)).fetchone()[0]
            y = db.execute('SELECT title FROM records WHERE id=?', (j,)).fetchone()[0]
            size = max(len(x), len(y))
            if not size or abs(len(x)-len(y))/size >= .5:
                continue
            sim = 1-core.Levenshtein.distance(x, y)/size
            stats['compared_pairs'] += 1
            if sim > .5:
                tmp.execute('UPDATE seen SET sim=? WHERE a=? AND b=?', (sim, i, j))
            if stats['iterations'] % 10000 == 0:
                tmp.commit()
                space_check(job)
                if progress: progress(stats['iterations'])
        total = tmp.execute('SELECT count(*) FROM seen WHERE sim IS NOT NULL').fetchone()[0]
        pairs = [list(p) for p in tmp.execute('SELECT a,b FROM seen WHERE sim IS NOT NULL ORDER BY sim DESC,a,b LIMIT ?', (max_pairs,))]
        stats.update(eligible_pairs=total, returned_pairs=len(pairs), queue_truncated=total>max_pairs)
        session = {'schema': 1, 'engine': core.ENGINE_VERSION, 'dataset_sha256': dataset['sha256'],
                   'mapping': dataset['mapping'],
                   'pairs': pairs, 'candidate_stats': stats, 'events': [], 'updates': [], 'created': core.now()}
        save_session(job, session)
        return session
    finally:
        tmp.close()
        db.close()
        scratch.unlink(missing_ok=True)


def save_session(job, session):
    if session.get('progressive'):
        db = connect(Path(job)/'records.sqlite')
        try:
            db.execute("INSERT OR REPLACE INTO meta VALUES('live_session',?)", (json.dumps(session),))
            db.commit()
        finally: db.close()
        return
    target = Path(job) / 'session.json'
    tmp = target.with_suffix('.tmp')
    tmp.write_bytes(core.export_session(session))
    tmp.replace(target)


def load_session(job, dataset):
    session = dataset.get('_session')
    if session is None: session = json.loads((Path(job) / 'session.json').read_text(encoding='utf-8'))
    if session.get('engine') != core.ENGINE_VERSION or session.get('schema') != 1 or (session.get('dataset_id') != dataset.get('job_id') if session.get('progressive') else session.get('dataset_sha256') != dataset['sha256']):
        raise ValueError('Incompatible session or wrong input dataset.')
    validate_mapping(session['mapping'], dataset['columns'])
    if 'ai_model' in session:
        from ai_model import validate
        validate(session['ai_model'])
    pairs = session['pairs']
    if len(pairs)>100000 or any(not isinstance(p,list) or len(p)!=2 or any(type(i) is not int for i in p) or not 0<=p[0]<p[1]<len(dataset['rows']) for p in pairs):
        raise ValueError('Invalid saved pairs.')
    available = {tuple(p) for p in pairs}
    if len(available) != len(pairs):
        raise ValueError('Duplicate saved pairs.')
    for e in session['events']:
        if tuple(e['pair']) not in available or e['decision'] not in {'accept','reject','skip'}:
            raise ValueError('Invalid review event.')
    if not isinstance(session['updates'], list):
        raise ValueError('Invalid threshold history.')
    return session


def export_cleaned(job, output, progress=None, cancel=None):
    """Stream ZIP64 export; only reviewed connected components occupy Python memory."""
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Output already exists; choose a new export filename.')
    output.parent.mkdir(parents=True, exist_ok=True)
    space_check(output.parent)
    db, dataset = open_dataset(job)
    partial = output.with_name(output.name+'.partial')
    if partial.exists():
        db.close()
        raise ValueError('A partial export already exists. Choose another filename.')
    try:
        session = load_session(job, dataset)
        if session.get('progressive') and not dataset.get('import_complete'):
            raise ValueError('Wait for the scan to complete before exporting the full dataset. Reviews are already saved.')
        rows, columns = dataset['rows'], dataset['columns']
        decisions = core.latest_decisions(session)
        parent = {}
        def root(i):
            parent.setdefault(i, i)
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for pair, event in decisions.items():
            if event['decision'] == 'accept':
                a,b = map(root, pair)
                parent[b] = a
        for pair,event in decisions.items():
            if event['decision'] == 'reject' and pair[0] in parent and pair[1] in parent and root(pair[0]) == root(pair[1]):
                raise ValueError('Export blocked: accepted links connect explicitly rejected pairs.')
        groups = {}
        for i in parent:
            groups.setdefault(root(i), []).append(i)
        members, starts = set(parent), {}
        for ids in groups.values():
            ids.sort()
            starts[ids[0]] = ids
        # Temporary CSV files allow separate ZIP members without buffering outputs.
        scratch = Path(job) / ('export_'+os.urandom(8).hex())
        scratch.mkdir()
        output_count = conflicts_count = 0
        try:
            from contextlib import ExitStack
            with ExitStack() as stack:
                writers = {}
                for name, cols in [('cleaned', columns),('source_records', columns),('record_mapping',['source_row','output_row','canonical_source_row'])]:
                    f = stack.enter_context((scratch/(name+'.csv')).open('w',encoding='utf-8-sig',newline=''))
                    writers[name] = csv.DictWriter(f, fieldnames=cols)
                    writers[name].writeheader()
                conflict_file = stack.enter_context((scratch/'conflicts.json').open('w', encoding='utf-8'))
                conflict_file.write('[')
                for i, row in enumerate(rows):
                    check_cancel(cancel)
                    writers['source_records'].writerow(row)
                    if i in members and i not in starts:
                        continue
                    ids = starts.get(i, [i])
                    # Do not load an entire accepted component: retain ids only.
                    completeness = [(j, sum(not core.missing(v) for v in rows[j].values())) for j in ids] if len(ids)>1 else [(i,0)]
                    ordered = [j for j,n in sorted(completeness,key=lambda v:(-v[1],v[0]))]
                    canonical = dict(rows[ordered[0]]) if len(ids)>1 else dict(row)
                    for col in columns:
                        # Alternatives for a single field are bounded by reviewed components,
                        # not total dataset size; very large accepted groups still cost memory.
                        options = list(dict.fromkeys(rows[j].get(col,'') for j in ordered if not core.missing(rows[j].get(col)))) if len(ids)>1 else []
                        if core.missing(canonical.get(col)) and options:
                            canonical[col] = options[0]
                        if len(options)>1:
                            if conflicts_count:
                                conflict_file.write(',\n')
                            json.dump({'output_row':output_count,'field':col,'retained':canonical.get(col,''),'alternatives':options,'source_rows':ids},conflict_file,ensure_ascii=False)
                            conflicts_count += 1
                    writers['cleaned'].writerow(canonical)
                    for j in ids:
                        writers['record_mapping'].writerow({'source_row':j,'output_row':output_count,'canonical_source_row':ordered[0]})
                    output_count += 1
                    if i % 2000 == 0:
                        space_check(scratch)
                        if progress: progress(i)
                conflict_file.write(']')
            summary = {'input_records':len(rows),'output_records':output_count,'records_consolidated':len(rows)-output_count,
                       'merged_groups':len(groups),'conflicting_fields':conflicts_count,
                       'policy':'Only accepted links; most-complete row; empty-field fill; alternatives retained in conflicts.json.',
                       'dataset_sha256':dataset['sha256'],'engine':core.ENGINE_VERSION}
            with zipfile.ZipFile(partial,'x',zipfile.ZIP_DEFLATED,allowZip64=True) as z:
                for p in scratch.iterdir():
                    with p.open('rb') as src,z.open(p.name,'w',force_zip64=True) as dst:
                        for block in iter(lambda:src.read(1024*1024),b''):
                            check_cancel(cancel)
                            space_check(output.parent,len(block))
                            dst.write(block)
                z.writestr('summary.json',json.dumps(summary,indent=2))
                z.writestr('review_session.json',core.export_session(session))
                if 'ai_model' in session: z.writestr('ai_model.json',json.dumps(session['ai_model'],indent=2))
            partial.replace(output)
            return summary
        finally:
            # Scratch is an explicitly created child of this job, never user input.
            for p in scratch.iterdir():
                p.unlink()
            scratch.rmdir()
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        db.close()
