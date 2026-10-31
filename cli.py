"""Twin Finder terminal interface; desktop uses these same application services."""
import argparse
import json
from pathlib import Path
import storage
import twin_workflow as workflow

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['start','import','prepare','inspect','review','counts','propose','activate','rollback','export'])
    p.add_argument('--job',required=True,type=Path)
    p.add_argument('--input',type=Path)
    p.add_argument('--mapping')
    p.add_argument('--pair',type=int,default=1)
    p.add_argument('--decision',choices=['accept','reject','skip'])
    p.add_argument('--proposal',type=int)
    p.add_argument('--version',type=int,default=0)
    p.add_argument('--max-pairs',type=int,default=10000)
    p.add_argument('--budget',type=int,default=3000000)
    p.add_argument('--output',type=Path)
    a=p.parse_args(argv)
    if a.command=='start':
        if not a.input:p.error('--input is required')
        import progressive
        result=progressive.run(a.input,a.job,json.loads(a.mapping) if a.mapping else None,max_pairs=a.max_pairs,budget=a.budget)
    elif a.command=='import':
        if not a.input:p.error('--input is required')
        with storage.job_lock(a.job):result=storage.import_file(a.input,a.job,json.loads(a.mapping) if a.mapping else None)
    elif a.command=='prepare':result=workflow.prepare(a.job,max_pairs=a.max_pairs,budget=a.budget)
    elif a.command=='inspect':result=workflow.inspect(a.job,a.pair)
    elif a.command=='review':
        if not a.decision:p.error('--decision is required')
        result=workflow.review(a.job,a.pair,a.decision)
    elif a.command=='counts':result=workflow.feedback_counts(a.job)
    elif a.command=='propose':result=workflow.propose_update(a.job)
    elif a.command=='activate':
        if a.proposal is None:p.error('--proposal is required')
        result=workflow.activate(a.job,a.proposal)
    elif a.command=='rollback':result=workflow.rollback(a.job,a.version)
    else:
        if not a.output:p.error('--output is required')
        with storage.job_lock(a.job):result=storage.export_cleaned(a.job,a.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result

if __name__=='__main__':main()
