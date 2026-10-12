# Browser accessibility-tree tool (Playwright) for weak Chrome tasks

## Problem

Hybrid/desktop Chrome tasks are weak when Windows-MCP exposes little page structure (titles/coordinates without labels). Models guess clicks.

## Proposal

An optional tool that attaches Playwright to the owner's Chrome (or launches a controlled browser) and returns a compact **accessibility tree** (roles, names, values) for the active tab — not a screenshot-first path.

## Would it fix weak Chrome tasks?

**Likely yes for form fills, labeled buttons, and navigation** — a11y names are what humans and assistive tech use. **No** for canvas/custom widgets without a11y, CAPTCHAs, or pixel-perfect games.

## Constraints

- Owner opt-in; never auto-launch a browser with an open profile without consent.
- SSRF / navigation policy: block private IP navigations (Stage V3).
- Prefer read-only tree dump first; click/type go through existing approval risk tiers.
- Playwright already has a py3.14 Windows wheel check from Stage E — still do not add until an owner asks for the feature.

## Recommendation

Prototype as a confirm-tier tool behind `FRIDAY_BROWSER_A11Y=true`, measure on the Chrome subset of the hybrid bench before changing defaults.
