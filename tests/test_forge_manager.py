import pytest

from core.api_errors import ForgeAPIError, NetworkError
from core.forge_manager import ForgeManager

from tests._http_fixture import StubResponse, StubServer, json_route


def test_list_projects_parses_results():
    table = {
        ("GET", "/api/projects"): StubResponse(
            body={"results": [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}], "next": None}
        )
    }
    with StubServer(json_route(table)) as server:
        manager = ForgeManager(server.url, retry_attempts=1)
        projects = manager.list_projects()
    assert [(p.id, p.name) for p in projects] == [(1, "alpha"), (2, "beta")]


def test_list_projects_follows_next_pagination():
    page2_url = "/api/projects?page=2"

    def router(request):
        if request.path == "/api/projects" and not request.query:
            return StubResponse(
                body={"results": [{"id": 1, "name": "a"}], "next": f"{server.url}{page2_url}"}
            )
        if request.path == "/api/projects" and request.query.get("page") == ["2"]:
            return StubResponse(body={"results": [{"id": 2, "name": "b"}], "next": None})
        return StubResponse(status=404, body={})

    with StubServer(router) as server:
        manager = ForgeManager(server.url, retry_attempts=1)
        projects = manager.list_projects()
    assert [p.id for p in projects] == [1, 2]


def test_basic_auth_header_is_sent():
    captured: dict[str, str] = {}

    def router(request):
        captured.update(request.headers)
        return StubResponse(body={"results": []})

    with StubServer(router) as server:
        manager = ForgeManager(server.url, retry_attempts=1)
        manager.set_basic_auth("alice", "s3cret")
        manager.list_projects()
    assert "authorization" in captured
    assert captured["authorization"].startswith("Basic ")


def test_token_auth_takes_precedence_over_basic():
    captured: dict[str, str] = {}

    def router(request):
        captured.update(request.headers)
        return StubResponse(body={"results": []})

    with StubServer(router) as server:
        manager = ForgeManager(server.url, retry_attempts=1)
        manager.set_basic_auth("alice", "s3cret")
        manager.set_token("tok-xyz")
        manager.list_projects()
    assert captured["authorization"] == "Bearer tok-xyz"


def test_401_raises_forge_api_error_with_status():
    table = {("GET", "/api/projects"): StubResponse(status=401, body={"detail": "denied"})}
    with StubServer(json_route(table)) as server:
        manager = ForgeManager(server.url, retry_attempts=1)
        with pytest.raises(ForgeAPIError) as exc_info:
            manager.list_projects()
    assert exc_info.value.status == 401
    assert exc_info.value.is_auth_error
    assert not exc_info.value.is_retryable


def test_503_is_retryable():
    table = {("GET", "/api/projects"): StubResponse(status=503, body={"err": "x"})}
    with StubServer(json_route(table)) as server:
        manager = ForgeManager(server.url, retry_attempts=1)
        with pytest.raises(ForgeAPIError) as exc_info:
            manager.list_projects()
    assert exc_info.value.is_server_error
    assert exc_info.value.is_retryable


def test_unreachable_host_raises_network_error():
    manager = ForgeManager("http://127.0.0.1:1", retry_attempts=1)  # closed port
    with pytest.raises(NetworkError):
        manager.list_projects()


def test_normalize_base_url_strips_swagger_suffix():
    manager = ForgeManager("https://forge.example.com/api/swagger/")
    assert manager.base_url == "https://forge.example.com"


def test_get_project_returns_dict():
    table = {("GET", "/api/projects/3"): StubResponse(body={"id": 3, "name": "x"})}
    with StubServer(json_route(table)) as server:
        manager = ForgeManager(server.url, retry_attempts=1)
        result = manager.get_project(3)
    assert result == {"id": 3, "name": "x"}


def test_ping_succeeds_when_credentials_valid():
    table = {("GET", "/api/projects"): StubResponse(body={"results": []})}
    with StubServer(json_route(table)) as server:
        manager = ForgeManager(server.url, retry_attempts=1)
        result = manager.ping()
    assert result == {"ok": True}


def test_ping_raises_on_401():
    table = {("GET", "/api/projects"): StubResponse(status=401, body={"detail": "denied"})}
    with StubServer(json_route(table)) as server:
        manager = ForgeManager(server.url, retry_attempts=1)
        with pytest.raises(ForgeAPIError):
            manager.ping()


def test_create_camera_sends_json_payload():
    captured: dict[str, bytes] = {}

    def router(request):
        captured["body"] = request.body
        captured["content-type"] = request.headers.get("content-type", "")
        return StubResponse(status=201, body={"id": 9})

    with StubServer(router) as server:
        manager = ForgeManager(server.url, retry_attempts=1)
        result = manager.create_camera({"name": "Cam Norte"})
    import json as _json

    assert result == {"id": 9}
    assert _json.loads(captured["body"]) == {"name": "Cam Norte"}
    assert captured["content-type"] == "application/json"
