"""Convert pinned pretrained MiniLM to a verified offline TorchScript artifact."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ai_model import ROOT,REVISION


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--download',action='store_true',help='Allow downloading the pinned public model if not cached')
    args=p.parse_args()
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(2)
    source=SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2',revision=REVISION,local_files_only=not args.download,device='cpu')
    source[0].auto_model.set_attn_implementation('eager')
    class Wrapper(torch.nn.Module):
        def __init__(self,bert):
            super().__init__();self.bert=bert
        def forward(self,ids,mask,types):
            hidden=self.bert(input_ids=ids,attention_mask=mask,token_type_ids=types,return_dict=False)[0]
            weights=mask.unsqueeze(-1).to(hidden.dtype)
            pooled=(hidden*weights).sum(1)/weights.sum(1).clamp(min=1e-9)
            return torch.nn.functional.normalize(pooled,p=2,dim=1)
    model=Wrapper(source[0].auto_model).eval()
    tokens=source.tokenizer(['graph indexes','bibliographic quality'],padding='max_length',truncation=True,max_length=256,return_tensors='pt')
    with torch.inference_mode():
        traced=torch.jit.trace(model,(tokens['input_ids'],tokens['attention_mask'],tokens['token_type_ids']),strict=False)
        traced=torch.jit.freeze(traced)
    folder=ROOT/'models';folder.mkdir(exist_ok=True)
    traced.save(str(folder/'encoder.pt'))
    source.tokenizer.backend_tokenizer.save(str(folder/'tokenizer.json'))
    sha=lambda name:hashlib.sha256((folder/name).read_bytes()).hexdigest()
    manifest={'model':'sentence-transformers/all-MiniLM-L6-v2','revision':REVISION,'license':'Apache-2.0',
              'pooling':'attention-masked mean then L2 normalization','max_tokens':256,'dimension':384,
              'sha256':{name:sha(name) for name in ('encoder.pt','tokenizer.json')}}
    (folder/'encoder_manifest.json').write_text(json.dumps(manifest,indent=2))
    from ai_model import Encoder
    runtime=Encoder()
    cases=['','hello','Graph indexing for scholarly libraries','Étude des données bibliographiques','long title '*400]
    expected=source.encode([t.strip().casefold() for t in cases],normalize_embeddings=True,batch_size=2)
    deltas=[]
    for batch in [1,2,8]:
        actual=runtime.encode(cases,batch)
        deltas.append(float(np.max(np.abs(expected-actual))))
        assert np.allclose(expected,actual,atol=2e-5),deltas
    manifest['reference_max_absolute_error']=max(deltas)
    (folder/'encoder_manifest.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps(manifest,indent=2))

if __name__=='__main__':main()
