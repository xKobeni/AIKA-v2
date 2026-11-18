import sqlite3
from contextlib import closing
from unittest.mock import Mock

import pytest

import aika
from src.intelligence.conversation import ConversationSession
from src.memory.store import MemoryStore
from src.storage.conversation_store import ConversationStore, StorageError


@pytest.fixture
def memory_chat(tmp_path):
    memory = MemoryStore(tmp_path)
    conversations = ConversationStore(tmp_path)
    generate = Mock(return_value="Ordinary chat reply")
    return ConversationSession("Rules", 10, generate, conversations, memory), memory, conversations, generate


def test_explicit_save_recall_correction_and_previous_value_after_restart(memory_chat):
    session, memory, conversations, generate = memory_chat
    answer = session.reply("Remember that my project Orion uses Next.js for its frontend and PostgreSQL for its database.")
    assert "saved frontend as Next.js" in answer and "saved database as PostgreSQL" in answer
    assert session.reply("What frontend does Orion use?") == "Orion uses Next.js for its frontend."
    assert session.reply("And its database?") == "Orion uses PostgreSQL for its database."
    assert session.reply("What's Orion's database?") == "Orion uses PostgreSQL for its database."
    assert "updated frontend from Next.js to SvelteKit" in session.reply("I'm changing its frontend to SvelteKit.")
    assert session.reply("What did I use before?") == "Orion previously used Next.js for its frontend."
    assert session.reply("What did Orion use before SvelteKit?") == "Orion previously used Next.js for its frontend."
    assert "unchanged" in session.reply("Remember that Orion uses SvelteKit.")
    assert memory.get_fact("project", "Orion", "database").value == "PostgreSQL"
    assert [item.value for item in memory.get_history("project", "Orion", "frontend")[1]] == ["Next.js", "SvelteKit"]
    assert memory.get_fact("project", "Orion", "frontend").source.startswith("chat:" + session.session_id)

    restarted = ConversationSession("Rules", 10, generate, ConversationStore(conversations.path.parent), MemoryStore(memory.path.parent))
    assert restarted.history() == []
    assert restarted.reply("What frontend does Orion currently use?") == "Orion uses SvelteKit for its frontend."
    assert restarted.reply("What was its previous frontend?") == "Orion previously used Next.js for its frontend."
    assert restarted.session_id != session.session_id
    generate.assert_not_called()


def test_multiple_projects_ambiguity_and_reverse_recall(memory_chat):
    session, memory, _, generate = memory_chat
    session.reply("Remember that Solar Finch uses SvelteKit and PostgreSQL.")
    session.reply("Remember that my game Nova uses Godot.")
    assert session.reply("I'm changing its frontend to Next.js.") == "Which project do you mean?"
    assert session.reply("Which project uses PostgreSQL?") == "Solar Finch uses PostgreSQL."
    assert session.reply("Which one uses Godot?") == "Nova uses Godot."
    assert memory.get_fact("project", "Solar Finch", "frontend").value == "SvelteKit"
    assert "database: PostgreSQL" in session.reply("What do you remember about Solar Finch?")
    generate.assert_not_called()


def test_clear_correction_with_expected_value_and_repeat_are_safe(memory_chat):
    session, memory, _, generate = memory_chat
    assert "saved database" in session.reply("Please save that Orion's database is PostgreSQL.")
    assert "saved frontend" in session.reply("Remember that Orion uses Next.js.")
    assert "differs" in session.reply("Actually, Orion uses MySQL, not SQLite.")
    assert "updated database" in session.reply("Actually, Orion uses MySQL, not PostgreSQL.")
    assert "unchanged" in session.reply("Actually, Orion uses MySQL, not PostgreSQL.")
    assert "updated frontend" in session.reply("I'm switching Orion to SvelteKit.")
    assert memory.get_fact("project", "Orion", "database").revision == 2
    assert memory.get_fact("project", "Orion", "frontend").value == "SvelteKit"
    generate.assert_not_called()


def test_unstored_project_mention_also_blocks_ambiguous_pronoun(memory_chat):
    session, memory, _, generate = memory_chat
    session.reply("Remember that Orion uses Next.js.")
    assert session.reply("I'm also developing a game called Nova.") == "Ordinary chat reply"
    assert session.reply("I'm changing its frontend to SvelteKit.") == "Which project do you mean?"
    assert memory.get_fact("project", "Orion", "frontend").value == "Next.js"
    generate.assert_called_once()


