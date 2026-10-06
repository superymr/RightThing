import json

import pytest

from app.config import Settings
from app.llm.base import LLMError, LLMResponse
from app.llm.compact import expand_profile
from app.llm.extractor import Extractor


TEXT = "熟练使用Python、SQL。掌握Docker者优先。"


def compact():
    return {"ev": ["熟练使用Python、SQL。", "掌握Docker者优先。"],
            "lang": [["Python", True, 0], ["SQL", True, 0]],
            "hard": [["Docker", False, 1]], "domain": [], "soft": [],
            "edu": "", "exp": "", "level": "", "major": [], "cert": [], "pref": [1]}


def test_shared_evidence_and_required_flags_survive_expansion():
    data = expand_profile(compact(), TEXT)
    assert data["programming_languages"][0]["evidence"] == data["programming_languages"][1]["evidence"]
    assert data["hard_skills"][0]["required"] is False
    assert data["preferred_qualifications"] == ["掌握Docker者优先。"]
    assert data["summary"] == ""
    assert len(json.dumps(compact(), ensure_ascii=False)) < len(json.dumps(data, ensure_ascii=False))


@pytest.mark.parametrize("bad_index", [-1, 2, True, "0"])
def test_invalid_indices_rejected(bad_index):
    data = compact()
    data["lang"][0][2] = bad_index
    with pytest.raises(LLMError):
        expand_profile(data, TEXT)


def test_invented_evidence_rejected():
    data = compact()
    data["ev"][0] = "精通Rust"
    with pytest.raises(LLMError):
        expand_profile(data, TEXT)


def test_extractor_restores_profile_and_preserves_usage():
    class Provider:
        name = "openai"
        model_name = "test"

        def complete_json(self, **kwargs):
            assert "ev" in kwargs["json_schema"]["properties"]
            return LLMResponse(data=compact(), model="test", token_in=100, token_out=40)

    outcome = Extractor(Provider(), Settings()).extract_profile(job_title="开发工程师", company="", jd_text=TEXT)
    assert outcome.status == "ok"
    assert outcome.profile.job_title == "开发工程师"
    assert {item.name for item in outcome.profile.all_skills()} == {"Python", "SQL", "Docker"}
    assert outcome.token_in == 100 and outcome.token_out == 40


@pytest.mark.parametrize("url,thinking,expected", [
    ("https://api.deepseek.com/v1", False, {"type": "disabled"}),
    ("https://api.deepseek.com/v1", True, {"type": "enabled"}),
    ("https://custom.example/v1", False, None),
])
def test_deepseek_thinking_switch_is_vendor_scoped(url, thinking, expected):
    from app.llm.openai_provider import OpenAICompatibleProvider
    provider = OpenAICompatibleProvider(Settings(llm_base_url=url, llm_api_key="test",
                                                llm_deepseek_thinking=thinking))
    requests = []

    def post(payload):
        requests.append(payload)
        return {"choices": [{"message": {"content": "{}"}}]}

    provider._post_with_retry = post
    provider.complete_json(system="test", user="test", schema_name="test")
    assert requests[0].get("thinking") == expected
