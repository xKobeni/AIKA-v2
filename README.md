# AIKA AI V2

AIKA is a Windows-first, local-first personal AI companion. The long-term goal is an animated desktop character that can converse, remember useful information, act with permission, and react to enabled desktop signals.

Development starts with a headless backend and a CLI for verification. The planned backend is a Python 3.12+ modular monolith with SQLite as its first durable store. Local inference through Ollama begins in Phase 1A. The future desktop interface will consume backend events, with React, TypeScript, and Tauri as candidates.

## Current checkpoint

Phase 4B adds user-selected source reading and evidence-grounded answers through the existing conversation lifecycle. DDGS/Tavily search, calculator, approved Windows apps, system information, memory, and persistence remain. Search and source reading are independently disabled by default. No autonomous browsing or planning is enabled.

The conversation reliability update prefers `qwen3.5:4b` when no model override is set. Saved chats can be resumed with either model.

## Run on Windows

Open PowerShell in this project's root. Create a Python 3.12 virtual environment and use its Python directly.

```powershell
py -3.12 -m venv .venv
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install -e '.[dev]'
& $python -m aika
& $python -m aika --version
& $python -m aika doctor
& $python -m aika --help
& $python -m pytest -q
```

To activate the environment instead, run `.\.venv\Scripts\Activate.ps1` and replace `& $python` with `python` in the commands above.

| Command | Expected result |
| --- | --- |
| `python -m aika` | Core runtime `READY`, configuration `LOADED`, configured model, and current phase `4B`. This command works offline. |
| `python -m aika --version` | `AIKA AI V2 0.1.0` by default. |
| `python -m aika doctor` | Runtime, SQLite, memory, Ollama, calculator, application, Windows measurement, and optional search configuration/contract checks. It never launches applications, samples system metrics, enumerates processes, or contacts Tavily. Missing optional web credentials produce `WARN` and do not prevent local use. |
| `python -m aika chat` | Opens an interactive session with the configured local model. Use `exit`, `/exit`, Ctrl+C, or EOF to quit. |
| `python -m aika memory --help` | Commands to save, retrieve, list, revise, and delete structured facts. Works without Ollama. |
| `python -m aika --help` | Usage, `chat`, `doctor`, `memory`, and `--version`. |
| `python -m pytest -q` | All runtime tests pass. |

Exit codes are `0` for success or warnings, `1` for a configuration, storage startup, or runtime check failure, and `2` for invalid CLI syntax. Doctor rolls back its write probe on an existing database. With no database yet, it uses a temporary SQLite file and leaves the real data path alone.

## Chat with a local model

