"""Synthetic resolver-only timing; no models or production database access."""
import argparse
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from src.intelligence.context import resolve_context
from src.intelligence.persona import SYSTEM_INSTRUCTION, HISTORY_OMITTED
from src.intelligence.prompt_budget import bounded_context
from src.storage.conversation_store import ConversationStore
from src.intelligence.conversation import ConversationSession


def benchmark(output):
    results={}
    with TemporaryDirectory(prefix='aika-q1b-timing-') as root:
        store=ConversationStore(Path(root))
        session=ConversationSession(SYSTEM_INSTRUCTION,2,lambda _:None,store)
        with store._transaction(write=True) as db:
            for i in range(1000):
                text='The prototype export format is SVG.' if i==980 else f'Coffee note {i}.'
                pair=(text,'Synthetic acknowledgement.')
                session._sequence=store.save_exchange(session.session_id,session._sequence,*pair,connection=db)
                session._turns.append(pair)
        history=session.history(for_model=True)
        for mode in ('legacy','q1b','q1b-nonreference'):
            samples=[]; reads=[]; sizes=[]; calls=[]
            for _ in range(100):
                prompt='Hello there.' if mode=='q1b-nonreference' else 'What export format did I choose earlier?'
                started=perf_counter()
                if mode=='legacy':
                    messages,_=bounded_context(SYSTEM_INSTRUCTION+HISTORY_OMITTED,history,prompt,24000)
                    read=0.0; count=0
                else:
                    count=0
                    def load():
                        nonlocal count
                        count+=1
                        return store.context_statements(session.session_id,session._sequence)
                    selected=resolve_context(SYSTEM_INSTRUCTION,history,prompt,24000,turns=2,
                        sequence=session._sequence,load=load,allowed=session._model_history_allowed,redact=lambda s:s)
                    messages=selected.messages;read=selected.metadata['retrieval_ms']
                samples.append((perf_counter()-started)*1000)
                reads.append(read);calls.append(count);sizes.append(sum(len(m['content']) for m in messages))
            def stats(values):
                return {'median':round(median(values),3),'p95':round(sorted(values)[94],3),'min':round(min(values),3),'max':round(max(values),3)}
            results[mode]={'assembly_ms':stats(samples),'sqlite_ms':stats(reads),'input_characters':stats(sizes),'sqlite_queries':stats(calls)}
    data={'iterations_per_mode':100,'synthetic_exchanges':1000,'model_calls':0,'results':results}
    Path(output).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(data,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    benchmark(parser.parse_args().output)