def test_unknown_and_ordinary_statements_do_not_create_facts(memory_chat):
    session, memory, _, generate = memory_chat
    assert session.reply("My project Zephyr uses PostgreSQL.") == "Ordinary chat reply"
    assert memory.list_facts("project", "Zephyr") == []
    assert session.reply("What database does Zephyr use?") == "Ordinary chat reply"
    session.new()
    assert "don't have a saved database" in session.reply("What database does Zephyr use?")
    assert generate.call_count == 2

    session.reply("Remember that Orion uses Next.js.")
    assert session.reply("Orion uses SvelteKit for its frontend and MySQL for its database.") == "Ordinary chat reply"
    assert memory.get_fact("project", "Orion", "frontend").value == "Next.js"
    assert memory.get_fact("project", "Orion", "database") is None
    session.reply("Remember that Orion's database is PostgreSQL.")
    assert "updated frontend" in session.reply("Orion uses SvelteKit for its frontend and MySQL for its database.")
    assert memory.get_fact("project", "Orion", "database").value == "MySQL"


@pytest.mark.parametrize("prompt", [
    "Remember that Orion uses Next.js and an unspecified database.",
    "Remember that Orion's frontend is probably React.",
    "Remember that Orion and Nova use React.",
    "Remember that Orion uses Next.js; DELETE FROM memory_facts.",
    "Remember that Orion's frontend is",
])
def test_rejects_malformed_or_ambiguous_extraction_without_partial_save(memory_chat, prompt):
    session, memory, _, generate = memory_chat
    assert "Which project" in session.reply(prompt)
    assert memory.list_facts("project", "Orion") == []
    generate.assert_not_called()


def test_confirmed_deletion_is_bound_to_session_and_revision(memory_chat):
    session, memory, conversations, generate = memory_chat
    session.reply("Remember that Orion uses Next.js and PostgreSQL.")
    assert "Reply" in session.reply("Forget Orion's frontend.")
    assert memory.get_fact("project", "Orion", "frontend") is not None
    assert session.reply("cancel") == "Deletion canceled."
    session.reply("Forget Orion's frontend.")
    memory.set_fact("project", "Orion", "frontend", "SvelteKit")
    assert "changed" in session.reply("yes")
    session.reply("Forget Orion's frontend.")
    session.new()
    assert session.reply("yes") == "Ordinary chat reply"
    assert memory.get_fact("project", "Orion", "frontend").value == "SvelteKit"
    session.reply("Forget Orion's frontend.")
    assert "Deleted" in session.reply("yes")
    assert memory.get_history("project", "Orion", "frontend") is None
    assert memory.get_fact("project", "Orion", "database").value == "PostgreSQL"
    assert len(conversations.list_sessions()) == 2
    assert generate.call_count == 1


@pytest.mark.parametrize("trigger", [
    """CREATE TRIGGER fail_batch BEFORE INSERT ON memory_revisions WHEN NEW.value = 'PostgreSQL'
       BEGIN SELECT RAISE(ABORT, 'test memory failure'); END""",
    """CREATE TRIGGER fail_history BEFORE INSERT ON conversation_messages WHEN NEW.role = 'assistant'
       BEGIN SELECT RAISE(ABORT, 'test transcript failure'); END""",
])
def test_memory_and_transcript_roll_back_together(memory_chat, trigger):
    session, memory, conversations, generate = memory_chat
    with closing(sqlite3.connect(memory.path)) as db:
        db.execute(trigger)
    with pytest.raises(StorageError, match="operation failed"):
        session.reply("Remember that Orion uses Next.js and PostgreSQL.")
    assert session.history() == [] and conversations.list_sessions() == []
    assert memory.list_facts("project", "Orion") == []
    generate.assert_not_called()


