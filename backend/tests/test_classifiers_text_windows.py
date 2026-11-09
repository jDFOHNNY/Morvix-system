from types import SimpleNamespace

import pytest


torch = pytest.importorskip("torch")


class WindowTokenizer:
    def __init__(self):
        self.call = None

    def __call__(self, text, **kwargs):
        self.call = (text, kwargs)
        return {
            "input_ids": torch.tensor([[101, 10, 102], [101, 20, 102]]),
            "attention_mask": torch.ones((2, 3), dtype=torch.long),
            "overflow_to_sample_mapping": torch.tensor([0, 0]),
        }


class WindowModel:
    config = SimpleNamespace(id2label={
        0: "toxic", 1: "severe_toxic", 2: "obscene", 3: "threat", 4: "insult", 5: "identity_hate",
    })

    def __init__(self):
        self.inputs = None

    def __call__(self, **kwargs):
        self.inputs = kwargs
        # The first window is benign; the second contains the relevant sentence.
        return SimpleNamespace(logits=torch.tensor([
            [-4.0, -5.0, -5.0, -4.0, -5.0, -5.0],
            [-4.0, -5.0, -5.0, 1.0, -5.0, -5.0],
        ]))


def test_text_classifier_uses_overlapping_windows_and_max_score_across_page(monkeypatch):
    from backend.app import classifiers

    tokenizer = WindowTokenizer()
    model = WindowModel()
    monkeypatch.setattr(classifiers, "_load_text_model", lambda: (model, tokenizer))

    result = classifiers.classify_text("  first long page section. Later, a relevant threat sentence.  ")

    called_text, options = tokenizer.call
    assert called_text == "first long page section. Later, a relevant threat sentence."
    assert options["max_length"] == 512
    assert options["padding"] is True
    assert options["stride"] == 64
    assert options["return_overflowing_tokens"] is True
    assert "overflow_to_sample_mapping" not in model.inputs
    assert result["supported_categories"] == ["threat_language"]
    assert result["category"] == "threat_language"
    assert result["confidence"] == pytest.approx(torch.sigmoid(torch.tensor(1.0)).item())

