import json
import threading
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ai_model as ai
import progressive
import storage
import twin_workflow as workflow


class FastEncoder:
    """Deterministic test vectors only; actual neural parity tested separately."""
    def encode(self,texts,batch_size=8):
        values=np.zeros((len(texts),384),dtype=np.float32);values[:,0]=1
        return values


def fixture_file(path,count=800):
    path.write_text('title,authors,year\n'+''.join(f'Paper about indexing group {i//2},Chen,2020\n' for i in range(count)),encoding='utf-8')


def test_mapping_ambiguity_is_not_silently_resolved():
    mapping,uncertain=progressive.detect_mapping(['Article Title','Author','Publication Year'])
    assert mapping=={'title':'Article Title','authors':'Author','venue':None,'year':'Publication Year'} and not uncertain
    _,uncertain=progressive.detect_mapping(['Title','Paper Title','Authors'])
    assert uncertain==['title']


def test_live_reviews_stable_resume_and_full_export_guard(tmp_path):
    source=tmp_path/'input.csv';fixture_file(source);job=tmp_path/'job';stop=threading.Event();first=[]
    def progress(message):
        if 'AI-scored pairs ready' in message:
            result=workflow.inspect(job,1);first.append(result['source_rows'])
            workflow.review(job,1,'accept')
            with pytest.raises(ValueError,match='scan to complete'):storage.export_cleaned(job,tmp_path/'premature.zip')
            stop.set()
    with pytest.raises(storage.Cancelled):progressive.run(source,job,max_pairs=100,progress=progress,cancel=stop,encoder=FastEncoder())
    before=progressive.snapshot(job)
    assert before['status']=='paused' and before['ready_pairs']==50 and before['records']<800
    assert not (tmp_path/'premature.zip').exists()
    stop.clear();progressive.run(source,job,cancel=stop,encoder=FastEncoder())
    after=workflow.inspect(job,1)
    assert after['source_rows']==first[0] and after['latest_review']['decision']=='accept'
    state=progressive.snapshot(job);assert state['status']=='complete' and state['records']==800 and state['ready_pairs']==100
    assert state['stats']['queue_truncated']
    result=storage.export_cleaned(job,tmp_path/'complete.zip');assert result['input_records']==800 and result['output_records']==799


def test_cross_chunk_matches_and_changed_source_rejected(tmp_path):
    source=tmp_path/'input.csv'
    source.write_text('title\nShared distant publication\n'+''.join(f'z{i} unrelated\n' for i in range(300))+'Shared distant publication\n')
    job=tmp_path/'job';progressive.run(source,job,encoder=FastEncoder())
    db,data=storage.open_dataset(job)
    try:assert [0,301] in storage.load_session(job,data)['pairs']
    finally:db.close()
    with source.open('a') as handle:handle.write('changed\n')
    with pytest.raises(ValueError,match='changed'):progressive.run(source,job,encoder=FastEncoder())


def test_scanner_lock_does_not_block_review_lock(tmp_path):
    source=tmp_path/'input.csv';fixture_file(source,20);job=tmp_path/'job'
    progressive.run(source,job,encoder=FastEncoder())
    with storage.job_lock(job,name='.scan.lock'):
        workflow.review(job,1,'reject')
        with pytest.raises(ValueError,match='another application|in progress'):progressive.run(source,job,encoder=FastEncoder())
    assert workflow.inspect(job,1)['latest_review']['decision']=='reject'


def test_dynamic_padding_matches_fixed_padding():
    encoder=ai.Encoder()
    texts=['','graph indexing','Étude des données bibliographiques','word '*400]
    dynamic=encoder.encode(texts)
    encoder.tokenizer.enable_padding(length=256,pad_id=0,pad_token='[PAD]')
    fixed=encoder.encode(texts)
    assert np.allclose(dynamic,fixed,atol=2e-5)


def test_desktop_keeps_review_enabled_during_scan(tmp_path):
    import tkinter as tk
    from desktop import App
    source=tmp_path/'input.csv';fixture_file(source,20);job=tmp_path/'job'
    progressive.run(source,job,encoder=FastEncoder())
    root=tk.Tk();root.withdraw();release=threading.Event()
    try:
        app=App(root,job)
        app.run(lambda progress:release.wait(3),lambda result:None,scanning=True)
        assert str(app.open_button.cget('state'))=='disabled'
        assert any(b.cget('text')=='Accept as duplicate' and str(b.cget('state'))=='normal' for b in app.buttons)
        app.display_pair(workflow.inspect(job,1));app.save_review('reject')
        from test_desktop_ui import wait_review
        wait_review(root,app)
        assert workflow.inspect(job,1)['latest_review']['decision']=='reject'
    finally:release.set();root.destroy()
