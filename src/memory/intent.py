import re
from dataclasses import dataclass
from typing import Literal


Action = Literal["save", "statement", "correct", "recall", "saved_recall", "history", "list", "find", "forget", "clarify", "archive", "session_recall", "unsupported_assignment"]
KEYS = {
    "frontend": "frontend", "front end": "frontend", "front-end": "frontend", "frontend framework": "frontend",
    "framework": "frontend", "database": "database", "db": "database", "engine": "engine", "game engine": "engine",
    "project type": "project_type", "project_type": "project_type", "backend": "backend", "language": "language",
    "front-end framework": "frontend", "database system": "database", "database engine": "database",
}
KEY_PATTERN = "(?:" + "|".join(map(re.escape, sorted(KEYS, key=len, reverse=True))) + ")"
TECHNOLOGY_KEYS = {
    value.casefold(): key for key, values in {
        "frontend": ("Next.js", "SvelteKit", "React", "Vue", "Angular", "Astro", "Nuxt", "Remix"),
        "database": ("PostgreSQL", "Postgres", "MySQL", "SQLite", "MariaDB", "MongoDB", "Redis", "SQL Server"),
        "engine": ("Godot", "Unity", "Unreal Engine", "GameMaker"),
    }.items() for value in values
}
REFERENCES = {"it", "its", "that project", "the project", "my project", "this project", "my game", "that game"}


@dataclass(frozen=True)
class Intent:
    action: Action
    subject: str | None = None
    key: str | None = None
    facts: tuple[tuple[str, str], ...] = ()
    value: str | None = None
    expected: str | None = None
    original: bool = False
    relative: bool = False
    terms: tuple[str, ...] = ()
    broad: bool = False
    archive_scope: Literal["all", "other", "current"] = "all"


def _match(pattern: str, text: str) -> re.Match | None:
    return re.fullmatch(pattern, text, re.IGNORECASE)


def _subject(raw: str) -> str | None:
    raw = " ".join(raw.split())
    if raw.casefold() in REFERENCES:
        return None
    name = re.sub(r"^(?:my |the )?(?:game project|project|game)\s+", "", raw, flags=re.IGNORECASE)
    if not _match(r"[\w][\w .'-]{0,79}", name) or re.search(r"\b(?:and|or)\b", name, re.IGNORECASE):
        raise ValueError("Unclear project name")
    return name


def _value(raw: str) -> str:
    raw = raw.strip().strip('"')
    if not _match(r"[\w][\w .+/#()'&-]{0,127}", raw) or re.search(
        r"\b(?:maybe|probably|possibly|preferably|perhaps|presumably|apparently|might|could|would|may|i think|i guess|not|or)\b",
        raw, re.IGNORECASE,
    ):
        raise ValueError("Unclear fact value")
    return raw


def _target(text: str) -> tuple[str | None, str | None]:
    match = _match(rf"(?:its|their|the)\s+({KEY_PATTERN})", text)
    if match:
        return None, KEYS[match[1].casefold()]
    match = _match(rf"(.+?)'s\s+({KEY_PATTERN})", text)
    if match:
        return _subject(match[1]), KEYS[match[2].casefold()]
    return _subject(text), None


def _statement(text: str, action: Action) -> Intent:
    named = _match(rf"(?:its|(.+?)'s)\s+({KEY_PATTERN})\s+(?:is|uses)\s+(.+)", text)
    if named:
        subject = _subject(named[1]) if named[1] else None
        key, raw_values = KEYS[named[2].casefold()], named[3]
    else:
        statement = _match(r"(.+?)\s+uses\s+(.+)", text)
        if statement is None:
            raise ValueError("No supported assignment")
        subject, key, raw_values = _subject(statement[1]), None, statement[2]

    expected = None
    if action == "correct":
        parts = re.split(r",?\s+not\s+", raw_values, maxsplit=1, flags=re.IGNORECASE)
        raw_values = parts[0]
        if len(parts) == 2:
            expected = _value(parts[1])

    facts = []
    for part in re.split(r"\s+and\s+", raw_values, flags=re.IGNORECASE):
        property_value = _match(rf"(.+?)\s+(?:for|as)\s+(?:its|the)\s+({KEY_PATTERN})", part)
        value = _value(property_value[1] if property_value else part)
        property_key = KEYS[property_value[2].casefold()] if property_value else key or TECHNOLOGY_KEYS.get(value.casefold())
        if property_key is None or any(existing == property_key for existing, _ in facts):
            raise ValueError("Unclear or duplicate property")
        facts.append((property_key, value))
    if expected is not None and len(facts) != 1:
        raise ValueError("Unclear previous value")
    return Intent(action, subject, facts=tuple(facts), expected=expected)


