import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, replace

from src.memory.intent import KEYS, TECHNOLOGY_KEYS, Intent, mentioned_projects, parse_intent
from src.memory.store import Fact, MemoryStore
from src.memory.retrieval import Retrieval, fact_evidence, last_session_statement, search_archive


@dataclass(frozen=True)
class PendingSave:
    intent: Intent


@dataclass(frozen=True)
class PendingClarification:
    intent: Intent
    projects: tuple[str, ...] = ()
    properties: tuple[str, ...] = ()
    facts: tuple[Fact, ...] = ()


PendingMemory = Fact | PendingSave | PendingClarification
SAVE_CLAIM = re.compile(
    r"\b(?:i(?:'ve| have| will|'ll)? (?:just )?(?:save[ds]?|store[ds]?|record(?:ed)?|remembered|updat(?:ed|e)|correct(?:ed)?|delet(?:ed|e))|"
    r"(?:fact|memory) (?:has been |was )?saved|saved (?:in|to) (?:my |persistent )?memory|"
    r"(?:corrected|updated|saved|deleted) (?:the )?(?:frontend|database|engine|fact|memory))\b",
    re.IGNORECASE,
)


def ordinary_statement_reply(answer: str) -> str:
    if SAVE_CLAIM.search(answer.replace("’", "'")):
        return "Got it. That stays in this conversation unless you ask me to save it."
    return answer


@dataclass(frozen=True)
class HistoryAnchor:
    fact_id: str
    subject: str
    key: str
    revision: int


@dataclass(frozen=True)
class MemoryReply:
    answer: str
    subject: str | None = None
    keys: tuple[str, ...] = ()
    retrieved: bool = False
    committed: bool = False
    revised: bool = False
    validation_error: bool = False
    pending: PendingMemory | None = None
    history_anchor: HistoryAnchor | None = None
    evidence: tuple[Retrieval, ...] = ()


def resolve_pending(pending: PendingMemory | None, prompt: str) -> tuple[Intent | None, str | None]:
    command = " ".join(prompt.casefold().rstrip(".?!").split())
    if isinstance(pending, Fact):
        intent = Intent("forget", pending.subject, pending.key)
    elif pending is not None:
        intent = pending.intent
    else:
        return None, None

    if command in {"no", "cancel"}:
        return intent, "cancel"
    if command in {"yes", "confirm"}:
        if isinstance(pending, Fact):
            return intent, "confirm"
        if isinstance(pending, PendingSave):
            return intent, "save"
    if isinstance(pending, PendingClarification):
        choice = re.sub(r"^(?:hmm*,?\s+)?(?:i mean\s+)?", "", command)
        for project in pending.projects:
            if project.casefold() == choice:
                return replace(intent, subject=project), "clarified"
        choice = re.sub(r"^(?:the|its)\s+", "", choice)
        key = KEYS.get(choice, choice)
        for property_name in pending.properties:
            if property_name.casefold() == key:
                return replace(intent, key=property_name), "clarified"
    return None, None


def _context(prompts: Iterable[str]) -> tuple[list[Intent], list[str]]:
    recent = []
    subjects: dict[str, str] = {}
    for prompt in prompts:
        intent = parse_intent(prompt)
        if intent is None:
            for name in mentioned_projects(prompt):
                subjects[name.casefold()] = name
            continue
        recent.append(intent)
        if intent.subject:
            if intent.action in {"recall", "saved_recall", "history", "correct", "list", "forget"}:
                subjects.clear()
            subjects[intent.subject.casefold()] = intent.subject
    return recent, list(subjects.values())


def _recent_key(recent: list[Intent], subject: str) -> str | None:
    for intent in reversed(recent):
        if intent.subject and intent.subject.casefold() != subject.casefold():
            continue
        if intent.key:
            return intent.key
        if intent.facts:
            return intent.facts[0][0] if len(intent.facts) == 1 else None
    return None


def _correction_key(intent: Intent, recent: list[Intent], subject: str, facts: list[Fact]) -> str | None:
    if intent.key is not None:
        return intent.key
    if intent.expected is not None:
        matches = [fact.key for fact in facts if fact.value.casefold() == intent.expected.casefold()]
        return matches[0] if len(matches) == 1 else None

    key = _recent_key(recent, subject)
    inferred = TECHNOLOGY_KEYS.get(intent.value.casefold()) if intent.value else None
    if key:
        return key if inferred is None or inferred == key else None
    if len(facts) == 1 and (inferred is None or inferred == facts[0].key):
        return facts[0].key
    return None


