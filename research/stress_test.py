"""Measure synthetic disk ingestion and candidate retrieval; not a real-corpus AI accuracy study."""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import storage
from ai_model import ROOT

def worker(folder,count):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);source=folder/'synthetic.csv'
    start=time.perf_counter()
    with source.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(['title','authors','venue','year','note'])
        for i in range(count):
            key=i-1 if i%100==1 else i
            w.writerow([f'Synthetic bibliographic record {key:09d}','Alice Chen','Synthetic venue',2020,'x'*240])
    generated=time.perf_counter()-start;start=time.perf_counter()
    job=folder/'job';storage.import_file(source,job)
    ingest=time.perf_counter()-start;start=time.perf_counter()
    session=storage.build_session(job,max_pairs=10000)
    candidate=time.perf_counter()-start
    known={(i,i+1) for i in range(0,count-1,100)};retrieved=set(map(tuple,session['pairs']))
    result={'records':count,'input_bytes':source.stat().st_size,'generation_seconds':generated,
            'ingestion_seconds':ingest,'candidate_seconds':candidate,
            'working_database_bytes':(job/'records.sqlite').stat().st_size,
            'known_synthetic_duplicate_pairs':len(known),'retrieved_known_pairs':len(known&retrieved),
            'synthetic_candidate_recall':len(known&retrieved)/len(known),'candidate_stats':session['candidate_stats'],
            'scope':'Synthetic ingestion and lexical candidate retrieval only. No neural encoding of the full million-record dataset; no real-world scaling or recall guarantee.'}
    (folder/'result.json').write_text(json.dumps(result,indent=2))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',type=Path,required=True)
    p.add_argument('--sizes',type=int,nargs='+',default=[10000,100000,1000000]);p.add_argument('--child',type=int)
    a=p.parse_args()
    if a.child:worker(a.work,a.child);return
    import psutil
    results=[]
    for count in a.sizes:
        folder=a.work/str(count)
        if (folder/'result.json').exists():raise ValueError('Choose a fresh work directory to avoid mixing measurements.')
        process=subprocess.Popen([sys.executable,__file__,'--work',str(folder),'--child',str(count)])
        monitored=psutil.Process(process.pid);peak=0
        while process.poll() is None:
            try:
                # Windows virtual environments can launch a child interpreter.
                # Include that worker, not just the tiny launcher process.
                total=0
                for member in [monitored]+monitored.children(recursive=True):
                    try:total+=member.memory_info().rss
                    except psutil.NoSuchProcess:pass
                peak=max(peak,total)
            except psutil.NoSuchProcess:pass
            time.sleep(.2)
        if process.returncode:raise RuntimeError(f'Stress worker failed: {count}')
        row=json.loads((folder/'result.json').read_text());row['peak_process_working_set_bytes']=peak
        row['memory_measurement']='Peak sampled sum of worker process and descendants RSS; may double-count shared pages; excludes parent monitor.'
        results.append(row)
        (ROOT/'results/scale_measurements.json').write_text(json.dumps(results,indent=2))
        print(json.dumps(row),flush=True)

if __name__=='__main__':main()