Install and open [Ollama for Windows](https://ollama.com/download/windows). It normally serves the API on port `11434` in the background. If the Windows app is closed, you can run `ollama serve` in a separate PowerShell window instead. Use `ollama list` to see which models are already installed. [Ollama Windows documentation](https://docs.ollama.com/windows)

Install the default model if you want to use it and it is missing. This command downloads the model separately from AIKA.

```powershell
ollama pull qwen3.5:4b
```

An existing `AIKA_OLLAMA_MODEL` override takes precedence. To switch this PowerShell session to Qwen3.5, run the following from the V2 root. You can also set the variable to `qwen2.5:3b` or another installed local chat model.

```powershell
$python = '.\.venv\Scripts\python.exe'
$env:AIKA_OLLAMA_MODEL = 'qwen3.5:4b'
& $python -m aika doctor
& $python -m aika chat
```

| Symptom | What to check |
| --- | --- |
| Ollama cannot connect or the model check times out | Open Ollama or run `ollama serve`. Check the loopback port and allow startup to finish before retrying. |
| Model unavailable | Run `ollama list`, select an installed chat model, or use the `ollama pull` command shown by AIKA. |
| Generation times out | Retry or increase `$env:AIKA_MODEL_TIMEOUT` if the selected model needs longer to load or generate. |
| Ollama returns an HTTP error or no usable text | Check the service and retry with an installed model that supports text chat. |
| Ollama reaches its generation limit | Try a shorter request. If you enabled thinking, try `AIKA_OLLAMA_THINK=off`. AIKA leaves the incomplete exchange out of saved history. |
| SQLite cannot open or write the database | Check `AIKA_DATA_DIR`, its permissions, and available disk space, then run `doctor` again. |
| SQLite reports a corrupt or incompatible database | Keep the existing file. To start a separate clean database, choose a different absolute `AIKA_DATA_DIR`. |
| A saved chat changed in another window | Run `/resume` with the same ID before retrying the prompt. |

Chat sends the system instruction, up to 10 recent completed user/assistant turns by default, and your latest message to Ollama. The limit counts turns and does not measure model tokens. Earlier saved turns stay in SQLite even after they leave the model context.

## Saved conversations

The database is `conversations.sqlite3` under `AIKA_DATA_DIR`, which defaults to `%LOCALAPPDATA%\AIKA AI V2\data` on Windows. Completed exchanges are saved together before the reply is displayed. A chat appears in the saved list after its first successful exchange. If generation or saving fails, the pending exchange stays out of chat history. An application launch cannot be rolled back if saving subsequently fails; AIKA reports that outcome and asks you to check the application before retrying. Launches are never automatically retried.

Run `/sessions` to see saved conversations and copy the full ID. Run `/resume <session_id>` to load its recent turns. Each chat opens with fresh context until you resume a saved conversation. Permanent chat deletion is planned for a later phase.

| In-chat command | Action |
| --- | --- |
| `/help` | Show the conversation commands. |
| `/tools` | List registered tools, permission classifications, and enabled status. |
| `/calc <expression>` | Execute the calculator through the same executor used by natural-language arithmetic. |
| `/apps` | List approved application IDs, launch-target availability, and enabled state. |
| `/open <application>` | Launch one explicitly selected approved application through the tool executor. |
| `/system` | Collect a compact current Windows OS, CPU, RAM, and system-drive snapshot. No arguments accepted. |
| `/processes [limit]` | List running process names, PIDs, and resident memory. Default 10, allowed range 1–25; no flags accepted. |
| `/web <query>` | Search through the configured mode when enabled. Sends the query externally. |
| `/web --provider ddgs|tavily <query>` | Choose exactly one provider for this request; no fallback. |
| `/web-status` | Show provider, enablement, key presence, registration, readiness, and result limit without searching. |
| `/clear` | Start with empty context. The previous saved chat remains available to resume. |
| `/history` | Show the retained messages from the current chat. |
| `/status` | Show the configured model and how many completed turns are retained. |
| `/sessions` | List saved conversations with stable IDs and first-message previews. |
| `/resume <session_id>` | Switch to a saved conversation and load its recent turns. |
| `/new` | Start a fresh chat while keeping saved conversations. |
| `/exit` or `exit` | End the session. Ctrl+C and EOF also exit. |

## Structured memory

Conversation history stores what was said in a chat. Structured memory stores explicitly entered facts by entity type, subject, and key. Both use `AIKA_DATA_DIR/conversations.sqlite3`. Opening chat or running a memory command adds the version 2 memory tables to a compatible Phase 1C database. Doctor checks compatibility without migrating the configured database. Phase 2C-B uses the same schema.

### Remember and recall in chat

- Say `Remember that my project Orion uses Next.js for its frontend and PostgreSQL for its database.` AIKA saves both facts together before confirming.
- `Keep in mind that Eclipse uses Astro` and `Make a note that Eclipse's database is PostgreSQL` also request a save.
- Ask `What frontend does Orion use?` or `What do you remember about Orion?`. Saved facts can be recalled in a fresh chat without resuming the old transcript.
- Ask `What framework was Eclipse originally using?`, `Which of my projects uses PostgreSQL?`, or `Tell me everything you've saved about Eclipse.` Original-value questions use the first saved revision. Previous-value questions use the preceding saved revision.
- Say `I'm changing Orion's frontend to SvelteKit.` Then ask `What did I use before?`. AIKA keeps earlier revisions. It asks for clarification when a reference could point to more than one project.
- `Correct it to SvelteKit` and `Then correct it to Astro` use the clearly identified project and property. Follow with `tell me the current`, `What is its current value?`, or `And the current one?` to read the saved current value.
- `I switched Eclipse from Astro to SvelteKit` checks the stated old value against the saved value. For `I'm replacing it with SvelteKit`, the retained chat and saved facts must identify the project and property. When AIKA asks which project or property you mean, reply with the name to continue, or `cancel` to discard the request.
- Say `Forget Orion's frontend.` Reply `yes` to delete the identified fact and its revisions, or `cancel` to keep them. A different chat message supersedes the request. `/new`, `/clear`, `/resume`, and restart discard pending confirmation. Transcripts and backups may still contain the information.

Chat recognizes a bounded set of project properties, including frontend, database, engine, project type, backend, and language. State the property explicitly when a technology name does not identify it. An ordinary statement becomes a correction only when all its named facts already exist and the intent is clear. AIKA does not automatically save new facts from ordinary chat. Use the memory CLI for arbitrary keys and entity types.

Assignment notation such as `Nova.engine = Godot` is treated as an unsupported memory request and makes no change. Say `Remember that my game Nova uses Godot as its engine` to save it explicitly.

When correcting a property you mentioned only in chat, AIKA can offer to save the new value. Reply `yes` to create revision 1 or `cancel` to leave it unsaved. Only the active or explicitly resumed transcript can supply earlier chat context. An unrelated message, session switch, or restart discards a pending clarification or confirmation.

### Retrieve the right source

| Question | Source |
| --- | --- |
| `What frontend does Atlas currently use?` | The current saved fact. An absent fact is reported as missing. |
| `What's Atlas built with?` or `What's the current stack for Atlas?` | A summary of Atlas's saved facts. |
| `Which frontend did I save for Atlas?` | The matching saved frontend fact. |
| `What frontend did Orion use before?` | The saved revision immediately before the current one. |
| `What framework did Orion originally use?` | The earliest saved revision. |
| `And before that?` | The preceding revision of the specific fact last retrieved in this chat. |
| `What did I mention about Atlas in my previous conversations?` | Historical user-authored messages from other saved sessions. |
| `What did I mention about Atlas in this chat?` | Matching user statements from the active saved session. |
| `Find where I mentioned Atlas.` or `Did I ever talk about using Vue for Atlas?` | Archived messages containing all the literal search terms. |
| `What did I previously mention about PostgreSQL?` | Archived user statements mentioning PostgreSQL. |
| `What did I just tell you?` | The latest user message available in the active context. |

Historical search returns up to five distinct user messages, newest first, with excerpts of at most 402 characters including truncation markers. Repeated identical messages appear once. Search matches whole terms case-insensitively and excludes recognized recall and deletion requests. It scans the configured SQLite store when explicitly requested. A broad question such as `What did I previously mention about Atlas?` can include both the active and other sessions, with each result labeled by origin. Its quoted results remain historical evidence even if a newer saved fact differs. Deleting a structured fact can leave older chat mentions available to this explicit search.

The search supports literal terms and project names. SQL syntax, wildcard expressions, broad requests such as `everything`, and queries longer than eight terms or 120 characters require a more specific request. Very large archives can take longer to scan. No archive index or schema migration is introduced.

### Inspect and manage facts with the CLI

Run these examples from the V2 root in PowerShell. Each example command runs in its own Python process, so the reads also check persistence.

```powershell
$python = '.\.venv\Scripts\python.exe'
& $python -m aika memory set --type project --subject Orion --key frontend --value Next.js
& $python -m aika memory set --type project --subject Orion --key frontend --value SvelteKit
& $python -m aika memory get --type project --subject Orion --key frontend
& $python -m aika memory history --type project --subject Orion --key frontend
& $python -m aika memory list --type project --subject Orion
& $python -m aika memory delete --type project --subject Orion --key frontend --confirm
```

Each key has one active text value. Entity type, subject, and key lookups ignore case and collapse repeated whitespace. A changed value adds a revision to the same fact ID. Saving the same value leaves its history unchanged. `delete --confirm` removes the selected fact and its revisions from the active database. Conversation transcripts and backups may still contain the information. Deletion does not securely erase SQLite remnants.

To review without changing your archive, follow the [temporary-database walkthrough](docs/phase-reports/PHASE_2A_REPORT.md#manual-acceptance). The automated suite uses temporary SQLite files, and can be run with `& $python -m pytest -q`.

## Verified calculator

Start `python -m aika chat`, then try:

```text
What is 245 multiplied by 18?
/calc (125 + 75) / 4
What is 0.1 + 0.2?
What is 15% of 800?
/calc 100 / 0
/tools
```

The first four results are `4410`, `50`, `0.3`, and `120`. Division by zero produces an error. Supported wording includes `calculate`, `compute`, `evaluate`, `what is`, and `what's`, with `plus`, `minus`, `times`, `multiplied by`, or `divided by`. Bare arithmetic expressions also work. Ambiguous wording stays in ordinary conversation; use `/calc` for an explicit calculator request.

The calculator allows decimal numbers, unary signs, parentheses, `+`, `-`, `*`, `/`, and simple literal percentages such as `15% of 800`. It uses a restricted AST parser with no Python `eval` or `exec`. Calls, names, attributes, imports, powers, floor division, modulo, and scientific notation are rejected. Limits are 512 input characters, 128 AST nodes, nesting depth 16, and 50 digits per literal. Arithmetic uses 50 significant decimal digits with half-even rounding; repeating divisions are rounded. Nonzero intermediate and final magnitudes must stay between `1e-100` and `1e100`, and displayed results are limited to 128 characters.

Recognized invalid calculations return a controlled error without model fallback. Completed results and errors appear in the existing SQLite transcript and survive `/resume`. They do not automatically become structured facts. A storage failure is reported before displaying the reply. No schema migration or second database is introduced.

`calculator.evaluate`, `system.snapshot`, and `system.processes` are `READ_ONLY`. The separate `app.open` tool uses `LOCAL_ACTION` and requires authorization bound to the current explicit application request. Other local actions and all `SENSITIVE_ACTION` tools remain denied.

With `AIKA_CONTEXT_DEBUG=roles` or `content`, tool diagnostics show recognized intent, selected tool, permission, input validation, execution status, verification, and elapsed milliseconds. Expressions, results, and exception details are excluded from tool traces. Normal chat/history output still displays the user's request and answer.

## Approved Windows application launches

In `python -m aika chat`, try:

```text
/apps
Open Notepad.
/open notepad
Launch the Windows Calculator.
Can you open Spotify?
```

Notepad and Windows Calculator use only their fixed executable names in the system directory returned by Windows. The launcher uses an absolute one-element argument list with `shell=False` and the system directory as its working directory. It accepts no user arguments, executable paths, scripts, downloads, or elevation requests. Targets are validated at registration and checked again before launch, including rejection of redirected/reparse-point executables. `/apps` reports whether the approved launch executable exists, independently of whether the target is enabled; this does not prove that a Store application is installed or ready.

Spotify is listed as unavailable because this checkpoint has no audited Spotify launch adapter. AIKA does not infer whether Spotify is installed and does not use a protocol handler, arbitrary installation path, or shell command as a fallback.

Exact names and aliases include `notepad`, `windows notepad`, `calculator`, `windows calculator`, `calc`, and `spotify`. Requests can start with `open`, `launch`, or `start`, optionally with `please`, `can you`, `could you`, or `would you`. `Start Notepad for me` is supported. Unknown targets, command-like strings, extra arguments, and compound requests do not launch anything or enter ordinary model generation. Ambiguous requests ask which registered application you mean. Use `/open` for an explicit target.

A verified result means the process created from the approved executable was still running at the 250 ms observation deadline; the reply gives its actual PID and explicitly states that window readiness was not checked. If a launcher exits successfully before that deadline, AIKA reports **launch initiated; verification inconclusive**. Microsoft Store handoffs can use another PID, so a zero exit code never becomes proof that the application opened. Nonzero exits and OS creation errors are reported as failures. There are no automatic retries or background launches.

To disable approved applications in this PowerShell session, set the following before starting AIKA:

```powershell
$env:AIKA_DISABLED_APPS = '["notepad", "calculator"]'
python -m aika chat
```

The default is `[]`. Only unique IDs `notepad`, `calculator`, and `spotify` are accepted. To restore defaults, run `Remove-Item Env:AIKA_DISABLED_APPS` in the same shell. Executable definitions are code-owned; this setting cannot add applications or change paths. Doctor reports invalid configuration without echoing its raw values.

This checkpoint adds no schema migration or second database. `/history` and `/resume` retain completed action replies without replaying them. Tool traces use the existing debug setting and omit application arguments, paths, PIDs, and execution output.

## Windows system information

System information uses `psutil>=7,<8` and Python's standard-library Windows/platform interfaces. Installing the project with `python -m pip install -e '.[dev]'` installs this dependency. No system shell, PowerShell, WMI subprocess, or administrator privileges are used.

Try these in `python -m aika chat`:

```text
/system
What's my CPU usage?
How much RAM am I using?
How much free space is on my system drive?
What Windows version am I using?
/processes
/processes 15
Which processes are using the most RAM?
```

Natural-language recognition is bounded and deterministic. `Show my PC specs`, `How busy is my processor?`, `How many CPU cores do I have?`, `Check my storage`, and `List the top 10 processes by memory` are supported. General questions such as `Explain how RAM works` stay conversational. Recognized requests and validation errors never fall through to Ollama for invented measurements.

| Measurement | Meaning |
| --- | --- |
| CPU utilization | A fresh total usage sample over a fixed 0.1-second interval, not an uninitialized first reading or a permanent condition. |
| CPU cores | Logical processor count and physical core count when the API provides it. Missing counts are unavailable. |
| RAM used | Total physical RAM minus the API's available physical RAM. Values stay in bytes internally and are displayed consistently as GiB (`1024^3` bytes). |
| RAM available | Physical memory available for allocation/reuse, not a separate measurement of strictly unused pages. Windows psutil exposes the same underlying available value as its `free` field; AIKA labels it available and does not invent another free-RAM value. |
| Storage | Total, used, free, and percent used on the actual Windows system drive, determined from the Windows system directory. No fixed `C:` assumption or network/external-drive scanning. |
| OS | Reported Windows name/version, build, and architecture. Unavailable fields are labeled rather than inferred. |
| Process memory | Resident set/working-set bytes, displayed in GiB. Shared memory can overlap between processes, so this is not an exclusive allocation or a sum of physical RAM usage. |

Every successful result includes an actual timezone-aware UTC collection timestamp and measurement source. Focused CPU, RAM, storage, or OS questions collect only that section. A system summary collects those four sections and never a process inventory. There is no metric cache or background monitor. Missing optional fields and partial failures are shown explicitly; a completely failed requested measurement is not verified.

Process results default to PID order. Requests for the largest memory users sort measured resident memory descending, with unavailable memory values last and PID breaking ties. Only up to 25 rows are retained for output; ranking may inspect all current processes. Protected processes or ones that exit during inspection are handled without elevation. Unavailable names or memory values stay unavailable. Process names are reduced to basenames, stripped of terminal controls, and capped at 120 characters. A process list does not prove that any application window is visible or responsive. Per-process CPU usage is not implemented.

These tools never request process command lines, environment variables, usernames, open files, window contents, credentials, or histories. Debug traces contain tool execution metadata, not measurements or process lists. The displayed request/reply is saved in the existing SQLite conversation history and can contain process names and PIDs; this is not automatically saved as long-term facts. System measurement exchanges are excluded from subsequent ordinary Ollama context, including after `/resume`, to avoid sending inventories or presenting stale snapshots as current. `/history` still shows the saved replies. Manually supplied user text follows the normal conversation rules.

CPU temperature monitoring is not implemented. `What's my CPU temperature?` or `Is my CPU overheating?` receives an explicit limitation without guessing from utilization. `Why is my PC slow?` can return a current summary, with a reminder that one snapshot cannot establish the cause. No process termination, application closing, filesystem changes, network monitoring, screen inspection, or later-phase capabilities are added.

## Optional hybrid web search

One registered `web.search` tool routes to independent `DDGSSearchProvider` and `TavilySearchProvider` adapters. Web access remains disabled by default. Install the updated project dependencies with `python -m pip install -e '.[dev]'`; this includes the audited maintained `ddgs==9.16.1` library.

| Provider mode | Default behavior | Fallback |
| --- | --- | --- |
| `auto` (default) | DDGS first, free and keyless | Off by default; only an explicitly enabled secondary may run after unavailable/timeout/rate-limit errors. |
| `ddgs` | DDGS only | Never switches providers, even if fallback is enabled. |
| `tavily` | Tavily only; requires its API key and can consume credits | Never switches providers, even if fallback is enabled. |

To enable keyless search in a dedicated PowerShell window:

```powershell
$env:AIKA_WEB_SEARCH_ENABLED = 'on'
$env:AIKA_WEB_SEARCH_PROVIDER = 'auto'
$env:AIKA_WEB_SEARCH_FALLBACK_ENABLED = 'off'
python -m aika chat
```

Try:

```text
/web-status
/web official Python documentation
/web --provider ddgs recent Ollama updates
Search the web for recent Ollama updates.
```

DDGS uses the maintained [ddgs Python library](https://pypi.org/project/ddgs/), pinned at 9.16.1, with its documented `backend="auto"`, page 1, and a five-second native timeout. One adapter call can send the current query to several free search-engine backends within DDGS; it does not contact Tavily. Provider attribution remains DDGS because the library does not identify the underlying engine per result. No API key or paid account is needed. No extraction, API server, MCP server, TLS bypass, or AIKA retry is used. Backends can block or rate-limit requests. A returned empty list is a valid no-results outcome. The ambiguous `No results found.` exception is instead a controlled failure: it can hide rejected HTTP responses or parser failures, so it never authorizes paid fallback. Native timeout and rate-limit exceptions remain distinguishable. Local AVAILABLE status checks installation, not connectivity or source quality. DDGS's per-engine timeouts and thread shutdown do not guarantee a five-second total deadline.

Tavily remains optional. To authorize Tavily-only mode, enter its key through a hidden prompt so the literal key is absent from shell command history:

```powershell
$apiKeyInput = Read-Host 'Tavily API key' -AsSecureString
$env:AIKA_TAVILY_API_KEY = [System.Net.NetworkCredential]::new('', $apiKeyInput).Password
$apiKeyInput.Dispose()
Remove-Variable apiKeyInput
$env:AIKA_WEB_SEARCH_ENABLED = 'on'
$env:AIKA_WEB_SEARCH_PROVIDER = 'tavily'
python -m aika chat
```

For one deliberate Tavily search while the configured mode remains auto/DDGS, use `/web --provider tavily <query>`. Both per-request provider flags select exactly one provider and disable fallback for that request. Unknown or malformed flags are rejected. A key being present does not authorize automatic Tavily usage.

To authorize paid fallback deliberately, set all of the following before restarting chat, with a valid Tavily key present:

```powershell
$env:AIKA_WEB_SEARCH_PROVIDER = 'auto'
$env:AIKA_WEB_SEARCH_FALLBACK_ENABLED = 'on'
$env:AIKA_WEB_SEARCH_FALLBACK_PROVIDER = 'tavily'
```

This can consume Tavily credits when DDGS is unavailable, times out, or is rate-limited. Empty results, malformed results, bad input, and unexpected internal errors do not trigger fallback. Each selected provider runs at most once; there is no provider merging or automatic retry. A successful fallback reply names the provider used and shows `ddgs -> tavily`. If the secondary is configured as DDGS, it is the same as the auto primary and no second attempt is made. Explicit `ddgs`/`tavily` modes never fall back. To keep everything local, leave search settings unset or set `AIKA_WEB_SEARCH_ENABLED=off`.

The tool accepts a printable 1–300 character query, optional result count 1–5 (default five), and an optional explicit `ddgs`/`tavily` provider. It accepts no caller-provided URLs, headers, credentials, or arbitrary provider options. Both providers normalize to the same source record: actual optional title, URL/domain, snippet, provider, timezone-aware retrieval timestamp, and publication date only when supplied, plus rank/score when available. Missing fields are labeled unavailable. Retrieval time does not establish publication time or source freshness.

The Tavily adapter uses its fixed official HTTPS endpoint with `basic` search, `general` topic, and answer/raw-content/image/automatic-parameter options disabled. It retains 3-second connection/write/pool and 5-second read-inactivity timeouts, a 15-second budget checked between reads, no redirects, and no environment proxies. An in-progress read can extend to its inactivity timeout, so this is not hard preemption. The request format follows the [official Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search).

Both adapters limit returned rows and normalized content; titles are capped at 200 characters, snippets at 1,000, and normalized input at 512 KiB. Tavily additionally caps its streamed response at 512 KiB. DDGS buffers and parses search-engine responses inside its own library, so AIKA cannot impose the same raw-wire cap through its public API. DDGS_PROXY is rejected rather than silently using that alternate transport configuration. DDGS library logging is suppressed to avoid exceptions exposing queries. No result URL is fetched or crawled.

Explicit searches send only the current query and bounded options externally, never automatic chat context, structured facts, process inventories, system measurements, or files. Keys are hidden in object representations and redacted before model/transcript use, including recognizable `tvly-` token shapes. Credentials are not sent to DDGS; the configured Tavily key is used there only for redaction, never authentication or library parameters. Do not paste secrets into chat or commit them to files. Close the dedicated shell when done to discard its environment settings.

Search text is untrusted data, deterministically displayed rather than sent to Ollama as instructions. Safe HTTP(S) URL syntax, hostname/address checks, deduplication, control-character removal, and output contracts are shared by both adapters. These checks do not establish website safety or claim truth. A verified search result records the provider response reported by the adapter, not independent verification of its sources. Provider failures never become stale-model answers or fake citations. Selected HTTPS pages can now be read through `/read`, then used by `/ask-web`; searches alone do not fetch pages or supply article evidence.

Explicit search/current-information recognition remains bounded. Educational explanations, saved-memory questions, arithmetic, system information, and app launching retain their existing routes. Vague `search the internet for this` requests ask for a query instead of sending earlier context.

`/web-status` and doctor report provider mode, readiness, fallback policy, key presence, and contracts without searching or spending credits. A locally ready provider has not been connectivity/authentication-tested. Tool traces omit queries, keys, headers, and excerpts. SQLite saves displayed sources with their original provider and timestamp; `/resume` restores them without replaying searches. Search exchanges stay out of later ordinary Ollama context and do not automatically become memory facts. Search results are not globally cached.


## Selected source reading and grounded answers (Phase 4B)

Install updated dependencies with `python -m pip install -e '.[dev]'`. This adds Trafilatura for extraction from already retrieved HTML. Edit the project `.env` (process variables still take precedence):

```dotenv
AIKA_WEB_SEARCH_ENABLED=on
AIKA_WEB_READING_ENABLED=on
AIKA_WEB_SEARCH_PROVIDER=auto
AIKA_WEB_SEARCH_FALLBACK_ENABLED=off
```

Restart chat, then use:

```text
/web --provider ddgs latest Python release
/read 1
/read 2
/ask-web What release does each page identify? Do they agree?
```

`Read source 1.`, `Read the first result.`, and `Open and summarize source 2.` also select one page. Reading shows a short untrusted preview, actual URL, title, retrieval timestamp, and any explicit publication date. It does not synthesize an answer automatically. Select up to three pages from the current search; selecting a read source again reuses its active evidence. A new search clears the previous source set, including after a failed search. No result page is fetched until selected. Arbitrary URLs and source numbers outside the current result set are rejected. `/web-status` reports the separate reading gate.

The reader supports HTTPS on port 443 and HTML only. It rejects IP literals, credentials, local hostnames, and DNS answers containing any nonpublic address. The TCP connection uses the validated numeric address directly, with TLS verification/SNI for the original hostname, so it does not resolve the host again at connection time. It blocks redirects, environment proxies, cookies, authentication headers, file attachments, compressed responses, and non-HTML content. No JavaScript, secondary assets, crawling, retry, or paywall/CAPTCHA bypass is performed. Redirecting result URLs must be replaced by another directly readable search result; HTTP results are not upgraded.

Limits: three sources; 1 MiB downloaded HTML; 12,000 extracted characters per source; 3-second DNS/connect and 5-second read inactivity timeouts; a 15-second network budget with socket shutdown; no automatic retry. A bounded daemon resolver can outlive a timed-out lookup, with at most one pending lookup per process. These are application controls, not a sandbox for a compromised operating system or hostile network routing. See the [OWASP SSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html) and the phase report for the exact mechanism and limits.

`/ask-web` sends only the question and selected extracted passages to the configured local Ollama model; it never searches or fetches more pages. At most 2,400 characters per source and 15,000 prompt characters are allowed. The model must return a short structured answer with existing source IDs and exact supporting quotes. Invalid IDs, invented URLs, missing/invented quotes, obviously unsupported numbers, and malformed drafts produce an insufficient-evidence response without correction loops. The app attaches the real URLs and original retrieval timestamps. Quote/ID checks establish traceability and catch some errors; they cannot prove semantic entailment, freshness, truth, or that the model noticed every disagreement. Visible supporting quotes let you inspect each claim.

Full extracted text is active-session state only and is not saved as long-term memory. SQLite stores the bounded reading preview and completed answer/citations. These exchanges stay out of future ordinary model context. `/history` and `/resume` never refetch. Resume, restart, `/new`, `/clear`, or a new search discard full evidence; after resume, explicitly search and read sources again before asking a new grounded question. Saved answers keep their original source URLs and retrieval times. Reading sends the selected URL/path to that source site and performs DNS resolution, but sends no Tavily key, saved memory, conversation history, or system measurements.

Manual walkthrough: enable both gates; search; select a directly accessible HTTPS source; inspect `/read` preview; ask `/ask-web`; optionally select a second page and compare; inspect `/history`; resume and confirm a new grounded answer requires new reading. If a source redirects, is blocked, requires JavaScript, has no extractable text, or exceeds limits, expect a controlled failure. Ollama failures remain errors rather than guesses. Automated tests mock source HTTP and model responses and consume no provider credits.


## Configuration

AIKA automatically reads `.env` in the project root, regardless of the working directory. A local file with safe defaults is included; for a new checkout, copy `.env.example` to `.env`. Install updated dependencies with `python -m pip install -e '.[dev]'` (includes `python-dotenv`).

To use Tavily, edit `.env`:

```dotenv
AIKA_TAVILY_API_KEY=your-key-here
AIKA_WEB_SEARCH_ENABLED=on
AIKA_WEB_SEARCH_PROVIDER=tavily
```

Restart AIKA, then run `/web-status` and `/web <query>`. Tavily searches can consume credits. Keep fallback off unless deliberately authorizing it. The local `.env` is ignored by Git; `.env.example` contains only blank credentials and safe defaults. Never paste keys into chat or tracked code.

All optional variables below may be set in `.env` or PowerShell. Existing process environment variables override `.env`, including blank values. Quoted values and comments are supported; variable interpolation is disabled. Configuration reads do not modify the process environment.

| Variable | Default | Valid values |
| --- | --- | --- |
| `AIKA_APP_NAME` | `AIKA AI V2` | Public display name with 1–80 printable characters. |
| `AIKA_VERSION` | `0.1.0` | Numeric `X.Y.Z` application version override. Package metadata continues to use the built-in release version. |
| `AIKA_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. `DEBUG` shows a runtime summary with an invocation correlation ID. |
| `AIKA_DATA_DIR` | `%LOCALAPPDATA%\AIKA AI V2\data` | Absolute local directory. Falls back to `~/.aika-v2/data` if Windows local application data is unavailable. |
| `AIKA_OLLAMA_URL` | `http://127.0.0.1:11434` | Loopback HTTP(S) origin using `localhost`, `127.0.0.1`, or `[::1]`. Falls back to the existing `AIKA_RUNTIME_URL` setting when unset. |
| `AIKA_OLLAMA_MODEL` | `qwen3.5:4b` | An installed local chat model. Cloud models are unavailable. |
| `AIKA_MODEL_TIMEOUT` | `180` | Finite positive number of seconds to wait for generation I/O. Connection and model-list probes wait at most three seconds per I/O operation. |
| `AIKA_OLLAMA_THINK` | `off` | `off` requests no thinking where supported. `on` uses a supported thinking mode. `default` leaves the decision to the model. Only final assistant text is displayed and saved. |
| `AIKA_CONTEXT_TURNS` | `10` | Nonnegative whole number of completed turns to load into context. `0` keeps saving exchanges and sends only the system instruction and latest prompt. |
| `AIKA_CONTEXT_DEBUG` | `off` | `roles` shows the outgoing message order, model, session ID, retained turn count, and whether earlier saved turns were omitted. `content` also reveals explicitly approved public message text. |
| `AIKA_CONTEXT_DEBUG_PUBLIC` | `[]` | JSON array of exact public message strings to reveal in `content` mode. Unlisted and recognizable credential-like text stays hidden. |
| `AIKA_DISABLED_APPS` | `[]` | JSON array of unique approved application IDs to disable: `notepad`, `calculator`, `spotify`. No commands or paths are accepted. |
| `AIKA_WEB_SEARCH_ENABLED` | `off` | Explicit outbound-search gate: `off/on`, `false/true`, or `0/1`, case-insensitive. |
| `AIKA_WEB_SEARCH_PROVIDER` | `auto` | `auto` (DDGS first), `ddgs` only, or `tavily` only. |
| `AIKA_WEB_SEARCH_FALLBACK_ENABLED` | `off` | Explicit fallback opt-in, same boolean syntax. A Tavily secondary can consume credits. |
| `AIKA_WEB_SEARCH_FALLBACK_PROVIDER` | `tavily` | `ddgs` or `tavily`; never retries the primary or overrides explicit selection. |
| `AIKA_WEB_READING_ENABLED` | `off` | Separate source-reading opt-in; requires the existing web network gate too. |
| `AIKA_TAVILY_API_KEY` | empty | Optional secret ASCII token, at most 512 characters, without whitespace/control characters. Required only for Tavily; never displayed or sent to DDGS. |

To inspect the outbound message order, set `$env:AIKA_CONTEXT_DEBUG = 'roles'` before starting chat. Use `content` mode only in a synthetic test chat. Approved text appears on the terminal's error stream. Never approve private text or credentials.

When this setting is enabled, memory diagnostics also report the detected operation, recognized keys, lookup, commit, revision, validation status, evidence source types, and match count. Subject names stay hidden unless explicitly present in an approved public prompt. Stored values and archive excerpts are excluded from the memory trace.

## Project structure

```text
AIKA AI/
├── .gitignore
├── README.md
├── aika.py
├── pyproject.toml
├── docs/
│   ├── AIKA_V2_FOUNDATION.md
│   ├── AIKA_V2_IMPLEMENTATION_PHASES.md
│   ├── V1_PRESERVATION.md
│   ├── decisions/
│   │   └── README.md
│   └── phase-reports/
│       ├── MODEL_UPGRADE_QWEN35_REPORT.md
│       ├── PHASE_0A_REPORT.md
│       ├── PHASE_0B_REPORT.md
│       ├── PHASE_1A_REPORT.md
│       ├── PHASE_1B_REPORT.md
│       ├── PHASE_1C_REPORT.md
│       ├── PHASE_2A_REPORT.md
│       ├── PHASE_2B_REPORT.md
│       ├── PHASE_2C_A_REPORT.md
│       ├── PHASE_2C_B_REPORT.md
│       ├── PHASE_3A_REPORT.md
│       ├── PHASE_3B_A_REPORT.md
│       ├── PHASE_3B_B_REPORT.md
│       └── PHASE_4A_REPORT.md
├── src/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── diagnostics.py
│   ├── capabilities/
│   │   ├── __init__.py
│   │   ├── contracts.py
│   │   ├── registry.py
│   │   ├── executor.py
│   │   ├── calculator.py
│   │   ├── applications.py
│   │   ├── application_intent.py
│   │   ├── system_info.py
│   │   ├── system_intent.py
│   │   ├── web_search.py
│   │   ├── web_intent.py
│   │   └── intent.py
│   ├── intelligence/
│   │   ├── conversation.py
│   │   └── ollama_client.py
│   ├── memory/
│   │   ├── chat.py
│   │   ├── cli.py
│   │   ├── intent.py
│   │   ├── retrieval.py
│   │   └── store.py
│   └── storage/
│       ├── conversation_store.py
│       └── database.py
└── tests/
    ├── conftest.py
    ├── test_chat_memory.py
    ├── test_conversation.py
    ├── test_conversation_store.py
    ├── test_memory.py
    ├── test_retrieval.py
    ├── test_ollama.py
    ├── test_tools.py
    ├── test_applications.py
    ├── test_system_info.py
    ├── test_web_search.py
    ├── test_hybrid_search.py
    └── test_runtime.py
```

## Project documents

- [Foundation and architecture](docs/AIKA_V2_FOUNDATION.md) defines the architectural contracts.
- [Implementation phases](docs/AIKA_V2_IMPLEMENTATION_PHASES.md) defines the checkpoint order and acceptance gates.
- [V1 preservation](docs/V1_PRESERVATION.md) records the separate checkout and recovery procedure.
- [Architecture decisions](docs/decisions/README.md) describes how to propose changes to the baseline.
- [Phase 0A report](docs/phase-reports/PHASE_0A_REPORT.md) includes the manual acceptance checklist.
- [Phase 0B report](docs/phase-reports/PHASE_0B_REPORT.md) records implementation and runtime verification.
- [Phase 1A report](docs/phase-reports/PHASE_1A_REPORT.md) records the Ollama integration and manual acceptance steps.
- [Phase 1B report](docs/phase-reports/PHASE_1B_REPORT.md) records conversation tests and manual review steps.
- [Phase 1C report](docs/phase-reports/PHASE_1C_REPORT.md) records the SQLite schema, recovery tests, and manual acceptance steps.
- [Qwen3.5 reliability report](docs/phase-reports/MODEL_UPGRADE_QWEN35_REPORT.md) records the model upgrade, context investigation, and debugging walkthrough.
- [Phase 2A report](docs/phase-reports/PHASE_2A_REPORT.md) records the memory schema, migration checks, and manual acceptance steps.
- [Phase 2B report](docs/phase-reports/PHASE_2B_REPORT.md) records conversational memory behavior, test results, and manual acceptance.
- [Phase 2C-A report](docs/phase-reports/PHASE_2C_A_REPORT.md) lists supported phrasing, confirmation behavior, and the review walkthrough.
- [Phase 2C-B report](docs/phase-reports/PHASE_2C_B_REPORT.md) explains retrieval priorities, archive search, provenance, and manual acceptance.
- [Phase 3A report](docs/phase-reports/PHASE_3A_REPORT.md) explains tool execution, calculator limits, actual verification, and the manual acceptance walkthrough.
- [Phase 3B-A report](docs/phase-reports/PHASE_3B_A_REPORT.md) explains approved application launches, verification limits, permissions, and manual review steps.
- [Phase 3B-B report](docs/phase-reports/PHASE_3B_B_REPORT.md) explains read-only Windows measurements, process privacy, verification, and manual review steps.
- [Phase 4A report](docs/phase-reports/PHASE_4A_REPORT.md) records hybrid DDGS/Tavily setup, routing, fallback, costs and retrieval repairs.

- [Phase 4B report](docs/phase-reports/PHASE_4B_REPORT.md) records guarded source reading, citation checks, actual acceptance outcomes, and 791 passing regression tests. Next planned milestone: Phase 5 - Controlled Agent Planning (not implemented).
