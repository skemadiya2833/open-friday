import base64
import sys
import types

from friday.models import cloud


def test_gemini_uses_google_genai_client(monkeypatch):
    seen = {}

    class Part:
        @staticmethod
        def from_bytes(*, data, mime_type):
            seen["bytes"], seen["mime"] = data, mime_type
            return ("part", mime_type)

    class Models:
        def generate_content(self, *, model, contents):
            seen["model"], seen["contents"] = model, contents
            return types.SimpleNamespace(text=' {"steps": []} ')

    class Client:
        def __init__(self, api_key=None):
            seen["key"] = api_key
            self.models = Models()

    g = types.ModuleType("google")
    genai = types.ModuleType("google.genai")
    genai.Client = Client
    gtypes = types.ModuleType("google.genai.types")
    gtypes.Part = Part
    genai.types = gtypes
    g.genai = genai
    monkeypatch.setitem(sys.modules, "google", g)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", gtypes)
    monkeypatch.setattr(cloud, "GEMINI_API_KEY", "k")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    out = cloud._call_gemini("hi", base64.b64encode(b"img").decode())
    assert out == '{"steps": []}'
    assert seen["bytes"] == b"img" and seen["key"] == "k"
    assert seen["model"] == "gemini-2.5-flash" and seen["contents"][-1] == "hi"


def test_gemini_failure_returns_none(monkeypatch):
    monkeypatch.setitem(sys.modules, "google", None)   # import fails
    assert cloud._call_gemini("hi", None) is None
