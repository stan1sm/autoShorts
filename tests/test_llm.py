import pytest

from shorts.llm import LLMError, extract_json


def test_plain_json():
    assert extract_json('[{"a": 1}]') == [{"a": 1}]


def test_fenced_json():
    text = 'Here you go:\n```json\n[{"start": 1.0, "end": 2.0}]\n```\nEnjoy!'
    assert extract_json(text) == [{"start": 1.0, "end": 2.0}]


def test_json_embedded_in_prose():
    text = 'I selected these clips: [{"start": 10, "end": 40}] based on the hooks.'
    assert extract_json(text) == [{"start": 10, "end": 40}]


def test_object_embedded_in_prose():
    text = 'Metadata: {"title": "T", "hashtags": {"youtube": ["#shorts"]}} done.'
    assert extract_json(text)["title"] == "T"


def test_no_json_raises():
    with pytest.raises(LLMError):
        extract_json("Sorry, I cannot help with that.")
