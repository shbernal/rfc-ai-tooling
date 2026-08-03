# Verifying that Claude Desktop actually called the tools

Claude Desktop is the client this MCP server exists for: its chat has no shell,
so the server is the only surface that reaches it. That makes one question worth
being able to answer precisely — **did the model call the tools, or did it
answer from its own training data and only look like it did?**

Connection is not use. Desktop will show the server connected, list its tools,
and never invoke them, and the answer on screen looks the same either way. This
file records where the evidence actually lives, because the obvious place does
not have it.

## Do not look in the per-server MCP log

`~/.config/Claude/logs/mcp-server-rfc.log` and `~/.config/Claude/logs/mcp.log`
record the **handshake only** — `initialize`, `tools/list`, `prompts/list`,
`resources/list`, and the transport closing. On the build tested below they
carry **no `tools/call` entry even when tool calls demonstrably happened**.

```bash
grep -c 'tools/call' ~/.config/Claude/logs/mcp-server-rfc.log   # 0, and proves nothing
```

Treating that zero as "the model bluffed" is a false negative. It was one on
2026-08-03: the count was 0 while the transcript held two successful calls.

What these logs *are* good for: confirming which build of the server Desktop
resolved. The startup line settles whether you are testing the published package
or a local checkout.

```
mcp-server-rfc 0.1.0 starting on stdio
```

## Look in main.log for the call

`~/.config/Claude/logs/main.log` records tool permission traffic by tool name:

```bash
grep -E 'tool permission request|permission response|Connected to rfc' \
  ~/.config/Claude/logs/main.log
```

```
[LocalMcpServerManager] Connected to rfc (3 tools)
Emitted tool permission request <uuid> for mcp__rfc__list_sections in session local_<id>
Received permission response for <uuid>: always (tool: mcp__rfc__list_sections)
Emitted tool permission request <uuid> for mcp__rfc__get_rfc in session local_<id>
Received permission response for <uuid>: always (tool: mcp__rfc__get_rfc)
```

This proves a call was *attempted and approved*. It does not show arguments or
results, and a tool already approved with `always` may not re-emit a request on
later calls — so absence here is weaker evidence than presence.

**Timestamps are local time in `main.log` and UTC in the MCP logs.** The same
event appears as `14:34:54` in one and `12:34:54.817Z` in the other. Comparing
them without accounting for that makes concurrent events look unrelated.

## Look in the session transcript for the result

This is the good source: full tool inputs *and* outputs, so behaviour claims can
be checked against what actually came back rather than what the model said about
it. Grab the newest transcript:

```bash
find ~/.config/Claude/local-agent-mode-sessions \
  -path '*/.claude/projects/*' -name '*.jsonl' -printf '%T@ %p\n' |
  sort -rn | head -5 | cut -d' ' -f2-
```

Then extract the calls, results and the model's own text:

```bash
python3 - "$TRANSCRIPT" <<'EOF'
import json, sys
for line in open(sys.argv[1]):
    try: d = json.loads(line)
    except ValueError: continue
    content = (d.get("message") or {}).get("content")
    if not isinstance(content, list): continue
    for b in content:
        if b.get("type") == "tool_use" and "rfc" in b.get("name", ""):
            print(f">>> {b['name']} {json.dumps(b.get('input'))}")
        elif b.get("type") == "tool_result":
            c = b.get("content")
            s = c if isinstance(c, str) else " ".join(
                x.get("text", "") for x in c if isinstance(x, dict))
            print(f"<<< err={b.get('is_error')}\n{s[:800]}")
        elif b.get("type") == "text" and b.get("text", "").strip():
            print(f"--- {d.get('type')}: {b['text'][:800]}")
EOF
```

A tool result with real RFC text and `err=None` is proof the server answered.
The model's adjacent `text` block is what shows whether it *relayed* what it got
— which is the actual question for the obsolescence banner and for the no-mirror
refusal, both of which are only useful if they survive into the reply.

## Which Desktop surface you are testing

Desktop hosts more than one agent. The distinction matters, because it decides
whether the result says anything about the audience this server exists for.

- **Plain Desktop chat** — no shell. This is the surface the MCP server is for,
  and the only one where a passing result justifies the package.
- **Claude Code in Desktop** — logged as `LocalAgentModeSessions` / `HostLoop` /
  `cli.js` in `main.log`, with a session id like `local_<uuid>` and a working
  directory of its own. This surface *has* a shell, so the skill also works
  there. It still exercises the same stdio plumbing, so it proves routing — just
  not the no-shell case.
- **Cowork / claude.ai on the web** — runs in Anthropic's cloud with no route to
  a process on this machine. The stdio server can never work there; that is what
  HTTP mode is for. A "connector keeps dropping" report from those clients is a
  category error, not a bug in this package.

Read the session id in `main.log` before recording which surface a result came
from.

## Result log

| Date | Version | Surface | Result |
|---|---|---|---|
| 2026-08-02 | 0.1.0 (PyPI) | Desktop, unknown | Handshake only. Connected, 3 tools listed, no calls. |
| 2026-08-03 | 0.1.0 (PyPI) | Claude Code in Desktop (`local_722995b1…`) | `list_sections` and `get_rfc` on RFC 1020 both returned real content, no error. Obsolescence banner (`!! OBSOLETED BY: RFC 1062, 1117, 1166`) reached the model and was relayed in the reply. |

Tested against `claude-desktop-bin` 1.20186.9-1, an unofficial Linux repackage
of the official `.deb`, with `uvx mcp-server-rfc` resolved from `/usr/bin/uvx`.
The repackage is a real variable: do not generalise a Linux result to macOS or
Windows without re-running it there.

## Reading a mirror side-effect correctly

`read_document` caches every fetched RFC into the mirror directory, creating it
if absent, and `ensure_index` writes or touches the index there. So a successful
read **does** create `~/.local/share/rfc-ai-tooling`, and that is correct
behaviour, not a leak.

What must never happen is an *automatic full sync* — 512 MB pulled from a
volunteer-run mirror without the user asking. The lazy-index assertion is
narrower than it first looks: connecting and listing tools must create nothing.
Reading is allowed to cache.

If you need to observe the no-mirror error path, rename the mirror rather than
deleting it, and delete the small directory the probes recreate before restoring
— otherwise `mv ~/.local/share/rfc-ai-tooling{.bak,}` moves the backup *inside*
the new directory instead of replacing it.

```bash
mv ~/.local/share/rfc-ai-tooling{,.bak}
# ... run the probes ...
rm -rf ~/.local/share/rfc-ai-tooling
mv ~/.local/share/rfc-ai-tooling{.bak,}
```
