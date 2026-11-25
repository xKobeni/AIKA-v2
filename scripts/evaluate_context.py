"""Finite, sequential synthetic context comparison; no production data or service changes."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from types import MethodType
from unittest.mock import patch

from src.config import load_config
from src.intelligence.conversation import ConversationSession
from src.intelligence.ollama_client import OllamaClient
from src.intelligence.persona import SYSTEM_INSTRUCTION,HISTORY_OMITTED
from src.intelligence.prompt_budget import bounded_context
from src.capabilities.intent import guard_action_claim
from src.capabilities.system_intent import guard_system_claim
from src.capabilities.web_intent import guard_web_claim
from src.capabilities.web_budget import request_budget
from src.memory.chat import ordinary_statement_reply
from src.memory.store import MemoryStore
from src.storage.conversation_store import ConversationStore

def baseline(self,prompt,trace):
    started=perf_counter()
    system=self.web_search.redact(self._system_instruction)
    history=self.history(for_model=True)
    messages,trimmed=bounded_context(system,history,prompt,self._context_chars)
    omitted=trimmed or self._sequence//2>(len(messages)-2)//2
    if omitted:messages,_=bounded_context(system+HISTORY_OMITTED,history,prompt,self._context_chars)
    self.last_context={'source':'legacy_recent_suffix','message_ids':[],'omitted':omitted,'assembly_ms':round((perf_counter()-started)*1000,3),'retrieval_ms':0}
    if trace:trace(self.session_id,messages,(len(messages)-2)//2,omitted)
    answer=self._generate(messages)
    return guard_web_claim(guard_system_claim(guard_action_claim(ordinary_statement_reply(answer))))

def evaluate(output):
    folder=Path(output)
    folder.mkdir(exist_ok=False)
    cases=json.loads((Path(__file__).resolve().parents[1]/'tests/fixtures/q1b_continuity.json').read_text(encoding='utf-8'))
    state={'date':'2026-11-24','status':'running','note':'Synthetic prior user history with fixed acknowledgements, not end-to-end generated setup. Only target replies are live. Three fresh repetitions of important cases; no model or service change.', 'trials':[],'generation_limit':40,'seconds_limit':1500,
           'resolver_sha256':hashlib.sha256((Path(__file__).resolve().parents[1]/'src/intelligence/context.py').read_bytes()).hexdigest(),
           'fixtures':cases}
    path=folder/'LIVE.json'
    def save():path.write_text(json.dumps(state,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    calls=0
    with TemporaryDirectory(prefix='aika-q1b-live-') as root, request_budget(1500), patch('src.capabilities.executor.ToolExecutor.execute',side_effect=AssertionError('No tools')), patch.object(MemoryStore,'set_fact',side_effect=AssertionError('No memory writes')):
        settings=replace(load_config(),data_dir=Path(root),web_search_enabled=False,web_reading_enabled=False,tavily_api_key='')
        with OllamaClient(settings) as client:
            model=client.check_model()
            state.update(model=settings.model,model_digest=model.get('digest'),thinking=settings.ollama_think,
                         context_chars=settings.context_chars,response_tokens=settings.response_tokens,
                         persona_sha256=hashlib.sha256(SYSTEM_INSTRUCTION.encode()).hexdigest())
            assert settings.model=='qwen3.5:4b' and settings.ollama_think=='off'
            save()
            for case in cases:
                for repetition in range(case['repetitions']):
                    for mode in (('baseline','q1b') if repetition%2==0 else ('q1b','baseline')):
                        row={'id':case['id'],'mode':mode,'repetition':repetition,'status':'running','model_calls':0,'raw_model_final':None,'human_review':None}
                        state['trials'].append(row);save()
                        def generate(messages):
                            nonlocal calls
                            calls+=1
                            assert calls<=40
                            row['model_calls']+=1
                            row['input_characters']=sum(len(m['content']) for m in messages)
                            row['raw_model_final']=client.generate(messages)
                            row['output_characters']=len(row['raw_model_final'])
                            return row['raw_model_final']
                        directory=Path(root)/f"{case['id']}-{mode}-{repetition}"
                        store=ConversationStore(directory)
                        session=ConversationSession(SYSTEM_INSTRUCTION,case['turns'],generate,store,MemoryStore(directory))
                        for statement in case['history']:
                            pair=(statement,'Synthetic acknowledgement.')
                            session._sequence=store.save_exchange(session.session_id,session._sequence,*pair)
                            session._turns.append(pair)
                        if mode=='baseline':session._ordinary_reply=MethodType(baseline,session)
                        traces=[]
                        started=perf_counter()
                        try:
                            row['answer']=session.reply(case['prompt'],trace=lambda _id,messages,_included,_omitted:traces.append(messages))
                            row['status']='complete'
                        except Exception as e:
                            row['status']='error';row['error_type']=type(e).__name__
                        row['wall_ms']=round((perf_counter()-started)*1000,3)
                        row['context']=session.last_context
                        row['assembled_messages']=traces[-1] if traces else []
                        row['selected_input_characters']=sum(len(m['content']) for m in row['assembled_messages'])
                        text=json.dumps(row['assembled_messages'],ensure_ascii=False)
                        row['evidence_selected']=all(item in text for item in case['evidence'])
                        if case.get('clarification'):
                            row['context_selection_pass']=bool(session.last_context.get('clarification_needed')) if mode=='q1b' else None
                        else:row['context_selection_pass']=row['evidence_selected']
                        save()
                        print(case['id'],mode,repetition,row['status'],flush=True)
    state.update(status='complete',model_calls=calls)
    save()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ollama',action='store_true',required=True,help='Explicitly enable live local-model calls.')
    parser.add_argument('--output',required=True,help='New output directory; existing evidence is never overwritten.')
    args=parser.parse_args()
    evaluate(args.output)