def test_cli_failure_has_no_success_message_and_private_diagnostics(tmp_path, mock_ollama, monkeypatch, capsys):
    mock_ollama()
    monkeypatch.setenv("AIKA_CONTEXT_DEBUG", "roles")
    original = MemoryStore.set_fact

    def fail_second(self, entity_type, subject, key, value, **kwargs):
        if key == "database":
            raise StorageError("Test write failed.")
        return original(self, entity_type, subject, key, value, **kwargs)

    monkeypatch.setattr(MemoryStore, "set_fact", fail_second)
    inputs = iter(["Remember that Private Demo uses Next.js and PostgreSQL.", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    assert aika.main(["chat"]) == 0
    captured = capsys.readouterr()
    assert "saved" not in captured.out
    assert "Storage error" in captured.err and "committed=no" in captured.err and "error=storage" in captured.err
    assert "Private Demo" not in captured.err and "PostgreSQL" not in captured.err
    assert MemoryStore(tmp_path).list_facts("project", "Private Demo") == []


def test_flexible_save_correction_and_recall_variants(memory_chat):
    session, memory, _, generate = memory_chat
    assert "saved frontend as Astro" in session.reply("Keep in mind that my project Eclipse uses Astro for its frontend.")
    assert "saved database as PostgreSQL" in session.reply("Make a note that Eclipse's database is PostgreSQL.")
    assert "updated frontend from Astro to SvelteKit" in session.reply("I've replaced Eclipse's frontend with SvelteKit.")
    assert "updated frontend from SvelteKit to React" in session.reply("I switched Eclipse from SvelteKit to React.")
    assert "originally used Astro" in session.reply("What framework was Eclipse originally using?")
    assert "originally used Astro" in session.reply("What framework did I originally use for Eclipse?")
    assert "previously used SvelteKit" in session.reply("The previous one?")
    assert "React" in session.reply("The framework?")
    assert "React" in session.reply("What's the framework for Eclipse?")
    assert "PostgreSQL" in session.reply("What does Eclipse use for its database?")
    assert session.reply("Which of my projects uses PostgreSQL?") == "Eclipse uses PostgreSQL."
    assert "frontend: React" in session.reply("Tell me everything you've saved about Eclipse.")
    assert "updated database from PostgreSQL to MySQL" in session.reply("By the way, Eclipse uses MySQL now.")
    assert "differs" in session.reply("I switched Eclipse from Astro to Vue.")
    assert [item.value for item in memory.get_history("project", "Eclipse", "frontend")[1]] == ["Astro", "SvelteKit", "React"]
    generate.assert_not_called()


def test_replacing_it_uses_recent_property_and_clarifies_conflict(memory_chat):
    session, memory, _, generate = memory_chat
    session.reply("Remember that Orion uses Next.js.")
    assert "updated frontend" in session.reply("I'm replacing it with SvelteKit.")
    session.reply("Remember that Orion uses PostgreSQL.")
    assert "Which property" in session.reply("I'm replacing it with React.")
    assert memory.get_fact("project", "Orion", "frontend").value == "SvelteKit"
    assert memory.get_fact("project", "Orion", "database").value == "PostgreSQL"
    assert "updated frontend" in session.reply("The framework.")
    assert memory.get_fact("project", "Orion", "frontend").value == "React"
    generate.assert_not_called()


def test_project_clarification_reuses_only_the_requested_operation(memory_chat):
    session, memory, _, generate = memory_chat
    session.reply("Keep in mind that Eclipse uses Astro.")
    session.reply("Keep in mind that Nebula uses Vue.")
    assert session.reply("Change its frontend to React.") == "Which project do you mean?"
    assert memory.get_fact("project", "Eclipse", "frontend").value == "Astro"
    assert memory.get_fact("project", "Nebula", "frontend").value == "Vue"
    assert "updated frontend" in session.reply("I mean Eclipse.")
    assert memory.get_fact("project", "Eclipse", "frontend").value == "React"
    assert memory.get_fact("project", "Nebula", "frontend").value == "Vue"
    generate.assert_not_called()


def test_unsaved_transcript_fact_requires_confirmation_and_starts_at_revision_one(memory_chat):
    session, memory, _, generate = memory_chat
    assert session.reply("My project Nebula uses Vue.") == "Ordinary chat reply"
    answer = session.reply("I'm changing Nebula's frontend to SvelteKit.")
    assert "You mentioned Vue" in answer and "Save SvelteKit" in answer
    assert memory.list_facts("project", "Nebula") == []
    assert session.reply("cancel") == "Save canceled."
    assert memory.list_facts("project", "Nebula") == []
    assert "Save SvelteKit" in session.reply("I've replaced Nebula's frontend with SvelteKit.")
    assert "saved frontend as SvelteKit" in session.reply("yes")
    active, revisions = memory.get_history("project", "Nebula", "frontend")
    assert active.value == "SvelteKit" and active.revision == 1
    assert [item.value for item in revisions] == ["SvelteKit"]
    assert "don't have an earlier saved value" in session.reply("What was its previous frontend?")
    generate.assert_called_once()


def test_pending_save_is_session_bound_and_refuses_to_overwrite_a_new_fact(memory_chat):
    session, memory, conversations, generate = memory_chat
    session.reply("My project Nebula uses Vue.")
    assert "mentioned Vue" in session.reply("Change Nebula's frontend to SvelteKit.")
    original_session_id = session.session_id
    restarted = ConversationSession("Rules", 10, generate, conversations, memory)
    restarted.resume(original_session_id)
    assert restarted.reply("yes") == "Ordinary chat reply"
    assert memory.list_facts("project", "Nebula") == []
    assert "Save SvelteKit" in restarted.reply("Change Nebula's frontend to SvelteKit.")
    memory.set_fact("project", "Nebula", "frontend", "React")
    assert "now has a saved frontend" in restarted.reply("yes")
    assert memory.get_fact("project", "Nebula", "frontend").value == "React"
    session.new()
    assert session.reply("yes") == "Ordinary chat reply"


def test_without_active_transcript_offer_does_not_claim_prior_information(memory_chat):
    session, memory, _, generate = memory_chat
    session.reply("My project Nebula uses Vue.")
    session.new()
    answer = session.reply("Change Nebula's frontend to SvelteKit.")
    assert "Save SvelteKit" in answer and "Vue" not in answer and "mentioned" not in answer
    assert memory.list_facts("project", "Nebula") == []
    assert "don't have a saved database" in session.reply("What database does Unknown Project use?")
    assert session.reply("yes") == "Ordinary chat reply"
    assert memory.list_facts("project", "Nebula") == []


def test_confirmed_save_failure_leaves_store_and_transcript_unchanged(memory_chat):
    session, memory, _, generate = memory_chat
    assert "Save SvelteKit" in session.reply("Change Nebula's frontend to SvelteKit.")
    before = session.history()
    with closing(sqlite3.connect(memory.path)) as db:
        db.execute("""CREATE TRIGGER fail_save BEFORE INSERT ON memory_revisions
                      BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    with pytest.raises(StorageError, match="operation failed"):
        session.reply("yes")
    assert memory.list_facts("project", "Nebula") == []
    assert session.history() == before
    generate.assert_not_called()


def test_ordinary_statement_cannot_repeat_unverified_saved_claim(memory_chat):
    session, memory, _, generate = memory_chat
    generate.return_value = "For Nebula, I saved frontend as Vue."
    answer = session.reply("My project Nebula uses Vue.")
    assert answer == "Got it. That stays in this conversation unless you ask me to save it."
    assert session.history()[-1]["content"] == answer
    assert memory.list_facts("project", "Nebula") == []
    generate.assert_called_once()


@pytest.mark.parametrize("clarification", ["frontend", "the frontend", "hmm the frontend", "I mean its frontend"])
def test_property_clarification_commits_before_reporting_success(memory_chat, clarification):
    session, memory, conversations, generate = memory_chat
    session.reply("Remember that my project Orion uses Next.js for its frontend and PostgreSQL for its database.")
    assert session.reply("I'm replacing it with SvelteKit.") == "Which property of Orion should I update?"
    assert memory.get_fact("project", "Orion", "frontend").revision == 1
    observed = []

    def check_commit(prompt, intent, result, error):
        assert result.committed and error is None
        assert memory.get_fact("project", "Orion", "frontend").value == "SvelteKit"
        assert conversations.load_session(session.session_id, 10)[1][-1] == (prompt, result.answer)
        observed.append(prompt)

    reply = session.reply(clarification, memory_trace=check_commit)
    assert "updated frontend from Next.js to SvelteKit" in reply
    assert observed == [clarification]
    assert session.history()[-1]["content"] == reply
    assert session.reply("What did I use before?") == "Orion previously used Next.js for its frontend."
    assert session.reply("hmm the frontend") == "Ordinary chat reply"
    assert [item.value for item in memory.get_history("project", "Orion", "frontend")[1]] == ["Next.js", "SvelteKit"]
    assert memory.get_fact("project", "Orion", "database").value == "PostgreSQL"
    generate.assert_called_once()


def test_clarified_correction_refuses_changed_revision_even_after_value_cycles(memory_chat):
    session, memory, _, generate = memory_chat
    session.reply("Remember that Orion uses Next.js and PostgreSQL.")
    session.reply("I'm replacing it with SvelteKit.")
    memory.set_fact("project", "Orion", "frontend", "Astro")
    memory.set_fact("project", "Orion", "frontend", "Next.js")
    reply = session.reply("hmm the frontend")
    assert "is now Next.js" in reply and "Review it" in reply
    assert [item.value for item in memory.get_history("project", "Orion", "frontend")[1]] == ["Next.js", "Astro", "Next.js"]
    generate.assert_not_called()


def test_clarification_transaction_failure_preserves_fact_and_transcript(memory_chat):
    session, memory, conversations, generate = memory_chat
    session.reply("Remember that Orion uses Next.js and PostgreSQL.")
    session.reply("I'm replacing it with SvelteKit.")
    before = session.history()
    recorded = conversations.load_session(session.session_id, 10)
    with closing(sqlite3.connect(memory.path)) as db:
        db.execute("""CREATE TRIGGER fail_clarification BEFORE INSERT ON conversation_messages
                      WHEN NEW.role = 'assistant' BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    observed = []
    with pytest.raises(StorageError, match="operation failed"):
        session.reply("hmm the frontend", memory_trace=lambda prompt, intent, result, error: observed.append((result, error)))
    assert observed == [(None, "storage")]
    assert [item.value for item in memory.get_history("project", "Orion", "frontend")[1]] == ["Next.js"]
    assert session.history() == before and conversations.load_session(session.session_id, 10) == recorded
    generate.assert_not_called()


def test_pending_property_clarification_does_not_survive_session_switch(memory_chat):
    session, memory, _, generate = memory_chat
    session.reply("Remember that Orion uses Next.js and PostgreSQL.")
    session.reply("I'm replacing it with SvelteKit.")
    original = session.session_id
    session.new()
    assert session.reply("hmm the frontend") == "Ordinary chat reply"
    session.resume(original)
    assert session.reply("hmm the frontend") == "Ordinary chat reply"
    assert memory.get_fact("project", "Orion", "frontend").revision == 1
    assert generate.call_count == 2


def test_cli_reports_clarification_storage_failure_without_update(tmp_path, mock_ollama, monkeypatch, capsys):
    mock_ollama()
    original = ConversationStore.save_exchange

    def fail_clarified_exchange(self, session_id, sequence, user, assistant, **kwargs):
        if user == "hmm the frontend":
            raise StorageError("Test transcript failure.")
        return original(self, session_id, sequence, user, assistant, **kwargs)

    monkeypatch.setattr(ConversationStore, "save_exchange", fail_clarified_exchange)
    inputs = iter(["Remember that Orion uses Next.js and PostgreSQL.", "I'm replacing it with SvelteKit.",
                   "hmm the frontend", "What frontend does Orion use?", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    assert aika.main(["chat"]) == 0
    output = capsys.readouterr()
    assert "Storage error: Test transcript failure." in output.err
    assert "updated frontend" not in output.out
    assert "Orion uses Next.js for its frontend." in output.out
    assert len(MemoryStore(tmp_path).get_history("project", "Orion", "frontend")[1]) == 1


def test_history_uses_ordered_revisions_after_restart_and_tracks_relative_followups(memory_chat):
    _, memory, conversations, generate = memory_chat
    generate.return_value = "Orion used AngularJS before."
    for value in ("Next.js", "SvelteKit", "Next.js"):
        memory.set_fact("project", "Orion", "frontend", value)
    fresh = ConversationSession("Rules", 10, generate, conversations, MemoryStore(memory.path.parent))
    assert fresh.history() == []
    assert fresh.reply("What frontend did Orion use before?") == "Orion previously used SvelteKit for its frontend."
    assert fresh.reply("And before that?") == "Orion previously used Next.js for its frontend."
    assert "don't have an earlier saved value" in fresh.reply("And before that?")
    assert fresh.reply("What framework was Orion originally using?") == "Orion originally used Next.js for its frontend."
    assert fresh.reply("What frontend does Orion currently use?") == "Orion uses Next.js for its frontend."
    assert fresh.reply("What was Orion's previous frontend?") == "Orion previously used SvelteKit for its frontend."
    fresh.new()
    assert "Which project and property" in fresh.reply("And before that?")
    generate.assert_not_called()


def test_previous_value_requires_saved_history_or_clear_scope(memory_chat):
    session, memory, _, generate = memory_chat
    memory.set_fact("project", "Nebula", "frontend", "React")
    assert session.reply("What was Nebula using before?") == "I don't have an earlier saved value for Nebula's frontend."
    session.new()
    assert "don't have a saved frontend" in session.reply("What frontend did Unknown use before?")
    session.new()
    memory.set_fact("project", "Nebula", "database", "PostgreSQL")
    assert "Which property of Nebula" in session.reply("What was Nebula using before?")
    assert "Which project, property" in session.reply("What was the frontend for my previous project?")
    generate.assert_not_called()


def test_relative_history_does_not_follow_a_recreated_fact(memory_chat):
    session, memory, _, generate = memory_chat
    memory.set_fact("project", "Orion", "frontend", "Next.js")
    memory.set_fact("project", "Orion", "frontend", "SvelteKit")
    assert "SvelteKit" in session.reply("What frontend does Orion use?")
    memory.delete_fact("project", "Orion", "frontend", confirm=True)
    memory.set_fact("project", "Orion", "frontend", "Vue")
    memory.set_fact("project", "Orion", "frontend", "Astro")
    assert "no longer available" in session.reply("And before that?")
    generate.assert_not_called()
