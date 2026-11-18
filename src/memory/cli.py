import argparse
import sys
from pathlib import Path

from src.memory.store import MemoryInputError, MemoryStore


def add_memory_commands(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="memory_command", required=True)
    for name, help_text in (
        ("set", "save or update a fact"), ("get", "retrieve a fact"),
        ("list", "list an entity's facts"), ("history", "show a fact's revisions"),
        ("delete", "delete a fact and its revisions"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--type", dest="entity_type", required=True, help="entity type, e.g. project")
        command.add_argument("--subject", required=True)
        if name != "list":
            command.add_argument("--key", required=True)
        if name == "set":
            command.add_argument("--value", required=True)
        if name == "delete":
            command.add_argument("--confirm", action="store_true", help="confirm deletion of this fact and its revisions")


def run_memory(args: argparse.Namespace, data_dir: Path) -> int:
    command = args.memory_command
    if command == "delete" and not args.confirm:
        raise MemoryInputError("Use --confirm to delete the selected fact and its revisions.")

    store = MemoryStore(data_dir)
    if command == "list":
        facts = store.list_facts(args.entity_type, args.subject)
        if not facts:
            print("No facts found.")
        for fact in facts:
            print(f"{fact.subject} / {fact.key}: {fact.value}")
        return 0

    scope = (args.entity_type, args.subject, args.key)
    match command:
        case "set":
            fact, previous = store.set_fact(*scope, args.value)
            if previous is None:
                print("Memory saved.")
            elif previous == fact.value:
                print("Memory unchanged.")
            else:
                print(f"Memory updated.\nPrevious: {previous}")
            print(f"{fact.subject} / {fact.key}: {fact.value}\nRevision: {fact.revision}")
        case "get":
            fact = store.get_fact(*scope)
            if fact is None:
                return _not_found()
            print(f"{fact.subject} / {fact.key}: {fact.value}")
        case "history":
            history = store.get_history(*scope)
            if history is None:
                return _not_found()
            fact, revisions = history
            print(f"{fact.subject} / {fact.key}")
            for revision in revisions:
                print(f"Revision {revision.revision}: {revision.value}")
            print(f"Current: {fact.value}")
        case "delete":
            if not store.delete_fact(*scope, confirm=args.confirm):
                return _not_found()
            print("Fact and its revisions deleted from the active database.")
    return 0


def _not_found() -> int:
    print("Fact not found.", file=sys.stderr)
    return 1
