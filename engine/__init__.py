"""Deprecated compatibility package. Prefer `friday.*` imports."""

from friday.actions.executor import execute_action as execute_step
from friday.agent.planner import decide_next_action as get_next_steps
from friday.agent.session import AgentSession as TaskSession
from friday.vision.feed import LiveScreenFeed

__all__ = [
    "execute_step",
    "get_next_steps",
    "TaskSession",
    "LiveScreenFeed",
]
