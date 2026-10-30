# Security policy

## Reporting a vulnerability

Report it privately through
[GitHub's advisory form](https://github.com/shbernal/rfc-ai-tooling/security/advisories/new),
not in a public issue. Include the affected version, which surface it is in (the
skill or `mcp-server-rfc`) and the steps to reproduce it.

## Supported versions

Fixes go into the next release, on the latest version only. Published versions
are never replaced, so upgrading is how a fix reaches you.

## Scope

In scope is this repository: `core/rfc.py`, the MCP server, the skill, the
Docker image and the release workflows.

The HTTP mode has no authentication by design. A deployment that leaves it
exposed is covered in the README and is not a vulnerability on its own.
