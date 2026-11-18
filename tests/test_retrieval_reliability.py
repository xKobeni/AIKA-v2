import sqlite3
from contextlib import closing
from unittest.mock import Mock
from uuid import uuid4

import pytest

from src.intelligence.conversation import ConversationSession
from src.memory.store import MemoryStore
from src.storage.conversation_store import ConversationStore, StorageError


@pytest.fixture
def chat(tmp_path):
    memory = MemoryStore(tmp_path)
    conversations = ConversationStore(tmp_path)
    model = Mock(return_value="For Orion, I corrected frontend to a fabricated value.")
    session = ConversationSession("Rules", 10, model, conversations, memory)
    return session, memory, conversations, model


def test_successive_pronoun_corrections_commit_exactly_three_revisions_and_reopen(chat):
    session, memory, conversations, model = chat
    session.reply("Remember that my project Orion uses Next.js for its frontend.")
    commits = []

    def verify_commit(prompt, intent, result, error):
        assert error is None and result.committed and result.revised
        with closing(sqlite3.connect(memory.path)) as db:
            commits.append(db.execute("SELECT value, revision FROM memory_facts WHERE normalized_subject='orion'").fetchone())
        assert conversations.load_session(session.session_id, 10)[1][-1] == (prompt, result.answer)

    assert "updated frontend from Next.js to SvelteKit" in session.reply("Correct it to SvelteKit.", memory_trace=verify_commit)
    assert "updated frontend from SvelteKit to Astro" in session.reply("Then correct it to Astro.", memory_trace=verify_commit)
    assert commits == [("SvelteKit", 2), ("Astro", 3)]
    assert session.reply("What frontend does Orion use?") == "Orion uses Astro for its frontend."
    assert "Astro" in session.reply("tell me the current")
    assert "SvelteKit" in session.reply("What frontend did Orion use before?")
    assert "Astro" in session.reply("What is its current value?")
    assert "Next.js" in session.reply("What framework was Orion originally using?")
    assert "Astro" in session.reply("And the current one?")
    assert [revision.value for revision in memory.get_history("project", "Orion", "frontend")[1]] == ["Next.js", "SvelteKit", "Astro"]
    reopened = ConversationSession("Rules", 10, model, ConversationStore(memory.path.parent), MemoryStore(memory.path.parent))
    assert reopened.history() == []
    assert "Astro" in reopened.reply("What frontend does Orion use?")
    assert "SvelteKit" in reopened.reply("What was Orion's previous frontend?")
    assert "Next.js" in reopened.reply("What framework was Orion originally using?")
    model.assert_not_called()


def test_explicit_as_engine_save_and_assignment_notation_cannot_fake_update(chat):
    session, memory, _, model = chat
    assert "saved engine as Godot" in session.reply("Remember that my game Nova uses Godot as its engine.")
    assert memory.get_fact("project", "Nova", "engine").value == "Godot"
    assert "has not been saved" in session.reply("Nova.engine = Unreal Engine")
    assert "engine: Godot" in session.reply("What do you remember about Nova?")
    assert [revision.value for revision in memory.get_history("project", "Nova", "engine")[1]] == ["Godot"]
    model.assert_not_called()


def test_unsupported_correction_is_explicitly_rejected_and_regular_model_claim_is_guarded(chat):
    session, memory, _, model = chat
    session.reply("Remember that Orion uses Next.js.")
    assert "Which project, property, and value" in session.reply("Correct whatever you think needs it.")
    model.assert_not_called()
    assert session.reply("Let's discuss something else.") == "Got it. That stays in this conversation unless you ask me to save it."
    assert memory.get_fact("project", "Orion", "frontend").revision == 1
    model.assert_called_once()


def test_abbreviated_current_queries_require_unambiguous_fact(chat):
    session, memory, _, model = chat
    session.reply("Remember that Orion uses Next.js and PostgreSQL.")
    assert session.reply("tell me the current") == "Which property of Orion do you mean?"
    assert "Next.js" in session.reply("the frontend")
    session.reply("Remember that Nova uses Godot.")
    # The direct Orion lookup established that subject before Nova was added, so two candidates now remain.
    assert session.reply("And the current one?") == "Which project do you mean?"
    assert "Godot" in session.reply("Nova")
    assert memory.get_fact("project", "Orion", "database").value == "PostgreSQL"
    model.assert_not_called()


def test_current_recall_ignores_stale_assistant_and_reads_latest_store(chat):
    session, memory, _, model = chat
    session.reply("Remember that Orion uses Next.js.")
    assert "Next.js" in session.reply("What frontend does Orion use?")
    memory.set_fact("project", "Orion", "frontend", "Astro")
    assert "Astro" in session.reply("tell me the current")
    assert "Astro" in session.reply("What frontend does Orion use?")
    model.assert_not_called()


def test_pronoun_correction_detects_revision_change_since_last_fact_result(chat):
    session, memory, _, model = chat
    session.reply("Remember that Orion uses Next.js.")
    memory.set_fact("project", "Orion", "frontend", "React")
    assert "changed since the last response" in session.reply("Correct it to SvelteKit.")
    assert [revision.value for revision in memory.get_history("project", "Orion", "frontend")[1]] == ["Next.js", "React"]
    model.assert_not_called()


def test_pronoun_correction_after_property_clarification_and_failed_write(chat):
    session, memory, conversations, model = chat
    session.reply("Remember that Orion uses Next.js and PostgreSQL.")
    assert "Which property" in session.reply("I'm replacing it with SvelteKit.")
    session.reply("hmm the frontend")
    before = session.history()
    with closing(sqlite3.connect(memory.path)) as db:
        db.execute("""CREATE TRIGGER fail_correction BEFORE INSERT ON memory_revisions
                      WHEN NEW.value='Astro' BEGIN SELECT RAISE(ABORT, 'failure'); END""")
    with pytest.raises(StorageError):
        session.reply("Then correct it to Astro.")
    assert session.history() == before
    assert memory.get_fact("project", "Orion", "frontend").value == "SvelteKit"
    assert memory.get_fact("project", "Orion", "frontend").revision == 2
    assert memory.get_fact("project", "Orion", "database").revision == 1
    assert conversations.load_session(session.session_id, 10)[1][-1][0] == "hmm the frontend"
    model.assert_not_called()


def test_archive_scope_excludes_active_session_only_for_explicit_previous_conversations(chat):
    session, memory, conversations, model = chat
    old_id = uuid4().hex
    conversations.save_exchange(old_id, 0, "My project Atlas uses Vue.", "Old reply")
    session.reply("Remember that Atlas uses SvelteKit for its frontend.")
    older = session.reply("What did I mention about Atlas in my previous conversations?")
    assert old_id in older and "other session" in older
    assert session.session_id not in older and "SvelteKit" not in older
    current = session.reply("What did I mention about Atlas in this chat?")
    assert session.session_id in current and "current session" in current and "SvelteKit" in current
    assert old_id not in current and "Vue" not in current
    broader = session.reply("What did I previously mention about Atlas?")
    assert old_id in broader and session.session_id in broader
    assert "other session" in broader and "current session" in broader
    assert memory.get_fact("project", "Atlas", "frontend").value == "SvelteKit"
    session.new()
    assert "no matching user statements" in session.reply("What did I mention about Atlas in this chat?")
    assert "no matching user statements" in session.reply("What did I mention about Zephyr in my previous conversations?")
    model.assert_not_called()
