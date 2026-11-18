"""User-selected HTTPS retrieval with DNS validation bound to the connected address."""

import http.client
import ipaddress
import json
import queue
import re
import socket
import ssl
import threading
from dataclasses import asdict, replace
from datetime import datetime
from time import monotonic
from urllib.parse import unquote, urljoin, urlsplit

from src.capabilities.contracts import Permission, ToolDefinition, ToolExecutionError, ToolInputError, ToolStatus
from src.capabilities.web_content import MAX_TEXT, SourceEvidence, extract_evidence
from src.capabilities.web_diagnostics import WebFailure
from src.capabilities.web_budget import bounded_timeout
from src.capabilities.web_search import _clean, _published, _source_url, validate_output as validate_search_output


MAX_HTML = 1024 * 1024
MAX_SOURCES = 3
CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 5.0
TOTAL_BUDGET = 15.0
MAX_REDIRECTS = 2
_DNS_SLOT = threading.BoundedSemaphore(1)
_SPECIAL_NETWORKS = tuple(map(ipaddress.ip_network, (
    "192.0.0.0/24", "192.88.99.0/24", "168.63.129.16/32",
    "64:ff9b::/96", "64:ff9b:1::/48", "2001::/23",
)))


def validate_url(url: str) -> tuple[str, str]:
    source = _source_url(url)
    if source is None:
        raise ToolInputError("The selected source is not a supported public HTTPS URL.")
    parsed = urlsplit(url)
    host = source[1]
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ToolInputError("Direct IP-address sources cannot be read.")
    if (parsed.scheme != "https" or parsed.port not in {None, 443} or parsed.fragment
            or host.endswith((".local", ".localhost", ".internal", ".lan", ".home", ".test", ".invalid"))):
        raise ToolInputError("Reading requires a public HTTPS hostname on port 443, without credentials or fragments.")
    return source


def _resolve(host: str) -> list:
    # A stalled OS resolver cannot accumulate an unbounded number of waiting threads.
    if not _DNS_SLOT.acquire(blocking=False):
        raise ToolExecutionError("A previous DNS lookup is still pending. No connection was made.")
    result = queue.Queue(maxsize=1)

    def lookup():
        try:
            result.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP))
        except Exception:
            result.put(None)
        finally:
            _DNS_SLOT.release()

    threading.Thread(target=lookup, daemon=True, name="aika-source-dns").start()
    try:
        addresses = result.get(timeout=bounded_timeout(CONNECT_TIMEOUT))
    except queue.Empty:
        raise ToolExecutionError("Source DNS lookup timed out. No connection was made.") from None
    if not addresses or len(addresses) > 64:
        raise ToolExecutionError("Source DNS lookup failed or returned an unsupported address set.")
    for family, kind, protocol, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        if (family not in {socket.AF_INET, socket.AF_INET6} or kind != socket.SOCK_STREAM
                or protocol != socket.IPPROTO_TCP or address[1] != 443 or not ip.is_global
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified
                or any(ip in network for network in _SPECIAL_NETWORKS if ip.version == network.version)
                or (isinstance(ip, ipaddress.IPv6Address) and (ip.ipv4_mapped or ip.sixtofour or ip.teredo))):
            raise ToolExecutionError("Source DNS includes a nonpublic or unsupported address. No connection was made.")
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        family, kind, protocol, _, address = _resolve(self.host)[0]
        remaining = getattr(self, "deadline", float("inf")) - monotonic()
        if remaining <= 0:
            raise ToolExecutionError("Source retrieval exceeded its total-operation budget.")
        raw = socket.socket(family, kind, protocol)
        self.sock = raw
        try:
            raw.settimeout(min(CONNECT_TIMEOUT, remaining))
            # sockaddr contains a validated numeric IP; this call does not resolve the hostname again.
            raw.connect(address)
            peer = raw.getpeername()
            if ipaddress.ip_address(peer[0]) != ipaddress.ip_address(address[0]) or peer[1] != 443:
                raise WebFailure("Source connected address did not match the validated destination.", "retrieval", "peer_mismatch")
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            self.sock = None
            raise


def _open_connection(host: str):
    return _PinnedHTTPSConnection(host, port=443, timeout=CONNECT_TIMEOUT, context=ssl.create_default_context())


def redirect_target(current: str, location: str, host: str) -> str:
    if not isinstance(location, str) or not 1 <= len(location) <= 2048 or any(not c.isprintable() or c.isspace() for c in location):
        raise WebFailure("Source redirect has a missing or invalid location.", "retrieval", "redirect_location")
    target = urljoin(current, location)
    try:
        canonical, target_host = validate_url(target)
    except ToolInputError:
        raise WebFailure("Source redirect destination is not a supported public HTTPS URL.", "retrieval", "redirect_destination") from None
    if target_host != host:
        raise WebFailure("Cross-host source redirects are unsupported. No redirected destination was fetched.", "retrieval", "cross_host_redirect")
    return canonical