def _replacement(target: str, new: str, old: str | None = None) -> Intent:
    subject, key = _target(target)
    value = _value(new)
    expected = _value(old) if old else None
    referent = key is None and target.casefold() in {"it", "the previous one"}
    if target.casefold() == "the previous one":
        subject = None
    inferred = TECHNOLOGY_KEYS.get(value.casefold())
    previous_key = TECHNOLOGY_KEYS.get(expected.casefold()) if expected else None
    if key is None and previous_key and inferred and previous_key != inferred:
        raise ValueError("Replacement refers to different properties")
    key = key or (None if referent else inferred)
    return Intent("correct", subject, key, value=value, expected=expected)


def _archive_terms(text: str) -> tuple[str, ...] | None:
    match = _match(
        r"what did i (?:say|mention) about (.+?) in (?:our|my|the) (?:previous|past|earlier) conversations", text,
    ) or _match(
        r"what did i (?:say|mention) about (.+?) in (?:this|the (?:active|current)) (?:chat|conversation|session)", text,
    ) or _match(r"what did i (?:previously|earlier) (?:say|mention) about (.+)", text) or _match(
        r"find where i mentioned (.+)", text,
    )
    if match:
        query = re.sub(r"^(?:a |my |the )?(?:project (?:called |named )?)", "", match[1], flags=re.IGNORECASE)
    else:
        match = _match(r"did i ever talk about (.+)", text)
        if not match:
            if re.search(
                r"\b(?:previous conversations|past conversations|find where i mentioned|"
                r"what did i (?:previously|earlier) (?:say|mention)|did i ever talk about)\b", text, re.IGNORECASE,
            ):
                raise ValueError("Specify an archive topic")
            return None
        query = re.sub(r"^(?:using|use)\s+", "", match[1], flags=re.IGNORECASE)
        query = re.sub(r"\s+for\s+", " ", query, flags=re.IGNORECASE)

    if len(query) > 120 or not _match(r"[\w .+#/-]+", query):
        raise ValueError("Invalid literal archive query")
    terms = tuple(query.split())
    if not 1 <= len(terms) <= 8 or any(len(term) < 2 for term in terms):
        raise ValueError("Specify a narrower archive topic")
    if any(term.casefold() in {"everything", "anything", "all", "it", "that", "something", "or", "and"} for term in terms):
        raise ValueError("Ambiguous archive query")
    return terms


def _fact_question(text: str) -> Intent | None:
    """Strict single-property questions; comparisons and explanations do not match."""
    match = _match(rf"(?:what is|what's) (?:its|(.+?)'s) (?:current )?({KEY_PATTERN})", text)
    if match:
        return Intent("saved_recall" if "current " in text.casefold() else "recall",
                      _subject(match[1]) if match[1] else None, KEYS[match[2].casefold()])
    match = _match(rf"(?:what is|what's) the (?:current )?({KEY_PATTERN}) (?:for|of) (.+)", text)
    if match:
        return Intent("saved_recall" if "current " in text.casefold() else "recall",
                      _subject(match[2]), KEYS[match[1].casefold()])
    match = _match(rf"what does (.+?) use for (?:its|the) ({KEY_PATTERN})", text)
    if match:
        return Intent("recall", _subject(match[1]), KEYS[match[2].casefold()])
    match = _match(rf"(?:what|which) ({KEY_PATTERN}) (?:does|is) (.+?) (?:currently )?(?:use|using)(?: now)?", text)
    if match:
        return Intent("saved_recall" if re.search(r"\b(?:currently|now)\b",text,re.I) else "recall",
                      _subject(match[2]), KEYS[match[1].casefold()])
    return None


