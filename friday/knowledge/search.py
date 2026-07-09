"""Knowledge augmentation — search the web when the agent is uncertain."""

from __future__ import annotations

import time
import urllib.parse
import webbrowser

from friday.types import KnowledgeNote


def perform_knowledge_search(query: str) -> KnowledgeNote:
    """
    Open a browser search for the query so the vision loop can read results
    on subsequent observations. Also records a lightweight note now so the
    planner has a callback marker even before reading SERP content.

    The agent's next observe ticks should extract useful facts visually;
    this helper only opens the search surface.
    """
    query = query.strip()
    print(f"[Knowledge] Searching: {query}")

    # Open via the OS default browser: works even when no browser window is
    # open or focused (Ctrl+T into the wrong window silently did nothing).
    url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
    webbrowser.open(url)
    time.sleep(3.0)

    # Leave the tab open for the vision model to read on the next tick.
    # Closing happens later when the model decides the knowledge is sufficient.
    summary = (
        f"Opened a search tab for '{query}'. "
        "Read the visible results on the next observation, extract only what is needed, "
        "then CLOSE_TAB and resume the original task."
    )
    print(f"[Knowledge] {summary}")
    return KnowledgeNote(query=query, summary=summary, source="web_search")