def fetch_html(url: str, *, redirects: list[str] | None = None, redaction_key: str = "") -> bytes:
    current, host = validate_url(url)
    deadline = monotonic() + bounded_timeout(TOTAL_BUDGET)
    chain = [current]
    connection = None
    connected_socket = None

    def interrupt():
        sock = connected_socket if connected_socket is not None else (connection.sock if connection is not None else None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    timer = threading.Timer(TOTAL_BUDGET, interrupt)
    timer.daemon = True
    timer.start()
    try:
        for hop in range(MAX_REDIRECTS + 1):
            validate_url(current)
            if redaction_key and redaction_key in unquote(current):
                raise WebFailure("Source URL contains a configured credential; no request was made.", "retrieval", "credential_url")
            if monotonic() >= deadline:
                raise ToolExecutionError("Source retrieval exceeded its total-operation budget.")
            parsed = urlsplit(current)
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection = _open_connection(host)
            connection.deadline = deadline
            connected_socket = None
            try:
                connection.connect()
                connected_socket = connection.sock
                if monotonic() >= deadline:
                    raise ToolExecutionError("Source retrieval exceeded its total-operation budget.")
                connection.auto_open = 0
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise ToolExecutionError("Source retrieval exceeded its total-operation budget.")
                connection.sock.settimeout(min(READ_TIMEOUT, remaining))
                connection.request("GET", path, headers={"Accept": "text/html", "Accept-Encoding": "identity",
                                                        "User-Agent": "AIKA/2 SourceReader", "Connection": "close"})
                with connection.getresponse() as response:
                    if 300 <= response.status < 400:
                        if response.status not in {301, 302, 303, 307, 308}:
                            raise WebFailure("Source redirect status is unsupported.", "retrieval", "redirect_status")
                        if hop == MAX_REDIRECTS:
                            raise WebFailure("Source exceeds the two-redirect limit.", "retrieval", "redirect_limit")
                        target = redirect_target(current, response.getheader("Location"), host)
                        if target in chain:
                            raise WebFailure("Source redirect loop detected.", "retrieval", "redirect_loop")
                        chain.append(target)
                        current = target
                        # Do not download redirect bodies or transfer cookies/authorization to the next hop.
                        continue
                    if response.status != 200:
                        raise WebFailure(f"Source returned HTTP {response.status}; access restrictions were not bypassed.", "retrieval", "http_status")
                    if response.getheader("Content-Type", "").split(";", 1)[0].strip().lower() != "text/html":
                        raise ToolExecutionError("Source content type is unsupported; only HTML pages can be read.")
                    if response.getheader("Content-Encoding", "identity").strip().lower() != "identity":
                        raise ToolExecutionError("Encoded source responses are unsupported; no decompression was attempted.")
                    if response.getheader("Content-Disposition"):
                        raise ToolExecutionError("Source file downloads are unsupported.")
                    length = response.getheader("Content-Length")
                    transfer = response.getheader("Transfer-Encoding")
                    if transfer is not None and (transfer.strip().lower() != "chunked" or length is not None):
                        raise ToolExecutionError("Source returned unsupported or ambiguous transfer framing.")
                    if length is not None and (not length.isdecimal() or len(length) > 10 or int(length) > MAX_HTML):
                        raise ToolExecutionError("Source response exceeds the HTML size limit or has an invalid size header.")
                    content = bytearray()
                    while True:
                        if monotonic() >= deadline:
                            raise ToolExecutionError("Source retrieval exceeded its total-operation budget.")
                        chunk = response.read1(min(8192, MAX_HTML + 1 - len(content)))
                        if not chunk:
                            break
                        content.extend(chunk)
                        if len(content) > MAX_HTML:
                            raise ToolExecutionError("Source response exceeds the HTML size limit.")
                    if monotonic() >= deadline:
                        raise ToolExecutionError("Source retrieval exceeded its total-operation budget.")
                    if length is not None and len(content) != int(length):
                        raise ToolExecutionError("The source response was incomplete; no partial document was accepted.")
                    if redirects is not None:
                        redirects[:] = chain
                    return bytes(content)
            finally:
                connection.close()
        raise ToolExecutionError("Source redirect handling failed closed.")
    except ssl.SSLError:
        raise WebFailure("Source TLS verification or negotiation failed. No insecure retry was made.", "retrieval", "tls") from None
    except TimeoutError:
        raise WebFailure("Source connection or read timed out. No retry was made.", "retrieval", "timeout") from None
    except (OSError, http.client.HTTPException, UnicodeError, ValueError) as exc:
        if isinstance(exc, ToolExecutionError):
            raise
        raise WebFailure("Source retrieval failed because of a network or HTTP error. No retry was made.", "retrieval", "network") from None
    finally:
        timer.cancel()


class WebReader:
    def __init__(self, enabled: bool = False, network_enabled: bool = False, redaction_key: str = ""):
        self.enabled = enabled
        self.network_enabled = network_enabled
        self._key = redaction_key
        self.clear()

    def clear(self):
        self._sources: dict[int, str] = {}
        self.evidence: dict[int, SourceEvidence] = {}

    def select_search(self, data: dict):
        validate_search_output(data)
        self.clear()
        self._sources = {number: json.dumps(source, sort_keys=True) for number, source in enumerate(data["results"], 1)}

    def read(self, source_number: int) -> dict:
        if self.enabled is not True or self.network_enabled is not True:
            raise ToolExecutionError("Web reading is disabled. Enable AIKA_WEB_SEARCH_ENABLED and AIKA_WEB_READING_ENABLED explicitly.", status=ToolStatus.UNAVAILABLE)
        if source_number not in self._sources:
            raise ToolExecutionError("Select a result from a successful search in this active conversation first; use /web, then /read <number>.")
        if source_number in self.evidence:
            return asdict(self.evidence[source_number])
        if len(self.evidence) >= MAX_SOURCES:
            raise ToolExecutionError("Three sources have already been read. Start another search to choose a new source set.")
        selected = json.loads(self._sources[source_number])
        try:
            validate_url(selected["url"])
        except ToolInputError as exc:
            raise ToolExecutionError(str(exc)) from None
        chain = [selected["url"]]
        html = fetch_html(selected["url"], redirects=chain, redaction_key=self._key)
        item = extract_evidence(html, selected, source_number, self._key)
        return asdict(replace(item, fetched_url=chain[-1], redirect_chain=tuple(chain)))


def read_arguments(arguments: dict) -> dict:
    if set(arguments) != {"source_number"} or type(arguments["source_number"]) is not int or not 1 <= arguments["source_number"] <= 5:
        raise ToolInputError("Use /read <result-number>, from 1 through 5. Arbitrary URLs are unsupported.")
    return arguments


def read_output(data: dict) -> dict:
    evidence = SourceEvidence(**data)
    stamp = datetime.fromisoformat(evidence.retrieved_at)
    original = json.loads(evidence.selected_source_json)
    if (not re.fullmatch(r"source-[1-5]", evidence.source_id) or evidence.extraction_status != "success"
            or not isinstance(evidence.content, str) or not 1 <= len(evidence.content) <= MAX_TEXT
            or any(not char.isprintable() and char != "\n" for char in evidence.content)
            or type(evidence.truncated) is not bool
            or stamp.tzinfo is None or stamp.utcoffset() is None
            or not isinstance(original, dict) or original.get("url") != evidence.requested_url
            or original.get("domain") != evidence.domain or original.get("provider") not in {"ddgs", "tavily"}
            or (evidence.title is not None and (not isinstance(evidence.title, str) or not evidence.title or _clean(evidence.title, 200) != evidence.title))
            or (evidence.published_at is not None and _published(evidence.published_at) != evidence.published_at)):
        raise ValueError("Invalid source evidence.")
    chain = evidence.redirect_chain or (evidence.requested_url,)
    if (not isinstance(chain, tuple) or not 1 <= len(chain) <= MAX_REDIRECTS + 1
            or chain[0] != evidence.requested_url or chain[-1] != evidence.fetched_url or len(set(chain)) != len(chain)
            or any(validate_url(hop)[1] != evidence.domain for hop in chain)
            or evidence.extraction_method not in {"trafilatura", "html_fallback"}):
        raise ValueError("Invalid redirect or extraction provenance.")
    if validate_url(evidence.fetched_url)[1] != evidence.domain:
        raise ValueError("Invalid source domain.")
    return data


def web_read_tool(reader: WebReader) -> ToolDefinition:
    def handle(arguments):
        try:
            return reader.read(**arguments)
        except WebFailure:
            raise
        except ToolExecutionError as exc:
            raise WebFailure(str(exc), "retrieval", "controlled_failure", status=exc.status) from None
    return ToolDefinition("web.read", "Read one explicitly selected search result as bounded public HTTPS evidence.",
                          read_arguments, read_output, Permission.READ_ONLY, handle)
