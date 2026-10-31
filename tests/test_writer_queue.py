import sys,threading,time,subprocess,json
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import storage


def test_waiting_review_precedes_scanner_reacquisition(tmp_path):
    job=tmp_path/'job';order=[];errors=[]
    def reviewer():
        try:
            with storage.job_lock(job,wait=2):order.append('review')
        except Exception as exc:errors.append(exc)
    with storage.job_lock(job):
        worker=threading.Thread(target=reviewer);worker.start()
        key=str((job/'.lock').resolve()).casefold() if sys.platform=='win32' else str((job/'.lock').resolve())
        until=time.monotonic()+2
        while time.monotonic()<until:
            with storage._writers_condition:
                if len(storage._writers.get(key,()))==2:break
            time.sleep(.005)
        else:pytest.fail('Reviewer did not join the writer queue')
    with storage.job_lock(job,wait=2):order.append('scanner')
    worker.join(2)
    assert not errors and order==['review','scanner']
    assert not storage._writers


def test_timed_out_waiter_does_not_poison_queue(tmp_path):
    with storage.job_lock(tmp_path):
        with pytest.raises(storage.JobBusy,match='in progress'):
            with storage.job_lock(tmp_path):pass
    with storage.job_lock(tmp_path):pass
    assert not storage._writers


def test_os_lock_still_blocks_a_second_process(tmp_path):
    code="""
import storage,sys
try:
    with storage.job_lock(sys.argv[1]):pass
except storage.JobBusy:
    print('blocked')
else:raise SystemExit('Second process incorrectly acquired lock')
"""
    with storage.job_lock(tmp_path):
        child=subprocess.run([sys.executable,'-c',code,str(tmp_path)],cwd=Path(storage.__file__).parent,text=True,capture_output=True,timeout=10)
    assert child.returncode==0,child.stderr
    assert child.stdout.strip()=='blocked'
    with storage.job_lock(tmp_path):pass
