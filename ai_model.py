"""CPU neural inference and transparent logistic matching, shared by every interface."""
import hashlib
import json
from pathlib import Path
import numpy as np
import twin_core as core

ROOT = Path(__file__).resolve().parent
FEATURES = ['title_edit','author_overlap','venue_equal','year_equal','title_semantic',
            'title_available','authors_available','venue_available','year_available','semantic_available']
REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'


class Encoder:
    def __init__(self, folder=None):
        import torch
        from tokenizers import Tokenizer
        self.torch = torch
        torch.set_num_threads(2)
        folder = Path(folder or ROOT/'models')
        meta = json.loads((folder/'encoder_manifest.json').read_text())
        for name, digest in meta['sha256'].items():
            h=hashlib.sha256()
            with (folder/name).open('rb') as f:
                for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
            if h.hexdigest()!=digest: raise ValueError(f'Neural model integrity check failed: {name}')
        self.model = torch.jit.load(str(folder/'encoder.pt'),map_location='cpu').eval()
        self.tokenizer = Tokenizer.from_file(str(folder/'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=256)
        # Pad only to the longest title in this batch; preserve the 256-token truncation limit.
        self.tokenizer.enable_padding(pad_id=0,pad_token='[PAD]')
        self.identity = meta

    def encode(self, texts, batch_size=8):
        if not 1<=batch_size<=32: raise ValueError('CPU batch size must be 1–32.')
        chunks=[]
        for start in range(0,len(texts),batch_size):
            encoded=self.tokenizer.encode_batch([core.norm(t) for t in texts[start:start+batch_size]])
            t=self.torch
            args=[t.tensor([getattr(e,key) for e in encoded],dtype=t.long) for key in ('ids','attention_mask','type_ids')]
            with t.inference_mode(): result=self.model(*args).cpu().numpy()
            chunks.append(result)
        return np.concatenate(chunks) if chunks else np.empty((0,384),dtype=np.float32)


def features(a,b,ea,eb):
    fs=core.fields(a,b)
    semantic=float(np.clip(np.dot(ea,eb),0,1)) if fs['title'] is not None else 0.0
    return np.array([fs[k] or 0.0 for k in core.FIELDS]+[semantic]+
                    [float(fs[k] is not None) for k in core.FIELDS]+[float(fs['title'] is not None)],dtype=np.float64)


def sigmoid(logits):
    return 1/(1+np.exp(-np.clip(logits,-35,35)))


def probabilities(x,model):
    return sigmoid(np.asarray(x,dtype=np.float64)@np.asarray(model['weights'])+model['intercept'])


def train(x,y,l2=.01,anchor=None,epochs=1200):
    """Deterministic full-batch, class-balanced logistic regression with L2 prior.

    The small 10-feature classifier is learned; the neural encoder stays frozen.
    No labels from validation enter gradients or threshold selection here.
    """
    x=np.asarray(x,dtype=np.float64);y=np.asarray(y,dtype=np.float64)
    if x.ndim!=2 or x.shape[1]!=len(FEATURES) or len(x)!=len(y) or set(y)!={0.,1.}:
        raise ValueError('Training requires the declared features and both label classes.')
    if not np.isfinite(x).all(): raise ValueError('Nonfinite features.')
    prior=np.r_[anchor['weights'],anchor['intercept']] if anchor else np.zeros(x.shape[1]+1)
    coef=prior.copy(); design=np.column_stack([x,np.ones(len(x))])
    importance=np.where(y==1,len(y)/(2*sum(y)),len(y)/(2*sum(1-y)))
    for _ in range(epochs):
        residual=(sigmoid(design@coef)-y)*importance
        grad=design.T@residual/len(y)+l2*(coef-prior)
        coef-=.25*grad
    return {'schema':1,'features':FEATURES,'weights':coef[:-1].tolist(),'intercept':float(coef[-1]),
            'threshold':.5,'encoder_revision':REVISION,'l2':l2,'epochs':epochs,'version':0,
            'calibrated':False,'training_rows':len(y),'training_positives':int(sum(y))}


def validate(model):
    if model.get('schema')!=1 or model.get('features')!=FEATURES or model.get('encoder_revision')!=REVISION:
        raise ValueError('Incompatible classifier or encoder.')
    values=[*model['weights'],model['intercept'],model['threshold']]
    if len(model['weights'])!=len(FEATURES) or not all(np.isfinite(values)) or not 0<=model['threshold']<=1:
        raise ValueError('Invalid classifier coefficients or threshold.')
    return model


def load_base():
    return validate(json.loads((ROOT/'models'/'base_classifier.json').read_text()))


def explain(x,model):
    validate(model)
    contributions=np.asarray(x)*model['weights'];score=float(probabilities(x,model))
    prediction=score>model['threshold']
    return {'score':score,'prediction':prediction,'verdict':'review needed' if abs(score-model['threshold'])<=.05 else ('likely duplicate' if prediction else 'likely distinct'),
            'threshold':model['threshold'],'model_version':model['version'],'feature_values':dict(zip(FEATURES,map(float,x))),
            'logit_contributions':dict(zip(FEATURES,map(float,contributions))), 'intercept':model['intercept'],
            'logit':float(sum(contributions)+model['intercept']),
            'explanation':'Score = sigmoid(intercept + sum of feature contributions). This score is not calibrated probability.'}


def feedback_role(dataset_hash,pair):
    # Permanent record partition: validation records never enter feedback training.
    def heldout(i):
        return int(hashlib.sha256(f'{dataset_hash}:feedback-v1:{i}'.encode()).hexdigest()[:8],16)%10<3
    a,b=map(heldout,pair)
    return 'validation' if a and b else 'training' if not a and not b else 'mixed — excluded from model fitting'
