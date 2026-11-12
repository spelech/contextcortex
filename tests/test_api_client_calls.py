"""Tests for HTTP client call extraction, including project-specific JS/TS request helpers with template literals."""

from app.services.chunking.api_route_extractor import extract_api_routes_and_calls, match_route_and_call


def _calls(code: str, filepath: str = "client/src/api/client.ts"):
    _, calls = extract_api_routes_and_calls(code, filepath, repo="web")
    return [(c.http_method, c.url_pattern, c.line_number) for c in calls]


def test_get_json_helper_with_encoded_template_parameter_matches_the_route():
    code = "export const analysis = (cmf: string) =>\n  getJson(`/api/accounts/${encodeURIComponent(cmf)}/analysis`, { signal })\n"
    calls = _calls(code)
    assert calls == [("GET", "/api/accounts/{encodeURIComponent(cmf)}/analysis", 2)]
    assert match_route_and_call("/api/accounts/{cmf}/analysis", calls[0][1])


def test_helper_name_and_method_option_set_the_http_method():
    code = "\n".join([
        "postJson('/api/batches', body)",
        "apiClient.put<Item>(`/api/items/${id}`, item)",
        "request('/api/items/7', {",
        "  method: 'DELETE',",
        "})",
        "http.patch(\"https://svc.example.com/v1/users/1\", patch)",
    ])
    assert _calls(code) == [
        ("POST", "/api/batches", 1),
        ("PUT", "/api/items/{id}", 2),
        ("DELETE", "/api/items/7", 3),
        ("PATCH", "https://svc.example.com/v1/users/1", 6),
    ]


def test_navigation_logging_and_non_http_calls_are_not_client_calls():
    code = "\n".join([
        "navigate('/accounts')",
        "router.push(`/accounts/${id}`)",
        "console.log('/api/items failed')",
        "t('/api/label')",
        "getJson('/')",
        "path.join('/api', 'items')",
    ])
    assert _calls(code) == []


def test_helper_rule_applies_only_to_javascript_and_typescript():
    assert _calls("data = getJson('/api/items')\n", filepath="tools/report.py") == []


def test_fetch_and_axios_calls_still_extracted():
    code = "fetch('/api/orders', { method: 'POST' })\naxios.get(`/api/orders/${id}`)\n"
    assert _calls(code, filepath="web/orders.js") == [("POST", "/api/orders", 1), ("GET", "/api/orders/{id}", 2)]
