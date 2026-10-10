from friday.models.cloud import pick_gemini_model


def test_pick_prefers_newest_stable_flash_and_skips_lite_preview_etc():
    names = ["models/gemini-1.5-flash", "models/gemini-2.5-flash", "models/gemini-2.5-flash-lite", "models/gemini-3.0-flash-preview",
             "models/gemini-2.5-pro", "models/gemini-2.0-flash", "models/gemini-2.5-flash-image", "models/embedding-001"]
    assert pick_gemini_model(names) == "gemini-2.5-flash"
    assert pick_gemini_model(["models/gemini-3.1-flash", "models/gemini-2.5-flash"]) == "gemini-3.1-flash"
    assert pick_gemini_model(["models/gemini-2.5-pro"]) == "gemini-2.5-pro"
    assert pick_gemini_model(["models/gemini-3.0-flash-preview"]) is None


def test_discovery_uses_env_then_listing_then_fallback(monkeypatch):
    import friday.models.cloud as C

    class M:
        def __init__(self, n, acts=("generateContent",)):
            self.name, self.supported_actions = n, list(acts)

    class Client:
        class models:
            @staticmethod
            def list():
                return [M("models/gemini-2.5-flash"), M("models/gemini-9.9-flash", acts=("embedContent",))]

    monkeypatch.setattr(C, "_gemini_model", None)
    monkeypatch.setenv("GEMINI_MODEL", "my-model")
    assert C.discover_gemini_model(Client) == "my-model"
    monkeypatch.delenv("GEMINI_MODEL")
    assert C.discover_gemini_model(Client) == "gemini-2.5-flash"      # 9.9 cannot generateContent
    monkeypatch.setattr(C, "_gemini_model", None)

    class Broken:
        class models:
            @staticmethod
            def list():
                raise RuntimeError("no key")
    assert C.discover_gemini_model(Broken) == "gemini-2.5-flash"
