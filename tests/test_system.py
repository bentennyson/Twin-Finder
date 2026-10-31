import copy
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import threading
import zipfile
import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import ai_model as ai
import storage
import twin_core as core
import twin_workflow as workflow


@pytest.fixture(scope='session')
def encoder():return ai.Encoder()


def imported(tmp_path):
    job=tmp_path/'job';storage.import_file(ROOT/'sample.csv',job);return job


def test_csv_jsonl_and_resume_at_quoted_record_boundary(tmp_path):
    source=tmp_path/'records.csv'
    with source.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['title','authors'])
        for i in range(2200):w.writerow([f'Ã‰tude {i}\nsecond line, quoted','Chen'])
    stop=threading.Event();job=tmp_path/'job'
    with pytest.raises(storage.Cancelled):storage.import_file(source,job,progress=lambda n:stop.set(),cancel=stop)
    assert not (job/'records.sqlite').exists()
    db=storage.connect(job/'importing.sqlite');state=json.loads(db.execute("SELECT value FROM meta WHERE key='checkpoint'").fetchone()[0]);db.close()
    assert state['count']==1000
    stop.clear();storage.import_file(source,job,cancel=stop)
    db,dataset=storage.open_dataset(job)
    assert len(dataset['rows'])==2200 and dataset['rows'][2199]['title']=='Ã‰tude 2199\nsecond line, quoted'
    db.close()
    j=tmp_path/'records.jsonl';j.write_text('{"title":"one"}\n{"title":"two","year":2020}\n',encoding='utf-8')
    storage.import_file(j,tmp_path/'jsonjob')
    db,d=storage.open_dataset(tmp_path/'jsonjob');assert d['rows'][0]['year']=='' and d['rows'][1]['year']=='2020';db.close()


def test_changed_input_refuses_resume_and_bad_data_rejected(tmp_path):
    source=tmp_path/'r.csv';source.write_text('title\n'+''.join(f'record {i}\n' for i in range(1100)))
    stop=threading.Event()
    with pytest.raises(storage.Cancelled):storage.import_file(source,tmp_path/'job',progress=lambda n:stop.set(),cancel=stop)
    with source.open('a') as f:f.write('changed\n')
    with pytest.raises(ValueError,match='changed'):storage.import_file(source,tmp_path/'job')
    bad=tmp_path/'bad.csv';bad.write_text('title,title\na,b\n')
    with pytest.raises(ValueError):storage.import_file(bad,tmp_path/'badjob')


def test_disk_candidate_order_matches_reference_and_cancellation(tmp_path):
    job=imported(tmp_path);db,d=storage.open_dataset(job)
    records=[{k:row.get(k,'') for k in core.FIELDS} for row in d['rows']];db.close()
    stop=threading.Event();stop.set()
    with pytest.raises(storage.Cancelled):storage.build_session(job,cancel=stop)
    assert not (job/'session.json').exists()
    session=storage.build_session(job,max_pairs=1000)
    expected,stats=core.candidates(records,1000)
    assert session['pairs']==expected
    for key in stats:assert session['candidate_stats'][key]==stats[key]


def test_neural_features_explanation_and_streaming_export(tmp_path,encoder):
    job=imported(tmp_path);workflow.prepare(job,encoder=encoder)
    result=workflow.inspect(job,1);m=result['machine']
    assert len(m['feature_values'])==10
    assert m['feature_values']['title_semantic']>.99
    assert abs(float(ai.sigmoid(m['intercept']+sum(m['logit_contributions'].values())))-m['score'])<1e-12
    workflow.review(job,1,'accept');summary=storage.export_cleaned(job,tmp_path/'cleaned.zip')
    assert summary['input_records']==13 and summary['output_records']==12
    with zipfile.ZipFile(tmp_path/'cleaned.zip') as z:
        assert {'cleaned.csv','source_records.csv','record_mapping.csv','conflicts.json','review_session.json','ai_model.json'}<=set(z.namelist())
        sources=list(csv.DictReader(io.StringIO(z.read('source_records.csv').decode('utf-8-sig'))));assert len(sources)==13
    db,d=storage.open_dataset(job);s=storage.load_session(job,d);db.close()
    # Accepted connectivity must never override an explicit reject.
    for pair,decision in [([0,2],'accept'),([1,2],'reject')]:workflow.review(job,s['pairs'].index(pair)+1,decision)
    with pytest.raises(ValueError,match='rejected'):storage.export_cleaned(job,tmp_path/'blocked.zip')
    assert not (tmp_path/'blocked.zip').exists()


