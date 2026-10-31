"""Measure the progressive engine on a supplied real input, without review labels.

Run against a NEW job. Timing includes import, discovery, model load, scoring
and final source hashing; it excludes application launch and file-picker time.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psutil
import progressive
import storage


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.job.exists():raise ValueError('Use a new job folder for an uncached run.')
    process=psutil.Process();peak=[process.memory_info().rss];done=threading.Event()
    def monitor():
        while not done.wait(.1):peak[0]=max(peak[0],process.memory_info().rss)
    thread=threading.Thread(target=monitor,daemon=True);thread.start()
    milestones={};start=time.perf_counter()
    def progress(message):
        if 'AI-scored pairs ready' in message:
            count=int(message.split()[0].replace(',',''))
            for target in [1,50,500,1000,5000,10000]:
                if count>=target and str(target) not in milestones:
                    milestones[str(target)]=time.perf_counter()-start
                    print(f'{count} pairs ready after {milestones[str(target)]:.2f}s',flush=True)
    try:result=progressive.run(args.input,args.job,progress=progress)
    finally:done.set();thread.join()
    result.update(wall_seconds=time.perf_counter()-start,peak_process_mib=peak[0]/1024**2,
                  milestones=milestones,input_bytes=args.input.stat().st_size,
                  input_sha256=storage.file_hash(args.input),
                  source_sha256={name:hashlib.sha256((Path(__file__).resolve().parents[1]/name).read_bytes()).hexdigest()
                                 for name in ['progressive.py','ai_model.py','storage.py','twin_workflow.py']},
                  interpretation='One run on this computer; sampled process memory, not whole-system RAM. Discovery-order bounded queue, not globally ranked. No accuracy claim.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
