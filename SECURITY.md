# Security

## Supported versions

Security fixes are applied on the default public branch (`main` / `release/clean` when published). Older development branches are not supported.

## Reporting a vulnerability

Email **skemadiya@gmail.com** with a description, steps to reproduce, and impact. Please do not open public issues for undisclosed security bugs.

We aim to acknowledge reports within a few business days. Coordinated disclosure is preferred.

## Scope

Friday is designed for **local, single-user** use on your own PC. Threats we prioritize:

- Unauthorized remote access to the Control Center API
- CSRF / DNS rebinding against loopback
- Tool and MCP abuse (shell, filesystem, desktop control)
- Secret leakage via logs, commits, or crash dumps

Out of scope: other malware already running as the same Windows user (it can invoke loopback APIs).

## Safe defaults

- Bind to loopback until you deliberately configure remote access (`docs/PHONE_SETUP.md`).
- Run `python scripts/pre_push_secrets_check.py` and `python scripts/pre_push_guard.py` before pushing forks.
- Keep `SHELL_TOOLS_ENABLED=false` unless you understand the risk.
- Leave MCP servers disabled until pinned and reviewed in `config/mcp_servers.yaml`.

See `docs/THREAT_MODEL.md` for control-by-control detail.