def feedback_job(tmp_path):
    """Synthetic features isolate learning/gating mechanics; no accuracy claim."""
    source=tmp_path/'feedback.csv'
    source.write_text('title\n'+''.join(f'Unique synthetic record {i}\n' for i in range(800)))
    job=tmp_path/'feedback';storage.import_file(source,job)
    db,d=storage.open_dataset(job);base=ai.load_base();pairs=[[2*i,2*i+1] for i in range(400)]
    session={'schema':1,'engine':core.ENGINE_VERSION,'dataset_sha256':d['sha256'],'mapping':d['mapping'],
             'pairs':pairs,'candidate_stats':{},'events':[],'updates':[],'ai_model':base,'model_history':[base],
             'model_actions':[],'proposals':[],'review_revision':0,'ai_ready':True}
    for index,pair in enumerate(pairs):
        x=np.ones(10) if index%2 else np.zeros(10)
        db.execute('INSERT INTO pair_features VALUES(?,?,?)',(*pair,json.dumps(x.tolist())))
        if index<300:
            decision='accept' if index%2 else 'reject'
            session['events'].append({'pair':pair,'decision':decision,'timestamp':core.now(),'machine':ai.explain(x,base)})
            session['review_revision']+=1
    db.commit();db.close();storage.save_session(job,session)
    return job


def test_feedback_is_record_disjoint_and_applied_then_rollback(tmp_path):
    job=feedback_job(tmp_path);before=workflow.inspect(job,2)['machine'];proposal=workflow.propose_update(job)
    assert proposal['eligible_to_apply']
    assert proposal['model']['weights']!=ai.load_base()['weights']
    workflow.activate(job,proposal['id']);after=workflow.inspect(job,2)['machine']
    assert after['model_version']>before['model_version'] and after['score']!=before['score']
    db,d=storage.open_dataset(job);s=storage.load_session(job,d)
    train_ids={i for p in s['pairs'] if ai.feedback_role(d['sha256'],p)=='training' for i in p}
    val_ids={i for p in s['pairs'] if ai.feedback_role(d['sha256'],p)=='validation' for i in p}
    assert train_ids.isdisjoint(val_ids) and len(s['events'])==300
    db.close();workflow.rollback(job,0)
    assert workflow.inspect(job,2)['machine']==before


def test_stale_feedback_and_failed_guard_block_activation(tmp_path):
    job=feedback_job(tmp_path);p=workflow.propose_update(job);workflow.review(job,1,'skip')
    with pytest.raises(ValueError,match='changed'):workflow.activate(job,p['id'])
    db,d=storage.open_dataset(job);s=storage.load_session(job,d);db.close()
    s['proposals'][-1]['eligible_to_apply']=False;storage.save_session(job,s)
    with pytest.raises(ValueError,match='guard'):workflow.activate(job,p['id'])


def test_small_label_pool_and_locking(tmp_path,encoder):
    job=imported(tmp_path);workflow.prepare(job,encoder=encoder)
    with pytest.raises(ValueError,match='Need at least'):workflow.propose_update(job)
    with storage.job_lock(job):
        with pytest.raises(ValueError,match='another application|in progress'):
            with storage.job_lock(job):pass


def test_terminal_calls_same_prediction_and_review(tmp_path,encoder):
    job=imported(tmp_path);workflow.prepare(job,encoder=encoder)
    def run(*args):
        p=subprocess.run([sys.executable,str(ROOT/'cli.py'),*args,'--job',str(job)],capture_output=True,text=True,check=True)
        return json.loads(p.stdout)
    assert run('inspect','--pair','1')==workflow.inspect(job,1)
    assert run('review','--pair','1','--decision','accept')['machine']==workflow.inspect(job,1)['machine']


def test_desktop_adapter_displays_same_machine(tmp_path,encoder):
    import tkinter as tk
    from desktop import App
    job=imported(tmp_path);workflow.prepare(job,encoder=encoder)
    root=tk.Tk();root.withdraw()
    try:
        app=App(root,job);result=workflow.inspect(job,1);app.display_pair(result)
        assert app.score_text.get()==f"{result['machine']['score']:.4f}"
        assert app.verdict.get()==result['machine']['verdict'].title()
        app.save_review('accept')
        from test_desktop_ui import wait_review
        wait_review(root,app)
        assert workflow.inspect(job,1)['latest_review']['decision']=='accept'
        app.job.set(str(tmp_path/'different'))
        with pytest.raises(ValueError,match='Show a pair'):app.save_review('reject')
    finally:root.destroy()


def test_exact_threshold_boundary():
    threshold,_=core.select_threshold([.5011,.5012],[0,1],.7)
    assert threshold==.5011 and core.metrics([.5011,.5012],[0,1],threshold)['f1']==1
