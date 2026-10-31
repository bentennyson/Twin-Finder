"""Generate report figures from measured outputs, plus benchmark candidate coverage."""
import csv
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import ai_model as ai
import twin_core as core
from research.evaluate import read

def main():
    out=ai.ROOT/'results';fig=out/'figures';fig.mkdir(exist_ok=True)
    rows=read(out/'test_metrics.csv');names=['Neural + metadata','Metadata only','Title neural + edit','Title edit','Title neural']
    plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    f,ax=plt.subplots(figsize=(9,4.8));values=[float(r['f1'])*100 for r in rows]
    ax.barh(names[::-1],values[::-1],color=['#77a9bb']*4+['#136f63']);ax.set_xlim(0,105);ax.set_xlabel('F1 (%) on 535 retrospective test pairs')
    for i,v in enumerate(values[::-1]):ax.text(v+.5,i,f'{v:.2f}',va='center')
    f.tight_layout();f.savefig(fig/'figure_1_benchmark.png',dpi=180);plt.close(f)
    f,ax=plt.subplots(figsize=(8,4.5));x=np.arange(len(rows));w=.36
    ax.bar(x-w/2,[float(r['precision'])*100 for r in rows],w,label='Precision',color='#136f63')
    ax.bar(x+w/2,[float(r['recall'])*100 for r in rows],w,label='Recall',color='#77a9bb');ax.set_xticks(x,names,rotation=15,ha='right');ax.set_ylim(0,105);ax.set_ylabel('Percent');f.legend(loc='upper center',ncol=2);f.tight_layout(rect=[0,0,1,.9]);f.savefig(fig/'figure_2_precision_recall.png',dpi=180);plt.close(f)
    scale=json.loads((out/'scale_measurements.json').read_text());f,axes=plt.subplots(1,2,figsize=(10,4.5))
    labels=[f"{r['records']:,}" for r in scale]
    axes[0].bar(labels,[r['ingestion_seconds'] for r in scale],color='#136f63');axes[0].set_ylabel('Ingestion seconds');axes[0].tick_params(axis='x',rotation=15)
    axes[1].bar(labels,[r['peak_process_working_set_bytes']/1024**2 for r in scale],color='#77a9bb');axes[1].set_ylabel('Peak worker process tree RSS (MiB)');axes[1].tick_params(axis='x',rotation=15)
    f.suptitle('Synthetic CSV ingestion and lexical retrieval — excludes neural encoding');f.tight_layout();f.savefig(fig/'figure_3_scale.png',dpi=180);plt.close(f)
    replay=json.loads((out/'feedback_replay.json').read_text());p=replay['proposal'];f,ax=plt.subplots(figsize=(6.8,4.5));x=np.arange(3)
    ax.bar(x-.18,[p['before'][k]*100 for k in ('precision','recall','f1')],.36,label='Before',color='#77a9bb')
    ax.bar(x+.18,[p['after'][k]*100 for k in ('precision','recall','f1')],.36,label='Proposed update',color='#136f63');ax.set_xticks(x,['Precision','Recall','F1']);ax.set_ylim(0,105);ax.set_ylabel('Agreement with replayed labels (%)');ax.set_title('Development validation on 45 replay pairs');f.legend(loc='lower center',ncol=2);f.tight_layout(rect=[0,.1,1,1]);f.savefig(fig/'figure_4_feedback.png',dpi=180);plt.close(f)
    records=[row for name in ('tableA.csv','tableB.csv') for row in read(ai.ROOT/'data/dblp_acm'/name)]
    left=read(ai.ROOT/'data/dblp_acm/tableA.csv');right=read(ai.ROOT/'data/dblp_acm/tableB.csv')
    ia={r['id']:i for i,r in enumerate(left)};ib={r['id']:i+len(left) for i,r in enumerate(right)}
    known={(ia[r['ltable_id']],ib[r['rtable_id']]) for s in ('train','valid','test') for r in read(ai.ROOT/f'data/dblp_acm/{s}.csv') if int(r['label'])==1}
    candidates,stats=core.candidates(records,max_pairs=10000);found=set(map(tuple,candidates))
    coverage={'records':len(records),'known_positive_pairs':len(known),'retrieved_known_positive_pairs':len(known&found),
              'known_pair_candidate_recall':len(known&found)/len(known),'candidate_stats':stats,
              'limitations':'Recall against supplied positive links, not all true duplicates. Queue mixes within-source and cross-source pairs; unlabelled pairs are not counted as false positives. Small in-memory reference is tested against the disk implementation.'}
    (out/'candidate_coverage.json').write_text(json.dumps(coverage,indent=2))
    diagram='''flowchart TD
  A[CSV or JSONL on local disk] --> B[Resumable SQLite import]
  B --> C[Bounded lexical candidate discovery]
  C --> D[Frozen MiniLM title embeddings]
  B --> E[Metadata comparison features]
  D --> F[Learned logistic matching classifier]
  E --> F
  F --> G[Scores and additive feature explanations]
  G --> H[Human accept reject or skip]
  H --> I[Fixed record partition for feedback]
  I --> J[Train proposed classifier on training feedback]
  J --> K[Validate and explicitly activate or reject]
  K --> F
  H --> L[Stream reviewed merges and audit ZIP]
'''
    (fig/'architecture.mmd').write_text(diagram)
    print(json.dumps(coverage,indent=2))

if __name__=='__main__':main()