def _offer_save(subject: str, key: str, value: str, recent: list[Intent]) -> MemoryReply:
    earlier = next((
        dict(item.facts)[key] for item in reversed(recent)
        if item.action == "statement" and item.subject and item.subject.casefold() == subject.casefold()
        and key in dict(item.facts)
    ), None)
    context = f"You mentioned {earlier} for {subject}'s {key} in this chat. " if earlier else ""
    proposed = Intent("save", subject, facts=((key, value),))
    return MemoryReply(
        f"{context}I don't have a saved {key} for {subject}. Save {value} as its {key}? Reply ‘yes’ or ‘cancel’.",
        subject, (key,), retrieved=True, pending=PendingSave(proposed),
    )


def respond(
    intent: Intent, prompts: Iterable[str], store: MemoryStore, db: sqlite3.Connection, source: str,
    *, confirmation: str | None = None, pending: PendingMemory | None = None,
    history_anchor: HistoryAnchor | None = None,
    session_id: str | None = None, sequence: int = 0, has_session_context: bool = False,
) -> MemoryReply | None:
    if confirmation == "cancel":
        operation = "Deletion" if isinstance(pending, Fact) else "Save" if isinstance(pending, PendingSave) else "Request"
        return MemoryReply(f"{operation} canceled.")
    if intent.action == "clarify":
        return MemoryReply("Which project, property, and value do you mean?", validation_error=True)
    if intent.action == "unsupported_assignment":
        return MemoryReply("That assignment has not been saved. Say ‘remember’ with the project name, property, and value.",
                           validation_error=True)
    if intent.action == "archive":
        evidence = search_archive(db, intent.terms, session_id=session_id, scope=intent.archive_scope)
        if not evidence:
            return MemoryReply("I found no matching user statements in saved conversations.", retrieved=True)
        lines = ["Historical user statements from saved conversations"]
        for item in evidence:
            origin = "current session" if item.session_id == session_id else "other session"
            lines.append(f"[session {item.session_id}, {origin}, message {item.message_id}, {item.created_at}, {item.role}] {item.value!r}")
        return MemoryReply("\n".join(lines), retrieved=True, evidence=evidence)
    if intent.action == "session_recall":
        evidence = last_session_statement(db, session_id, sequence) if session_id and has_session_context else None
        if evidence is None:
            return MemoryReply("There is no earlier user message in the active context.", retrieved=True)
        return MemoryReply(f"You just said {evidence.value!r}.", retrieved=True, evidence=(evidence,))
    if intent.action == "find":
        assert intent.value is not None
        facts = store.find_value("project", intent.value, connection=db)
        subjects = list(dict.fromkeys(fact.subject for fact in facts))
        answer = f"{', '.join(subjects)} {'use' if len(subjects) > 1 else 'uses'} {intent.value}." if subjects else (
            f"I don't have a saved project that uses {intent.value}."
        )
        return MemoryReply(answer, retrieved=True, evidence=tuple(fact_evidence(fact) for fact in facts))

    recent, subjects = _context(prompts)
    subject = intent.subject or (subjects[0] if len(subjects) == 1 else None)
    if intent.relative:
        if history_anchor is None:
            return MemoryReply("Which project and property should I look up?", validation_error=True)
        subject = history_anchor.subject
    elif intent.action == "history" and intent.subject is None and history_anchor is not None:
        subject = history_anchor.subject
    if subject is None:
        if intent.action == "statement":
            return None
        candidates = tuple(
            fact for project in subjects for fact in store.list_facts("project", project, connection=db)
        ) if intent.action == "correct" else ()
        return MemoryReply("Which project do you mean?", validation_error=True,
                           pending=PendingClarification(intent, projects=tuple(subjects), facts=candidates) if subjects else None)

    action, key = intent.action, intent.key
    scope = ("project", subject)
    if action == "saved_recall" and key is None:
        if history_anchor and history_anchor.subject.casefold() == subject.casefold():
            key = history_anchor.key
        else:
            key = _recent_key(recent, subject)
        if key is None:
            facts = store.list_facts(*scope, connection=db)
            if len(facts) == 1:
                key = facts[0].key
            else:
                return MemoryReply(f"Which property of {subject} do you mean?", subject, retrieved=True, validation_error=True,
                                   pending=PendingClarification(replace(intent, subject=subject),
                                                                properties=tuple(fact.key for fact in facts)))
    if action == "correct" and not intent.facts:
        assert intent.value is not None
        if key is None and intent.subject is None and history_anchor and history_anchor.subject.casefold() == subject.casefold():
            inferred = TECHNOLOGY_KEYS.get(intent.value.casefold())
            if inferred is None or inferred == history_anchor.key:
                key = history_anchor.key
        facts = store.list_facts(*scope, connection=db) if key is None else []
        key = key or _correction_key(intent, recent, subject, facts)
        if key is None:
            candidates = pending.facts if confirmation == "clarified" and isinstance(pending, PendingClarification) else tuple(facts)
            return MemoryReply(f"Which property of {subject} should I update?", subject, retrieved=True, validation_error=True,
                               pending=PendingClarification(replace(intent, subject=subject),
                                                            properties=tuple(fact.key for fact in facts), facts=candidates))
        intent = replace(intent, facts=((key, intent.value),))
    if action in {"save", "statement", "correct"}:
        keys = tuple(key for key, _ in intent.facts)
        existing = [store.get_fact(*scope, key, connection=db) for key in keys]
        if action == "correct" and intent.subject is None and history_anchor is not None:
            for key, current in zip(keys, existing, strict=True):
                if key == history_anchor.key and subject.casefold() == history_anchor.subject.casefold() and (
                    current is None or (current.id, current.revision) != (history_anchor.fact_id, history_anchor.revision)
                ):
                    return MemoryReply("That saved fact changed since the last response. Review its current value before correcting it.",
                                       subject, keys, retrieved=True, validation_error=True)
        if confirmation == "clarified" and action == "correct" and isinstance(pending, PendingClarification):
            expected_facts = {fact.key.casefold(): fact for fact in pending.facts if fact.subject.casefold() == subject.casefold()}
            for key, current in zip(keys, existing, strict=True):
                if current != expected_facts.get(key.casefold()):
                    state = f"is now {current.value}" if current is not None else "is no longer saved"
                    return MemoryReply(f"The saved revision changed while I was waiting. {subject}'s {key} {state}. "
                                       "Review it before requesting another correction.",
                                       subject, keys, retrieved=True, validation_error=True)
        if confirmation == "save" and any(fact is not None for fact in existing):
            return MemoryReply(f"{subject} now has a saved {keys[0]}. Ask for a correction to change it.",
                               subject, keys, retrieved=True, validation_error=True)
        if action != "save" and any(fact is None for fact in existing):
            if action == "statement":
                return None
            if len(intent.facts) == 1:
                return _offer_save(subject, *intent.facts[0], recent)
            return MemoryReply("Some of those properties have no saved value. Say ‘remember’ to save the full set.",
                               subject, keys, retrieved=True)
        if intent.expected is not None and existing[0].value.casefold() not in {
            intent.expected.casefold(), intent.facts[0][1].casefold(),
        }:
            return MemoryReply("The saved value differs from the correction you described. Which value should I update?",
                               subject, keys, retrieved=True, validation_error=True)

        fragments = []
        saved = revised = False
        fact = None
        for (key, value), previous in zip(intent.facts, existing, strict=True):
            if previous and previous.value.casefold() == value.casefold():
                fact = previous
                fragments.append(f"left {key} unchanged at {previous.value}")
                continue
            fact, prior_value = store.set_fact(*scope, key, value, source=source, connection=db)
            if prior_value is None:
                saved = True
                fragments.append(f"saved {key} as {fact.value}")
            else:
                revised = True
                fragments.append(f"updated {key} from {prior_value} to {fact.value}")
        anchor = HistoryAnchor(fact.id, fact.subject, fact.key, fact.revision) if len(keys) == 1 and fact else None
        return MemoryReply(f"For {subject}, I {' and '.join(fragments)}.", subject, keys,
                           retrieved=True, committed=saved or revised, revised=revised, history_anchor=anchor)

    if action == "list":
        facts = store.list_facts(*scope, connection=db)
        answer = f"Saved facts for {subject}\n" + "\n".join(f"{fact.key}: {fact.value}" for fact in facts) if facts else (
            f"I don't have saved facts about {subject}."
        )
        return MemoryReply(answer, subject, tuple(fact.key for fact in facts), retrieved=True,
                           evidence=tuple(fact_evidence(fact) for fact in facts))

    if action == "history":
        return _history(store, db, subject, intent, recent, history_anchor)

    assert key is not None
    fact = store.get_fact(*scope, key, connection=db)
    if action == "recall" and intent.facts:
        value = intent.facts[0][1]
        answer = f"You just said {subject} uses {value} for its {key}. "
        answer += (f"Saved memory still has {fact.value}; it hasn't been changed." if fact and fact.value.casefold()!=value.casefold()
                   else "That matches saved memory." if fact else f"I don't have a saved {key} for {subject}.")
        current = Retrieval("current_session",value,subject=subject,key=key,source=source,session_id=session_id,role="user")
        return MemoryReply(answer,subject,(key,),retrieved=True,
                           evidence=(current, fact_evidence(fact)) if fact else (current,),
                           history_anchor=HistoryAnchor(fact.id,fact.subject,fact.key,fact.revision) if fact else None)
    if fact is None:
        forgotten = any(
            item.action == "forget" and item.key == key
            and (item.subject is None or item.subject.casefold() == subject.casefold()) for item in recent
        )
        if action == "recall" and not forgotten and any(
            item.action == "statement" and item.subject and item.subject.casefold() == subject.casefold()
            and key in dict(item.facts) for item in recent
        ):
            return None  # The ordinary chat path can answer from the supplied transcript.
        return MemoryReply(f"I don't have a saved {key} for {subject}.", subject, (key,), retrieved=True)
    if action == "forget":
        if confirmation == "confirm":
            if not isinstance(pending, Fact) or (pending.id, pending.revision) != (fact.id, fact.revision):
                return MemoryReply("That fact changed. Ask me to forget it again to confirm the current revision.",
                                   subject, (key,), retrieved=True, validation_error=True)
            store.delete_fact(*scope, key, confirm=True, connection=db)
            return MemoryReply(f"Deleted {fact.subject}'s {fact.key} and its revisions from the active memory database. "
                               "Chat transcripts and backups may still contain it.", fact.subject, (fact.key,),
                               retrieved=True, committed=True)
        return MemoryReply(f"Delete {fact.subject}'s {fact.key} and its revisions? Reply ‘yes’ to confirm or ‘cancel’.",
                           fact.subject, (fact.key,), retrieved=True, pending=fact)
    return MemoryReply(f"{fact.subject} uses {fact.value} for its {fact.key}.", fact.subject, (fact.key,), retrieved=True,
                       history_anchor=HistoryAnchor(fact.id, fact.subject, fact.key, fact.revision), evidence=(fact_evidence(fact),))


