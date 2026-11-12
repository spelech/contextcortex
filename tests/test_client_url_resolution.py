"""find_api_callers: client URLs built from same-file constants, URL variables, wrappers, and bases that cannot be resolved."""

import pytest

from app.services.chunking.api_client_calls import extract_client_calls
from app.services.chunking.api_route_extractor import match_route_and_call
from app.services.chunking.client_url_resolution import expand_constants, js_variable_urls, string_constants

PUBLISH_ROUTE = "api/v{version}/assistants/{id}/publish"

TS_SERVICE = """\
import sendHttpRequest from "./httpTransport";
import { ASSISTANT_HUB_API_BASE_URL_WITH_HOST } from "./httpTransport";
const ASSISTANT_HUB_API_VERSION_BASE_URL = `${ASSISTANT_HUB_API_BASE_URL_WITH_HOST}/v2`;

export const api = {
  publishAssistantInstance: async (instanceId: string, notes: string) => {
    const url = `${ASSISTANT_HUB_API_VERSION_BASE_URL}/Assistants/${instanceId}/publish`;
    const response = await sendHttpRequest(url, {
      method: "POST",
      body: JSON.stringify(notes),
      headers: { "Content-Type": "application/json" },
    });
    return response.json();
  },
};
"""

TS_SEED = """\
async function publishAssistant(baseUrl: string, instanceId: string) {
  const url = `${baseUrl}/api/v2/Assistants/${instanceId}/publish`;
  const resp = await fetch(url, { method: "POST" });
}
"""

CS_CLIENT = """\
public class AssistantsClient
{
    private const string Base = "api/v2/Assistants";

    public Task<AssistantInstanceDTO> GetDetails(bool latestOnly, CancellationToken ct)
    {
        string uri = $"{Base}/details" + AssistantHubHttpCore.BuildQuery(("latestOnly", latestOnly));
        return _core.SendAsync<AssistantInstanceDTO>(HttpMethod.Get, uri, null, ct);
    }

    public Task<DraftCreationResultDTO<AssistantInstanceDTO>> CreateDraft(AssistantInstanceDTO assistant, CancellationToken ct)
        => _core.SendAsync<DraftCreationResultDTO<AssistantInstanceDTO>>(HttpMethod.Post, Base, assistant, ct);

    public Task<PublishInstanceResultDTO<AssistantInstanceDTO>> PublishInstanceAsync(Guid id, string note, CancellationToken ct = default)
        => _core.SendAsync<PublishInstanceResultDTO<AssistantInstanceDTO>>(HttpMethod.Post, $"{Base}/{id}/publish", note, ct);
}
"""


def _calls(source: str, language: str):
    return [(c.http_method, c.url_pattern) for c in extract_client_calls(source.splitlines(), "client", "f", [], language)]


def test_constants_are_collected_and_expanded():
    ts_consts = string_constants(TS_SERVICE.splitlines(), "typescript")
    assert ts_consts["ASSISTANT_HUB_API_VERSION_BASE_URL"] == "${ASSISTANT_HUB_API_BASE_URL_WITH_HOST}/v2"
    assert expand_constants("${ASSISTANT_HUB_API_VERSION_BASE_URL}/Assistants/${id}", ts_consts, "typescript") == (
        "${ASSISTANT_HUB_API_BASE_URL_WITH_HOST}/v2/Assistants/${id}"
    )
    cs_consts = string_constants(CS_CLIENT.splitlines(), "c_sharp")
    assert cs_consts == {"Base": "api/v2/Assistants"}
    assert expand_constants("{Base}/{id}/publish", cs_consts, "c_sharp") == "api/v2/Assistants/{id}/publish"


def test_js_url_variable_is_resolved_and_ignores_content_types():
    lines = TS_SERVICE.splitlines()
    call_line = next(i for i, line in enumerate(lines, start=1) if "sendHttpRequest(url" in line)
    assert js_variable_urls("url", lines, call_line) == ["${ASSISTANT_HUB_API_VERSION_BASE_URL}/Assistants/${instanceId}/publish"]
    assert _calls('const t = "application/json";\nawait sendHttpRequest(t);\n', "typescript") == []


def test_ts_service_call_through_a_url_variable_and_an_imported_base():
    calls = _calls(TS_SERVICE, "typescript")
    assert calls == [("POST", "/{ASSISTANT_HUB_API_BASE_URL_WITH_HOST}/v2/Assistants/{instanceId}/publish")]
    assert match_route_and_call(PUBLISH_ROUTE, calls[0][1])


def test_fetch_with_a_url_variable_and_a_base_parameter():
    calls = _calls(TS_SEED, "typescript")
    assert calls == [("POST", "/{baseUrl}/api/v2/Assistants/{instanceId}/publish")]
    assert match_route_and_call(PUBLISH_ROUTE, calls[0][1])


def test_csharp_wrapper_with_http_method_and_a_const_base():
    calls = _calls(CS_CLIENT, "c_sharp")
    assert ("POST", "/api/v2/Assistants/{id}/publish") in calls
    assert ("POST", "/api/v2/Assistants") in calls
    # `+ AssistantHubHttpCore.BuildQuery(...)` is a query string, not a path segment.
    assert ("GET", "/api/v2/Assistants/details") in calls
    assert [u for _, u in calls if match_route_and_call(PUBLISH_ROUTE, u)] == ["/api/v2/Assistants/{id}/publish"]


@pytest.mark.parametrize("call_url, expected", [
    ("/{API_HOST}/v2/Assistants/{instanceId}/publish", True),
    ("/{baseUrl}/api/v2/assistants/{x}/publish", True),
    ("https://hub.example.com/api/v2/Assistants/7/publish", True),
    ("/{API_HOST}/v2/Assistants/entity/{eid}", False),  # a client parameter never fills a literal route segment
    ("/{API_HOST}/v2/Tools/{id}/publish", False),
    ("/{base}/{id}/publish", False),  # fewer than two literal segments after the base
    ("/{base}/publish", False),
])
def test_base_relative_matching(call_url, expected):
    assert match_route_and_call(PUBLISH_ROUTE, call_url) is expected
