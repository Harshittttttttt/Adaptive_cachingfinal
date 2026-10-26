import hashlib
import json
import math
import os
from time import perf_counter

from src.llm.client import post_json


def normalized(vector):
    if not isinstance(vector, (list,tuple)) or not vector or not all(
        isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in vector):
        raise ValueError('Invalid embedding vector')
    norm=math.sqrt(sum(x*x for x in vector))
    if not math.isfinite(norm) or norm==0:
        raise ValueError('Embedding must have finite nonzero norm')
    return [x/norm for x in vector]


def cosine(left,right):
    if len(left)!=len(right):
        raise ValueError('Embedding dimensions differ')
    a,b=normalized(left),normalized(right)
    # Paper v1 defines similarities on [0,1]. Explicitly clip negative cosine.
    return max(0.0,min(1.0,sum(x*y for x,y in zip(a,b))))


class EmbeddingClient:
    def __init__(self,config,transport=post_json):
        self.config=dict(config)
        self.model=config['model']
        if not self.model:raise ValueError('Configure embedding model')
        self.provider=config.get('provider','mistral')
        self.base=config.get('base_url','https://api.mistral.ai/v1').rstrip('/')
        self.transport=transport
        self.model_id=self.provider+':'+self.model+':'+hashlib.sha256(self.base.encode()).hexdigest()[:12]
        self.requests=[]

    def embed(self,text):
        if not isinstance(text,str) or not text.strip():raise ValueError('Empty embedding input')
        if self.provider=='mistral':
            key=os.environ.get(self.config.get('api_key_env','MISTRAL_API_KEY'))
            if not key:raise ValueError('MISTRAL_API_KEY is not configured')
            url=self.base+'/embeddings'
            payload=dict(model=self.model,input=[text],encoding_format='float')
            headers={'Authorization':'Bearer '+key}
        elif self.provider=='ollama':
            url=self.base+'/api/embed'
            payload=dict(model=self.model,input=text,truncate=False)
            headers={}
        else:raise ValueError('Unsupported embedding provider')
        tick=perf_counter()
        record=dict(model_id=self.model_id,latency_seconds=None,status='failed',input_tokens=None,
                    estimated_cost_usd=None)
        try:
            data=self.transport(url,payload,headers,self.config.get('timeout_seconds',60))
            if self.provider=='mistral':
                vector=data['data'][0]['embedding']
                record['input_tokens']=(data.get('usage') or {}).get('prompt_tokens')
                tokens=record['input_tokens']
                if isinstance(tokens,int) and not isinstance(tokens,bool) and tokens>=0:
                    rate=self.config.get('input_per_million_usd')
                    if rate is not None:record['estimated_cost_usd']=tokens*rate/1e6
            else:
                vector=data['embeddings'][0]
                record['input_tokens']=data.get('prompt_eval_count')
            vector=normalized(vector)
            record['status']='success'
            return vector
        finally:
            record['latency_seconds']=perf_counter()-tick
            self.requests.append(record)