def parse_intent(prompt: str) -> Intent | None:
    text = prompt.replace("’", "'").strip().rstrip(".?!").strip()
    explicit = _match(r"(?:please\s+)?(remember|save|forget|keep in mind|make a note)\b(?:\s+that\b)?\s*(.*)", text)
    change = _match(
        r"(?:(?:i'm|i am) (?:changing|switching|updating)|(?:i |i've |i have )(?:changed|switched|updated)|"
        r"(?:then )?(?:please )?(?:change|switch|update|correct))\s+(.+?)\s+to\s+(.+)", text,
    )
    replace = _match(r"(?:(?:i'm|i am) replacing|(?:i |i've |i have )replaced|(?:please )?replace)\s+(.+?)\s+with\s+(.+)", text)
    correction = _match(r"actually[, ]+(.+)", text)
    try:
        # A same-message assertion plus question is context, never permission to update memory.
        compound = _match(r"(.+?)[.;]\s*((?:what(?:'s| is)?|which|how|why|would|could|should|can|does|is)\b.+)", text)
        if compound and not (explicit or change or replace):
            question = _fact_question(compound[2])
            if question:
                assertion = re.sub(r"^(?:actually[, ]+|correction[:, ]+)","",compound[1],flags=re.I)
                assertion = re.sub(r"\bnow uses\b","uses",assertion,flags=re.I)
                assertion = re.sub(r"\b(uses|is) now\b",r"\1",assertion,flags=re.I)
                try:
                    claim = _statement(assertion,"correct")
                except ValueError:
                    return None
                if (claim.subject and question.subject and claim.subject.casefold()==question.subject.casefold()
                        and len(claim.facts)==1 and claim.facts[0][0]==question.key):
                    return Intent("recall",question.subject,question.key,facts=claim.facts)
            return None  # Do not reinterpret an unresolved contextual correction as a write.
        if re.fullmatch(r"[\w .'-]+\.\w+\s*=\s*.+", text):
            return Intent("unsupported_assignment")
        if _match(r"(?:tell me|show me|what is|what's) (?:its |the )?current(?: value| one)?|and the current one", text):
            return Intent("saved_recall")
        if _match(r"what did i (?:just (?:tell you|say)|say just now)", text):
            return Intent("session_recall")
        archive = _archive_terms(text)
        if archive is not None:
            scope = "all"
            if re.search(r"\b(?:previous|past|earlier) conversations\b", text, re.IGNORECASE):
                scope = "other"
            elif re.search(r"\bin (?:this|the (?:active|current)) (?:chat|conversation|session)\b", text, re.IGNORECASE):
                scope = "current"
            return Intent("archive", terms=archive, archive_scope=scope)
        if explicit:
            if explicit[1].casefold() == "forget":
                subject, key = _target(explicit[2])
                return Intent("forget", subject, key) if key else Intent("clarify")
            return _statement(explicit[2], "save")
        if change:
            before = _match(r"(.+?)\s+from\s+(.+)", change[1])
            return _replacement(before[1], change[2], before[2]) if before else _replacement(change[1], change[2])
        if replace:
            return _replacement(replace[1], replace[2])
        if correction and re.search(rf"\buses\b|\b{KEY_PATTERN}\s+is\b", correction[1], re.IGNORECASE):
            return _statement(correction[1], "correct")
        temporal = re.sub(r"^by the way,?\s+", "", text, flags=re.IGNORECASE)
        if not prompt.rstrip().endswith("?") and _match(r".+ (?:now|instead)", temporal):
            assignment = temporal.rsplit(maxsplit=1)[0]
            if re.search(rf"\buses\b|\b{KEY_PATTERN}\s+is\b", assignment, re.IGNORECASE):
                return _statement(assignment, "correct")

        match = _match(rf"what was the previous ({KEY_PATTERN}) i recorded for (.+)", text)
        if match:
            return Intent("history", _subject(match[2]), KEYS[match[1].casefold()])
        if _match(r"what about my project", text):
            return Intent("list")
        match = _match(r"(?:what's|what is) (.+?) built with", text)
        if match:
            return Intent("list", _subject(match[1]))
        match = _match(r"(?:what's|what is) the current stack for (.+)", text)
        if match:
            return Intent("list", _subject(match[1]))
        match = _match(r"show (?:my )?saved information about (.+)", text)
        if match:
            return Intent("list", _subject(match[1]))
        match = _match(r"what technology was (.+?) previously using", text)
        if match:
            return Intent("history", _subject(match[1]), broad=True)

        match = _match(r"(?:what do you remember|tell me (?:everything|what) you(?:'ve| have) saved) about (.+)", text)
        if match:
            return Intent("list", _subject(match[1]))
        match = _match(r"which (?:of my projects|(?:of my )?projects?|game|one) uses? (.+)", text)
        if match:
            return Intent("find", value=_value(match[1]))
        match = _match(rf"what was (?:its|(.+?)'s) previous ({KEY_PATTERN})", text)
        if match:
            return Intent("history", _subject(match[1]) if match[1] else None, KEYS[match[2].casefold()])
        match = _match(
            rf"(?:what|which) ({KEY_PATTERN}) (?:was (.+?) (originally|previously) using|"
            r"did (.+?) (originally|previously) use(?: for (.+))?)", text,
        )
        if match:
            subject = match[6] or match[2] or match[4]
            return Intent("history", None if subject.casefold() == "i" else _subject(subject), KEYS[match[1].casefold()],
                          original=(match[3] or match[5]).casefold() == "originally")
        match = _match(rf"(?:what|which) ({KEY_PATTERN}) did (.+?) use before(?:\s+(.+))?", text)
        if match:
            subject = None if match[2].casefold() == "i" else _subject(match[2])
            return Intent("history", subject, KEYS[match[1].casefold()], value=_value(match[3]) if match[3] else None)
        match = _match(r"what (?:was|were) (.+?) using before", text)
        if match:
            return Intent("history", None if match[1].casefold() == "i" else _subject(match[1]))
        question = _fact_question(text)
        if question:
            return question
        match = _match(r"what did (.+?) use before(?:\s+(.+))?", text)
        if match:
            return Intent("history", None if match[1].casefold() == "i" else _subject(match[1]),
                          value=_value(match[2]) if match[2] else None)
        match = _match(rf"(?:what|which) ({KEY_PATTERN}) (?:did i save|am i using) for (.+)", text)
        if match:
            action = "saved_recall" if "did i save" in text.casefold() else "recall"
            return Intent(action, _subject(match[2]), KEYS[match[1].casefold()])
        if _match(r"(?:and |what about )?the previous one", text):
            return Intent("history")
        if _match(r"(?:and |what about )?before that", text):
            return Intent("history", relative=True)
        match = _match(
            rf"(?:and |what about )?(?:its|the) ({KEY_PATTERN})|(?:what|which) ({KEY_PATTERN}) do i use(?: now)?", text,
        )
        if match:
            return Intent("recall", key=KEYS[(match[1] or match[2]).casefold()])
    except ValueError:
        return Intent("clarify")

    if re.match(r"^(?:then\s+)?(?:please\s+)?(?:correct|change|switch|update|replace)\b", text, re.IGNORECASE):
        return Intent("clarify")
    if prompt.rstrip().endswith("?"):
        if re.search(r"\b(?:before|earlier|previous(?:ly)?|original(?:ly)?)\b", text, re.IGNORECASE) and re.search(
            rf"\b(?:{KEY_PATTERN}|(?:my |this |that )projects?|saved (?:fact|value))\b", text, re.IGNORECASE,
        ):
            return Intent("clarify")
        return None
    try:
        return _statement(text, "statement")
    except ValueError:
        return None


def mentioned_projects(prompt: str) -> list[str]:
    """Recognize explicit project names in ordinary chat without proposing a write."""
    text = prompt.replace("’", "'").strip().rstrip(".!?")
    match = re.search(
        r"\b(?:projects|project (?:is )?(?:called|named)|game (?:is )?(?:called|named))\s+(.+?)"
        r"(?=\s+(?:uses?|are|is|for|with|built)\b|[,;.!?]|$)", text, re.IGNORECASE,
    )
    if match is None:
        match = _match(r"my (?:game project|project|game) (.+?) (?:is|has|uses|runs)\s+.+", text)
    if match is None:
        return []
    names = []
    for candidate in re.split(r"\s+(?:and|or)\s+", match[1], flags=re.IGNORECASE):
        try:
            name = _subject(candidate)
        except ValueError:
            continue
        if name:
            names.append(name)
    return names
