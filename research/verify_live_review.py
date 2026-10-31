"""Exercise real-input concurrent review, pause/resume and export on a NEW job.

All rejects are scripted engineering decisions, not human labels or accuracy
evidence. Never run this against a user's existing job.
"""
import argparse,csv,json,sys,threading,time,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import progressive,storage,twin_workflow as workflow

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--work',type=Path,required=True);a=p.parse_args()
    a.work.mkdir(parents=True,exist_ok=False);job=a.work/'job'
    ready=threading.Event();cancel=threading.Event();errors=[];reviews=[]
    def task():
        try:progressive.run(a.input,job,progress=lambda m:ready.set() if 'AI-scored pairs ready' in m else None,cancel=cancel)
        except storage.Cancelled:pass
        except Exception as exc:errors.append(str(exc));ready.set()
    thread=threading.Thread(target=task);thread.start()
    try:
        if not ready.wait(120):raise RuntimeError('No scored pairs within test timeout')
        first=workflow.inspect(job,1)['source_rows']
        for i in range(80):
            pair=1+i%min(20,progressive.snapshot(job)['ready_pairs']);start=time.monotonic()
            workflow.review(job,pair,'reject',reviewer='Scripted concurrency check; not human/research labels')
            reviews.append({'pair':pair,'seconds':time.monotonic()-start})
            time.sleep(.025)
    finally:cancel.set();thread.join(120)
    assert not thread.is_alive() and not errors,errors
    paused=progressive.snapshot(job)
    assert workflow.inspect(job,1)['source_rows']==first
    cancel.clear();finished=progressive.run(a.input,job,cancel=cancel)
    assert finished['status']=='complete'
    assert workflow.inspect(job,1)['source_rows']==first
    db,data=storage.open_dataset(job)
    try:assert len(storage.load_session(job,data)['events'])==80
    finally:db.close()
    with storage.job_lock(job,wait=5):export=storage.export_cleaned(job,a.work/'checked_export.zip')
    assert export['output_records']==finished['records']
    with zipfile.ZipFile(a.work/'checked_export.zip') as z:assert z.testzip() is None
    result={'status':'passed','scope':'Scripted operational check, not accuracy or a human study','input':str(a.input),'input_sha256':storage.file_hash(a.input),'records':finished['records'],'review_saves':len(reviews),'max_review_seconds':max(r['seconds'] for r in reviews),'median_review_seconds':sorted(r['seconds'] for r in reviews)[len(reviews)//2],'paused_status':paused['status'],'paused_records':paused['records'],'stable_pair_identity':True,'audit_events_preserved':80,'export_records':export['output_records'],'reviews':reviews}
    (Path(__file__).resolve().parents[1]/'results/live_review_verification.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
