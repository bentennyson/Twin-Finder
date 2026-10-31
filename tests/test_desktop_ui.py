"""Presentation must preserve mapped records and human-review semantics."""
import sys
import time
import threading
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import progressive
import twin_workflow as workflow


def pump(root):
    """Use the app's native event loop with a bounded tick on every platform.

    Canvas redraws can keep update() draining indefinitely on macOS. A
    scheduled quit keeps assertions bounded without disabling any callbacks.
    """
    root.after(10, root.quit)
    root.mainloop()


def wait_review(root,app):
    deadline=time.monotonic()+8
    while (app.review_pending or time.monotonic()<app.review_cooldown) and time.monotonic()<deadline:
        pump(root);time.sleep(.01)
    assert app.review_pending is None
    assert time.monotonic()>=app.review_cooldown


class FixtureEncoder:
    def encode(self,texts,batch_size=8):
        vectors=np.zeros((len(texts),384),dtype=np.float32)
        vectors[:,0]=1
        return vectors


def test_display_startup_uses_dpi_awareness_and_actual_heading_font():
    """Run before the first HWND: DPI awareness cannot be reset mid-process."""
    import subprocess,json,os
    root_path=Path(__file__).resolve().parents[1]
    code="""
import json,ctypes,os
from tkinter import ttk,font
from modern_ui import create_root,configure_theme
root=create_root();root.withdraw();configure_theme(root)
label=ttk.Label(root,text='Twin Finder',style='Heading.TLabel')
effective=label.cget('font') or ttk.Style(root).lookup('Heading.TLabel','font')
result={'heading_size':font.Font(root,font=effective).actual('size')}
if os.name=='nt':
    value=ctypes.c_int();ctypes.windll.shcore.GetProcessDpiAwareness(None,ctypes.byref(value))
    result['dpi_awareness']=value.value
root.destroy();print(json.dumps(result))
"""
    result=subprocess.run([sys.executable,'-c',code],cwd=root_path,text=True,capture_output=True,check=True)
    values=json.loads(result.stdout)
    assert values['heading_size']==46
    if os.name=='nt':assert values['dpi_awareness']==2


def test_cards_follow_mapping_and_decision_revisions(tmp_path):
    import tkinter as tk
    from desktop import App
    source=tmp_path/'papers.csv'
    source.write_text('Article Title,Author,Publication Year\nGraph indexing,Alex Chen,2020\nGraph indexing,Alex Chen,2020\n')
    job=tmp_path/'job'
    progressive.run(source,job,{'title':'Article Title','authors':'Author','venue':None,'year':'Publication Year'},encoder=FixtureEncoder())
    root=tk.Tk();root.withdraw()
    try:
        app=App(root,job)
        result=workflow.inspect(job,1)
        assert app.paper_values[0]['title'].get()==result['records'][0]['Article Title']
        assert app.paper_values[1]['authors'].get()==result['records'][1]['Author']
        assert app.paper_values[0]['venue'].get()=='Not provided'
        assert app.similarity_bars['venue_equal'].value.get()=='N/A'
        assert app.similarity_bars['title_edit'].fraction==result['machine']['feature_values']['title_edit']
        assert app.score_text.get()==f"{result['machine']['score']:.4f}"
        for decision,count in [('accept',1),('reject',1),('skip',0)]:
            app.save_review(decision)
            wait_review(root,app)
            assert app.reviewed_count==count
            assert workflow.inspect(job,1)['latest_review']['decision']==decision
        assert app.ready_total==1
    finally:root.destroy()


def test_activity_animation_remains_responsive_and_stops(tmp_path):
    import tkinter as tk
    from desktop import App
    root=tk.Tk();root.withdraw();release=threading.Event()
    try:
        app=App(root)
        app.run(lambda progress:release.wait(3),lambda result:None)
        assert app.progress.running
        assert str(app.choose_button.cget('state'))=='disabled'
        initial=app.progress.phase
        deadline=time.monotonic()+.2
        while time.monotonic()<deadline:
            pump(root);time.sleep(.01)
        assert app.progress.phase!=initial
        release.set();deadline=time.monotonic()+2
        while app.busy and time.monotonic()<deadline:
            pump(root);time.sleep(.01)
        assert not app.busy
        assert not app.progress.running and app.progress.timer is None
        assert str(app.choose_button.cget('state'))=='normal'
    finally:release.set();root.destroy()


def review_job(tmp_path):
    source=tmp_path/'papers.csv'
    source.write_text('title,authors,year\n'+'Graph indexing,Alex Chen,2020\n'*4)
    job=tmp_path/'job'
    progressive.run(source,job,encoder=FixtureEncoder())
    return job


