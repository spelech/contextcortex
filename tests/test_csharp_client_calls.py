"""find_api_callers: C# client calls whose URL is an interpolated string or a variable set on an earlier line."""

from app.services.chunking.api_client_calls import extract_client_calls
from app.services.chunking.api_route_extractor import match_route_and_call

RUN_CLIENT = '''
public async Task<string> RunAssistantAsync(Guid assistantEntityId, Guid? assistantInstanceId)
{
    var json = JsonSerializer.Serialize(request, JsonOptions);
    using var content = new StringContent(json, Encoding.UTF8, "application/json");

    string url = assistantInstanceId.HasValue
        ? $"api/v2/Assistants/run/instance/{assistantInstanceId.Value}"
        : $"api/v2/Assistants/run/{assistantEntityId}";

    using var httpRequest = new HttpRequestMessage(HttpMethod.Post, url) { Content = content };
    httpRequest.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("text/event-stream"));
    using var response = await _httpClient.SendAsync(httpRequest, cancellationToken);
}
'''


def _calls(source: str, language: str = "c_sharp"):
    lines = source.splitlines()
    return [(c.http_method, c.url_pattern, c.line_number) for c in extract_client_calls(lines, "client", "Client.cs", [], language)]


def test_url_variable_with_conditional_gives_both_routes():
    calls = _calls(RUN_CLIENT)
    assert [(m, u) for m, u, _ in calls] == [
        ("POST", "/api/v2/Assistants/run/instance/{assistantInstanceId.Value}"),
        ("POST", "/api/v2/Assistants/run/{assistantEntityId}"),
    ]
    assert {line for _, _, line in calls} == {11}
    assert match_route_and_call("api/v{version}/assistants/run/{eid}", calls[1][1])
    assert match_route_and_call("api/v{version}/assistants/run/instance/{instanceId}", calls[0][1])


def test_interpolated_literal_and_custom_client_name():
    source = '''
    var item = await _apiClient.GetFromJsonAsync<ItemDto>($"api/items/{id}", ct);
    await _apiClient.DeleteAsync("api/items/" + id);
    var req = new HttpRequestMessage(new HttpMethod("PATCH"), $"api/items/{id}/state");
    '''
    assert [(m, u) for m, u, _ in _calls(source)] == [
        ("GET", "/api/items/{id}"),
        ("DELETE", "/api/items/{id}"),
        ("PATCH", "/api/items/{id}/state"),
    ]


def test_variables_without_a_url_are_ignored():
    source = '''
    string name = "report";
    var request = new HttpRequestMessage(HttpMethod.Get, name);
    var response = await _httpClient.PostAsync(requestUri, content);
    '''
    assert _calls(source) == []


def test_csharp_rules_do_not_apply_to_other_languages():
    assert _calls(RUN_CLIENT, language="python") == []
