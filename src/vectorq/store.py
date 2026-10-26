"""Exact cosine development fallback with explicit run and task isolation."""
from dataclasses import asdict, dataclass
import hashlib
import json

from src.embeddings.client import cosine, normalized
from src.vectorq.algorithm import ALGORITHM_VERSION, RegionState


@dataclass
class Entry:
    entry_id: str
    request_key: str
    response: str
    vector: list[float]
    state: RegionState


class CacheStore:
    def __init__(self,db,run_id,model_id,embedding_model):
        self.db,self.run_id,self.model_id,self.embedding_model=db,run_id,model_id,embedding_model
        self._vector_cache={}
        if not db.execute('SELECT 1 FROM experiment_runs WHERE run_id=?',(run_id,)).fetchone():
            raise ValueError('Create an isolated experiment run before opening cache')

    def _namespace(self,version,task):
        return (self.run_id,version,task.predicate_id,task.prompt_version,self.model_id,self.embedding_model)

    def entries(self,version,task,entry_id=None):
        extra=' AND entry_id=?' if entry_id else ''
        rows=self.db.execute('''SELECT * FROM cache_entries WHERE run_id=? AND dataset_version=?
            AND predicate_id=? AND prompt_version=? AND model_id=? AND embedding_model=?
            '''+extra+' ORDER BY rowid',self._namespace(version,task)+((entry_id,) if entry_id else ())).fetchall()
        entries=[]
        for row in rows:
            if row['algorithm_version']!=ALGORITHM_VERSION:raise ValueError('Incompatible cache algorithm')
            data=json.loads(row['metadata_json'])
            if data.pop('task_fingerprint',None)!=task.fingerprint:raise ValueError('Changed task definition in cache')
            state=RegionState(**data)
            state.validate()
            if row['response'] not in {'YES','NO'}:raise ValueError('Corrupt cache response')
            entries.append(Entry(row['entry_id'],row['request_key'],row['response'],
                                 normalized(json.loads(row['embedding_json'])),state))
        return entries

    def nearest(self,version,task,vector):
        vector=normalized(vector)
        rows=self.db.execute('''SELECT entry_id,embedding_json FROM cache_entries WHERE run_id=? AND dataset_version=?
            AND predicate_id=? AND prompt_version=? AND model_id=? AND embedding_model=? ORDER BY rowid''',
            self._namespace(version,task)).fetchall()
        if not rows:return None,None
        import numpy as np
        vectors=[]
        for row in rows:
            raw=row['embedding_json']
            cached=self._vector_cache.get(row['entry_id'])
            if cached is None or cached[0]!=raw:
                cached=(raw,normalized(json.loads(raw)))
                self._vector_cache[row['entry_id']]=cached
            if len(cached[1])!=len(vector):raise ValueError('Embedding dimensions differ')
            vectors.append(cached[1])
        scores=np.clip(np.asarray(vectors,dtype=np.float64)@np.asarray(vector,dtype=np.float64),0,1)
        index=int(np.argmax(scores));score=float(scores[index]);entry_id=rows[index]['entry_id']
        return self.entries(version,task,entry_id)[0],score

    def exact(self,version,task,key):
        return next((e for e in self.entries(version,task) if e.request_key==key),None)

    def insert(self,version,task,text,label,vector,grid_size=1001,decay=10):
        if label not in {'YES','NO'}:raise ValueError('Invalid cache label')
        vector=normalized(vector)
        state=RegionState(log_posterior=[0.0]*grid_size,decay=decay)
        state.validate()
        key=hashlib.sha256(text.encode()).hexdigest()
        count=self.db.execute('SELECT count(*) FROM cache_entries WHERE run_id=?',(self.run_id,)).fetchone()[0]
        entry_id=hashlib.sha256((self.run_id+':'+str(count)+':'+key).encode()).hexdigest()
        metadata={**asdict(state),'task_fingerprint':task.fingerprint}
        self.db.execute('''INSERT INTO cache_entries
            (entry_id,run_id,dataset_version,predicate_id,prompt_version,model_id,embedding_model,
            request_key,request_text,response,embedding_json,metadata_json,algorithm_version)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (entry_id,*self._namespace(version,task),key,text,label,json.dumps(vector),
             json.dumps(metadata),ALGORITHM_VERSION))
        return Entry(entry_id,key,label,vector,state)

    def update(self,entry,task):
        entry.state.validate()
        changed=self.db.execute('UPDATE cache_entries SET metadata_json=? WHERE entry_id=? AND run_id=?',
                               (json.dumps({**asdict(entry.state),'task_fingerprint':task.fingerprint}),
                                entry.entry_id,self.run_id)).rowcount
        if changed!=1:raise ValueError('Cache entry disappeared during update')

    def reset(self):
        self.db.execute('DELETE FROM cache_entries WHERE run_id=?',(self.run_id,))
        self._vector_cache.clear()
