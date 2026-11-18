import httpx
import pytest


@pytest.fixture
def ollama_model(request):
    return getattr(request, "param", "qwen3:4b")


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path, ollama_model):
    for key in (
        "AIKA_APP_NAME", "AIKA_VERSION", "AIKA_LOG_LEVEL", "AIKA_RUNTIME_URL",
        "AIKA_OLLAMA_URL", "AIKA_MODEL_TIMEOUT", "AIKA_CONTEXT_TURNS",
        "AIKA_OLLAMA_THINK", "AIKA_CONTEXT_DEBUG", "AIKA_CONTEXT_DEBUG_PUBLIC",
        "AIKA_DISABLED_APPS",
        "AIKA_TAVILY_API_KEY", "AIKA_WEB_SEARCH_ENABLED",
        "AIKA_WEB_SEARCH_PROVIDER", "AIKA_WEB_SEARCH_FALLBACK_ENABLED", "AIKA_WEB_SEARCH_FALLBACK_PROVIDER", "DDGS_PROXY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("src.config.DOTENV_PATH", tmp_path / ".env")
    # Child CLI processes must also stay offline when a developer enables local search.
    monkeypatch.setenv("AIKA_WEB_SEARCH_ENABLED", "off")
    monkeypatch.setenv("AIKA_WEB_READING_ENABLED", "off")
    monkeypatch.setenv("AIKA_WEB_DEBUG", "off")
    monkeypatch.setenv("AIKA_RESEARCH_TIMEOUT", "180")
    monkeypatch.setenv("AIKA_AGENT_TIMEOUT", "180")
    monkeypatch.setenv("AIKA_TIMEZONE", "local")
    monkeypatch.setenv("AIKA_TAVILY_API_KEY", "")
    monkeypatch.setenv("AIKA_WEB_SEARCH_PROVIDER", "auto")
    monkeypatch.setenv("AIKA_WEB_SEARCH_FALLBACK_ENABLED", "off")
    monkeypatch.setenv("AIKA_WEB_SEARCH_FALLBACK_PROVIDER", "tavily")
    monkeypatch.setenv("AIKA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AIKA_OLLAMA_MODEL", ollama_model)


@pytest.fixture(autouse=True)
def prevent_real_app_launches(monkeypatch):
    def forbidden(_app):
        raise AssertionError("Automated tests must mock application launching.")
    monkeypatch.setattr("src.capabilities.applications._launch", forbidden)


@pytest.fixture(autouse=True)
def prevent_real_system_measurements(monkeypatch):
    def forbidden():
        raise AssertionError("Automated tests must mock system measurement APIs.")
    monkeypatch.setattr("src.capabilities.system_info.initialize_measurements", forbidden)


@pytest.fixture(autouse=True)
def prevent_live_search_requests(monkeypatch):
    def forbidden(_httpx):
        raise AssertionError("Automated tests must mock Tavily HTTP requests.")
    monkeypatch.setattr("src.capabilities.web_search._open_client", forbidden)
    monkeypatch.setattr("src.capabilities.web_search._open_ddgs", lambda: forbidden(None))
    monkeypatch.setattr("src.capabilities.web_reader._open_connection", lambda _: forbidden(None))
    monkeypatch.setattr("src.capabilities.web_reader.socket.getaddrinfo", lambda *args, **kwargs: forbidden(None))


@pytest.fixture
def mock_ollama(monkeypatch, ollama_model):
    def installed_models(request):
        assert request.method == "GET"
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": ollama_model}]})

    def use_transport(handler=installed_models):
        def request(method, url, *, trust_env, follow_redirects, **kwargs):
            assert trust_env is False
            assert follow_redirects is False
            with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
                return client.request(method, url, **kwargs)

        monkeypatch.setattr(httpx, "request", request)

    return use_transport