def test_accept_reject_skip_advance_and_resume(tmp_path):
    import tkinter as tk
    from desktop import App
    job=review_job(tmp_path)
    workflow.review(job,2,'reject')
    root=tk.Tk();root.withdraw()
    try:
        app=App(root,job)
        assert app.current==1
        app.save_review('accept');app.save_review('reject')
        wait_review(root,app)
        assert app.current==3  # Pair 2 was already reviewed.
        assert workflow.inspect(job,1)['latest_review']['decision']=='accept'
        assert workflow.inspect(job,3)['latest_review'] is None
        app.save_review('reject');wait_review(root,app)
        assert app.current==4
        app.save_review('skip');wait_review(root,app)
        assert app.current==5 and app.reviewed_count==3
        assert workflow.inspect(job,4)['latest_review']['decision']=='skip'
        app.previous_pair();assert app.current==4
        app.save_review('accept');wait_review(root,app)
        assert app.current==5 and app.reviewed_count==4
    finally:root.destroy()
    root=tk.Tk();root.withdraw()
    try:
        app=App(root,job);assert app.current==5
        app.save_review('accept');wait_review(root,app)
        assert app.current==6
        app.save_review('reject');wait_review(root,app)
        assert app.current==6 and app.reviewed_count==6
        assert 'All candidate pairs reviewed' in app.review_notice.get()
        app.next_pair();assert app.current==6
        assert 'last ready pair' in app.review_notice.get()
        app.previous_pair();assert app.current==5
        app.save_review('reject');wait_review(root,app)
        assert app.reviewed_count==6  # Revising a decision does not double-count.
    finally:root.destroy()


def test_review_lock_wait_keeps_ui_alive_and_failure_stays_on_pair(tmp_path,monkeypatch):
    import tkinter as tk
    import storage
    from desktop import App
    job=review_job(tmp_path);root=tk.Tk();root.withdraw()
    try:
        app=App(root,job);ticks=[]
        with storage.job_lock(job):
            app.save_review('reject')
            root.after(30,lambda:ticks.append(True))
            until=time.monotonic()+.15
            while time.monotonic()<until:pump(root);time.sleep(.01)
            assert ticks and app.review_pending and app.current==1
            assert all(str(b.cget('state'))=='disabled' for b in app.review_actions)
            assert workflow.inspect(job,1)['latest_review'] is None
        wait_review(root,app)
        assert app.current==2 and app.reviewed_count==1
        def failed(*args):raise ValueError('Job is locked')
        monkeypatch.setattr(workflow,'review',failed)
        app.save_review('accept');wait_review(root,app)
        assert app.current==2 and app.reviewed_count==1
        assert workflow.inspect(job,2)['latest_review'] is None
        assert 'Decision not saved' in app.review_notice.get()
    finally:root.destroy()


def test_new_pairs_auto_appear_after_reviewing_ready_queue(tmp_path):
    import tkinter as tk
    import storage
    from desktop import App
    source=tmp_path/'papers.csv'
    source.write_text('title,authors,year\n'+''.join(f'Graph indexing group {i//2},Chen,2020\n' for i in range(600)))
    job=tmp_path/'job';stop=threading.Event()
    def checkpoint(message):
        if 'AI-scored pairs ready' in message:stop.set()
    try:progressive.run(source,job,encoder=FixtureEncoder(),progress=checkpoint,cancel=stop)
    except storage.Cancelled:pass
    total=workflow.review_navigation(job)['total']
    assert total==50
    for i in range(1,total):workflow.review(job,i,'reject')
    root=tk.Tk();root.withdraw()
    try:
        app=App(root,job);assert app.current==total
        app.save_review('accept');wait_review(root,app)
        assert app.waiting_review and app.current==total
        stop.clear();progressive.run(source,job,encoder=FixtureEncoder(),cancel=stop)
        app.refresh_live()
        assert app.current==total+1 and app.waiting_review is None
        assert app.reviewed_count==total
    finally:root.destroy()


def test_saved_decision_is_not_reported_unsaved_if_navigation_fails(tmp_path,monkeypatch):
    import tkinter as tk
    from desktop import App
    job=review_job(tmp_path);root=tk.Tk();root.withdraw()
    try:
        app=App(root,job)
        def failed(*args):raise ValueError('temporary display failure')
        monkeypatch.setattr(app,'advance_review',failed)
        app.save_review('reject');wait_review(root,app)
        assert workflow.inspect(job,1)['latest_review']['decision']=='reject'
        assert app.current==1
        assert app.review_notice.get().startswith('Decision saved, but')
    finally:root.destroy()


def test_close_waits_for_pending_review_to_finish(tmp_path):
    import tkinter as tk
    import storage
    from desktop import App
    job=review_job(tmp_path);root=tk.Tk();root.withdraw()
    app=App(root,job)
    try:
        with storage.job_lock(job):
            app.save_review('accept');app.close()
            assert app.pending_close and root.winfo_exists()
        deadline=time.monotonic()+5
        while app.review_pending and time.monotonic()<deadline:pump(root);time.sleep(.01)
        assert app.review_pending is None
        assert workflow.inspect(job,1)['latest_review']['decision']=='accept'
        try:
            exists=root.winfo_exists()
        except tk.TclError:exists=False
        assert not exists
    finally:
        try:root.destroy()
        except tk.TclError:pass


def test_switching_jobs_clears_previous_proposal_and_notice(tmp_path):
    import tkinter as tk
    from desktop import App
    (tmp_path/'first').mkdir();(tmp_path/'second').mkdir()
    first=review_job(tmp_path/'first');second=review_job(tmp_path/'second')
    root=tk.Tk();root.withdraw()
    try:
        app=App(root,first)
        app.proposal={'id':99}
        app.set_text(app.learning_text,'Proposal from the previous dataset')
        app.review_notice.set('Previous decision saved')
        app.job.set(str(second));app.first_shown=False;app.refresh()
        assert app.proposal is None
        assert 'previous dataset' not in app.learning_text.get('1.0','end')
        assert 'Previous decision' not in app.review_notice.get()
    finally:root.destroy()
