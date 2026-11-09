"""Real local-model smoke checks. These validate execution and result shape, not accuracy."""

import pytest

from backend.app.classifiers import classify_text, classifier_readiness


EXAMPLES = [
    pytest.param(
        "My family and I visited the park on Saturday and enjoyed a picnic.",
        id="ordinary-benign-text",
    ),
    pytest.param(
        "I will hurt you tomorrow.",
        id="explicit-threatening-language",
    ),
    pytest.param(
        "You are an awful person and nobody likes you.",
        id="toxic-or-abusive-language",
    ),
    pytest.param(
        "In the horror story, the abandoned station was stained with blood after the creature passed through.",
        id="disturbing-fiction-may-be-missed",
    ),
]


@pytest.mark.parametrize("text", EXAMPLES)
def test_available_local_model_runs_documented_text_examples(text):
    readiness = classifier_readiness()["text"]
    if readiness not in {"available_unloaded", "ready"}:
        pytest.skip(f"Local text classifier is not ready: {readiness}")

    result = classify_text(text)

    assert result["modality"] == "text"
    assert result["supported_categories"] == ["threat_language"]
    assert set(result["scores"]) == {"threat_language"}
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["scores"]["threat_language"] == result["confidence"]
