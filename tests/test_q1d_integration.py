import json
from unittest.mock import Mock

import pytest

from test_tool_result_followups import make,snapshot
from test_tool_result_analysis import setup_snapshot
from src.capabilities.tool_followup import ANALYSIS_REJECTED


def test_memory_assertion_and_verified_measurement_are_distinct(tmp_path,monkeypatch):
    session,model=make(tmp_path)
    session.reply('Remember that my project Nova uses Unity.')
    fact=session._memory.get_fact('project','Nova','engine')
    traces=[]
    assert 'Unity' in session.reply('Which engine does Nova use?')
    answer=session.reply('Actually, Nova now uses Godot. Which engine does Nova use?',memory_trace=lambda *args:traces.append(args))
    assert 'You just said Nova uses Godot' in answer and 'Saved memory still has Unity' in answer
    assert [e.source_type for e in traces[-1][2].evidence]==['current_session','structured_fact']
    setup_snapshot(session,cpu=85)
    assert '85.0%' in session.reply('What was my CPU usage?')
    model.return_value=json.dumps({'measurement':'85.0%','analysis':'The earlier sample showed high utilization. It does not confirm whether performance will degrade right now.'})
    monkeypatch.setattr(session._memory,'set_fact',Mock(side_effect=AssertionError('No implicit writes')))
    answer=session.reply('Is my CPU usage high?')
    assert 'Earlier snapshot: CPU usage 85.0%' in answer and 'not a current measurement' in answer
    assert 'does not confirm whether' in answer
    model.assert_called_once();assert session.tools.execute.call_count==1
    packet=json.loads(model.call_args.args[0][1]['content'])
    assert packet['evidence']['measurements']=={'cpu_usage':'85.0%'}
    assert 'Unity' not in str(packet) and 'Godot' not in str(packet)
    assert session._memory.get_fact('project','Nova','engine')==fact


@pytest.mark.parametrize('body,accepted',[
    ('This sample does not confirm whether the CPU load remains high right now.',True),
    ("It doesn't confirm whether performance will degrade right now.",True),
    ('It does not confirm whether performance will degrade right now. CPU usage is 85% right now.',False),
    ('It does not confirm whether CPU usage is high, but it is high right now.',False),
    ('It does not confirm whether CPU usage is high but it is high right now.',False),
    ('It does not confirm whether it is currently high right now.',False),
    ('It does not confirm whether RAM usage is 85% right now.',False),
    ('It does not confirm whether CPU usage was 99% right now.',False),
    ('CPU usage is not high right now.',False),
    ('CPU usage is 85% at present.',False),
])
def test_uncertainty_exception_does_not_waive_other_validations(tmp_path,body,accepted):
    session,model=make(tmp_path);setup_snapshot(session,cpu=85)
    model.return_value=json.dumps({'measurement':'85.0%','analysis':body})
    answer=session.reply('Is my CPU usage high?')
    assert answer.startswith('Earlier snapshot:')==accepted
    if not accepted:assert answer==ANALYSIS_REJECTED
    model.assert_called_once();assert session.tools.execute.call_count==1


def test_result_routing_does_not_reuse_calculation_for_memory_or_ambiguous_context(tmp_path):
    session,model=make(tmp_path)
    session.reply('Remember that Nova uses Unity.')
    execute=Mock(wraps=session.tools.execute);session.tools.execute=execute
    session.reply('/calc 12*7')
    assert '84' in session.reply('What was the result?')
    assert 'Unity' in session.reply('Which engine does Nova use?')
    assert 'Which earlier result' in session.reply('What was the result?')
    assert execute.call_count==1;model.assert_not_called()


def test_resume_preserves_saved_facts_but_not_trusted_tool_results(tmp_path):
    session,model=make(tmp_path)
    session.reply('Remember that Nova uses Unity.')
    setup_snapshot(session)
    session.resume(session.session_id)
    assert "isn't available" in session.reply('Is my RAM usage high?')
    assert "isn't available" in session.reply('What was my CPU usage?')
    assert 'Unity' in session.reply('Which engine does Nova use?')
    assert session.tools.execute.call_count==1;model.assert_not_called()


def test_tool_followup_cancels_pending_deletion_without_deleting_fact(tmp_path):
    session,model=make(tmp_path)
    session.reply('Remember that Nova uses Unity.')
    assert 'Reply' in session.reply("Forget Nova's engine.")
    assert session._pending_memory is not None
    assert "isn't available" in session.reply('What was my CPU usage?')
    assert session._pending_memory is None
    assert session._memory.get_fact('project','Nova','engine').value=='Unity'
    model.assert_not_called()