def _history(
    store: MemoryStore, db: sqlite3.Connection, subject: str, intent: Intent, recent: list[Intent],
    anchor: HistoryAnchor | None,
) -> MemoryReply:
    scope = ("project", subject)
    key = intent.key
    if key is None and intent.value is None and not intent.broad:
        scoped_recent = [item for item in recent if item.subject is not None] if intent.subject else recent
        key = anchor.key if anchor and anchor.subject.casefold() == subject.casefold() else _recent_key(scoped_recent, subject)
    keys = [key] if key else [fact.key for fact in store.list_facts(*scope, connection=db)]
    if intent.value is None and len(keys) > 1:
        return MemoryReply(f"Which property of {subject} do you mean?", subject, retrieved=True, validation_error=True,
                           pending=PendingClarification(replace(intent, subject=subject), properties=tuple(keys)))

    matches = []
    found_history = False
    for key in keys:
        history = store.get_history(*scope, key, connection=db)
        if history is None:
            continue
        fact, revisions = history
        position = len(revisions) - 1
        if intent.relative:
            if anchor is None or fact.id != anchor.fact_id:
                continue
            position = next((i for i, revision in enumerate(revisions) if revision.revision == anchor.revision), -1)
        elif intent.value is not None:
            position = next((i for i in range(position, -1, -1)
                             if revisions[i].value.casefold() == intent.value.casefold()), -1)
        found_history = True
        if intent.original:
            matches.append((fact, revisions[0]))
        elif position >= 0:
            previous = revisions[position - 1] if position else None
            matches.append((fact, previous))

    if len(matches) > 1:
        return MemoryReply(f"Which property of {subject} do you mean?", subject, retrieved=True, validation_error=True,
                           pending=PendingClarification(replace(intent, subject=subject),
                                                        properties=tuple(fact.key for fact, _ in matches)))
    if matches and matches[0][1] is not None:
        fact, previous = matches[0]
        when = "originally" if intent.original else "previously"
        return MemoryReply(f"{fact.subject} {when} used {previous.value} for its {fact.key}.", fact.subject, (fact.key,),
                           retrieved=True, history_anchor=HistoryAnchor(fact.id, fact.subject, fact.key, previous.revision),
                           evidence=(fact_evidence(fact, previous),))
    if not found_history:
        if intent.relative:
            return MemoryReply("That saved revision is no longer available. Which property should I look up?",
                               subject, tuple(keys), retrieved=True, validation_error=True)
        missing = f"a saved {keys[0]} for {subject}" if len(keys) == 1 else f"saved facts about {subject}"
        return MemoryReply(f"I don't have {missing}.", subject, tuple(keys), retrieved=True)
    target = f"{subject}'s {keys[0]}" if len(keys) == 1 else subject
    return MemoryReply(f"I don't have an earlier saved value for {target}.", subject, tuple(keys), retrieved=True)
