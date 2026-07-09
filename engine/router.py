"""Deprecated — use friday.agent.planner."""
from friday.agent.planner import decide_next_action

def create_high_level_plan(objective: str) -> dict:
    return {"message": "Vision-first adaptive execution (no fixed phase plan).", "phases": []}

def get_next_steps(session, vision):
    # Accept legacy TaskSession-like objects
    from friday.agent.session import AgentSession
    if not isinstance(session, AgentSession):
        adapted = AgentSession(objective=getattr(session, 'objective', ''))
        adapted.history = list(getattr(session, 'history', []))
        adapted.context_summary = getattr(session, 'context_summary', '')
        adapted.iteration = getattr(session, 'iteration', 0)
        session = adapted
    decision = decide_next_action(session, vision)
    steps = [decision.step.to_dict()] if decision.step else []
    return {
        "message": decision.message,
        "observation": decision.observation,
        "steps": steps,
        "needs_knowledge": decision.needs_knowledge,
        "phase_complete": False,
    }
