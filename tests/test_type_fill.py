"""TYPE must never be dropped just because the model put the payload in the wrong JSON field."""

from friday.agent.planner import fill_type_text
from friday.types import ActionStep


def test_from_dict_unwraps_args_and_content():
    s = ActionStep.from_dict({"action": "TYPE", "args": {"text": "print(1)"}})
    assert s.text == "print(1)"
    s = ActionStep.from_dict({"action": "TYPE", "content": "hello friday"})
    assert s.text == "hello friday"


def test_fill_from_extras_and_description():
    s = ActionStep(action="TYPE", extras={"code": "x = 1"})
    assert fill_type_text(s).text == "x = 1"
    s = ActionStep(action="TYPE", description="alpha\nbeta")
    assert fill_type_text(s).text == "alpha\nbeta"


def test_fill_python_objective_does_not_stay_empty():
    s = ActionStep(action="TYPE", description="type the Python code")
    fill_type_text(s, objective="Open Notepad and write a python script")
    assert s.text and "print" in s.text


def test_quoted_text_in_objective():
    s = ActionStep(action="TYPE")
    fill_type_text(s, objective='Open Notepad, type exactly: "hello friday"')
    assert s.text == "hello friday"
