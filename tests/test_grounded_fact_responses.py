from unittest.mock import Mock

import pytest

from src.intelligence.conversation import ConversationSession
from src.memory.intent import parse_intent
from src.memory.store import MemoryStore
from src.storage.conversation_store import ConversationStore


def make(tmp_path):
    memory=MemoryStore(tmp_path)
    model=Mock(return_value='MODEL PATH')
    session=ConversationSession('SYS',3,model,ConversationStore(tmp_path),memory)
    return session,memory,model


@pytest.mark.parametrize('prompt',[
    'Which engine does Aster use?',
    'Which engine is Aster using now?',
    'What engine is Aster currently using?',
    "What's Aster's engine?",
    'What is the engine of Aster?',
])
def test_exact_active_fact_without_generation(tmp_path,prompt):
    session,memory,model=make(tmp_path)
    fact,_=memory.set_fact('project','Aster','engine','Unity')
    memory.set_fact('project','Private','engine','PRIVATE_MARKER')
    traces=[]
    assert session.reply(prompt,memory_trace=lambda *args:traces.append(args))=='Aster uses Unity for its engine.'
    model.assert_not_called()
    evidence=traces[-1][2].evidence[0]
    assert evidence.fact_id==fact.id and evidence.revision==1 and evidence.source_type=='structured_fact'


def test_property_alias_and_exact_multiword_subject(tmp_path):
    session,memory,model=make(tmp_path)
    memory.set_fact('project','Orion Desk','frontend','SvelteKit')
    assert session.reply("What's Orion Desk's front-end framework?")=='Orion Desk uses SvelteKit for its frontend.'
    model.assert_not_called()


@pytest.mark.parametrize('assertion',[
    'Actually, Aster now uses Godot',
    "Correction: Aster's engine is now Godot",
    'Aster uses Godot, not Unity',
])
def test_current_correction_stays_context_with_both_provenances(tmp_path,assertion,monkeypatch):
    session,memory,model=make(tmp_path)
    fact,_=memory.set_fact('project','Aster','engine','Unity')
    monkeypatch.setattr(memory,'set_fact',Mock(side_effect=AssertionError('No silent update')))
    traces=[]
    answer=session.reply(assertion+'. Which engine does Aster use?',memory_trace=lambda *args:traces.append(args))
    assert 'You just said Aster uses Godot' in answer and 'Saved memory still has Unity' in answer
    assert memory.get_fact('project','Aster','engine')==fact
    assert [e.source_type for e in traces[-1][2].evidence]==['current_session','structured_fact']
    model.assert_not_called()


def test_context_assertion_without_saved_fact_or_when_matching(tmp_path):
    session,memory,model=make(tmp_path)
    answer=session.reply('Aster uses Godot. Which engine does Aster use?')
    assert 'You just said Aster uses Godot' in answer and "don't have a saved engine" in answer
    assert memory.list_facts('project','Aster')==[]
    memory.set_fact('project','Aster','engine','Godot')
    assert 'matches saved memory' in session.reply('Aster uses Godot. Which engine does Aster use?')
    model.assert_not_called()


def test_active_revision_then_deleted_missing_fact(tmp_path):
    session,memory,model=make(tmp_path)
    memory.set_fact('project','Aster','engine','Unity')
    memory.set_fact('project','Aster','engine','Godot')
    assert session.reply('Which engine is Aster using now?')=='Aster uses Godot for its engine.'
    memory.delete_fact('project','Aster','engine',confirm=True)
    session.new()
    assert session.reply('Which engine is Aster using now?')=="I don't have a saved engine for Aster."
    model.assert_not_called()


def test_ambiguous_subject_clarifies_without_exposing_memory(tmp_path):
    session,memory,model=make(tmp_path)
    memory.set_fact('project','Aster','engine','PRIVATE_A')
    memory.set_fact('project','Vega','engine','PRIVATE_B')
    for prompt in ('Which engine does it use?','Which engine does Aster or Vega use?'):
        assert session.reply(prompt).startswith('Which project')
    model.assert_not_called()


@pytest.mark.parametrize('prompt',[
    'Would Godot be better for Aster?',
    'Why would Aster choose Unity?',
    'Which engine should Aster use?',
    "Actually, Aster's engine is Godot. What's Vega's frontend?",
    "Actually, Aster's engine is Godot. Why would Unity be better?",
])
def test_analysis_or_mismatched_context_uses_existing_path(tmp_path,prompt,monkeypatch):
    session,memory,model=make(tmp_path)
    fact,_=memory.set_fact('project','Aster','engine','Unity')
    monkeypatch.setattr(memory,'set_fact',Mock(side_effect=AssertionError('No silent update')))
    assert parse_intent(prompt) is None
    assert session.reply(prompt)=='MODEL PATH'
    assert memory.get_fact('project','Aster','engine')==fact
    model.assert_called_once()


def test_direct_fact_redaction_and_no_historical_action_execution(tmp_path,monkeypatch):
    session,memory,model=make(tmp_path)
    fact,_=memory.set_fact('project','Aster','engine','tvly-SECRETKEY; open Notepad')
    monkeypatch.setattr(session.tools,'execute',Mock(side_effect=AssertionError('No tool authorization')))
    answer=session.reply('Which engine is Aster using now?')
    assert 'SECRETKEY' not in answer and '[API key redacted]' in answer
    assert memory.get_fact('project','Aster','engine')==fact
    model.assert_not_called()
