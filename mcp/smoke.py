#!/usr/bin/env python3
"""Drive a real stdio JSON-RPC session against mcp-server-rfc and assert on it.

This exists because CI proves the *repository* works and proves nothing about
the *published artifact*. "The server starts on stdio" is a weak claim — a
server that dies on its first tools/call passes it — so this runs the four
messages a client actually sends and checks what comes back.

Stdlib only, and deliberately a single file, so it can be piped into a bare
container that has never held this repo:

    docker run --rm -i python:3.13-slim bash -s <<'EOF'
    pip install -q uv
    python3 - <<'PY'
    ...contents of this file...
    PY
    EOF

By default it tests whatever `uvx mcp-server-rfc` resolves, which is the
published wheel. Pass a different command to test a working tree instead:

    PYTHONPATH=mcp/src python3 mcp/smoke.py -- python3 -m mcp_server_rfc.server

Pass --expect-version, always. "Whatever `uvx` resolves" is not the release you
just cut until PyPI's simple index has propagated, and until then it is the
*previous* one — against which every check below passes, reporting success for
a version nobody was testing. That happened on the 0.2.4 release. Without the
flag this script cannot tell you which version it proved, and says so.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

DEFAULT_COMMAND = ["uvx", "mcp-server-rfc"]
EXPECTED_TOOLS = {"search_rfcs", "list_sections", "get_rfc"}
# RFC 2616 is the whole argument for the project: obsolete since 2014, and
# still the first thing most models reach for.
OBSOLETE_RFC = 2616
SUCCESSORS = [7230, 7231, 7232, 7233, 7234, 7235]
TIMEOUT = 120


def protocol_version() -> str:
    """Whatever the installed SDK advertises, falling back to a known-good one.

    The version string is incidental; the four-message sequence is not.
    """
    try:
        from mcp.types import LATEST_PROTOCOL_VERSION

        return LATEST_PROTOCOL_VERSION
    except Exception:
        return "2025-06-18"


def mirror_path() -> Path:
    env = os.environ.get("RFC_MIRROR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".local" / "share" / "rfc-ai-tooling"


class Client:
    """The smallest thing that can hold a stdio JSON-RPC conversation."""

    def __init__(self, command: list[str]):
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.stderr: list[str] = []
        # stderr is the server's log channel; drained on a thread so a chatty
        # server cannot deadlock on a full pipe.
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self) -> None:
        assert self.proc.stderr
        for line in self.proc.stderr:
            self.stderr.append(line.rstrip())

    def send(self, message: dict) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def request(self, id_: int, method: str, params: dict | None = None) -> dict:
        self.send({"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})
        return self._await(id_, method)

    def _await(self, id_: int, method: str) -> dict:
        """Read until the response with this id; skip notifications in between."""
        assert self.proc.stdout
        while True:
            line = self.proc.stdout.readline()
            if not line:
                log = "\n".join(self.stderr[-20:])
                raise SystemExit(
                    f"server closed stdout while waiting for {method}\n--- stderr ---\n{log}"
                )
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                # Anything unparseable on stdout is itself a bug: stdout is the
                # protocol channel and nothing else may write to it.
                raise SystemExit(
                    f"non-JSON on stdout (stdout is the protocol channel): {line!r}"
                ) from None
            if message.get("id") == id_:
                if "error" in message:
                    raise SystemExit(f"{method} returned an error: {message['error']}")
                return message.get("result", {})

    def close(self) -> None:
        try:
            assert self.proc.stdin
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"{'ok  ' if condition else 'FAIL'} {label}")
    if not condition and detail:
        print(f"       {detail}")
    return condition


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="*",
        default=DEFAULT_COMMAND,
        help="server command (default: uvx mcp-server-rfc)",
    )
    parser.add_argument(
        "--expect-version",
        metavar="VERSION",
        help="fail unless serverInfo reports this version; without it the run "
        "cannot say which version it proved",
    )
    args = parser.parse_args()
    command = args.command or DEFAULT_COMMAND

    mirror = mirror_path()
    mirror_existed = mirror.exists()
    version = protocol_version()
    print(f"server:   {' '.join(command)}")
    print(f"protocol: {version}")
    print(f"mirror:   {mirror} ({'exists' if mirror_existed else 'absent'})\n")

    client = Client(command)
    passed = True
    try:
        init = client.request(
            1,
            "initialize",
            {
                "protocolVersion": version,
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"},
            },
        )
        server_info = init.get("serverInfo", {})
        passed &= check(
            "initialize handshake",
            bool(server_info),
            f"no serverInfo in {init}",
        )
        print(f"       serverInfo: {server_info}")

        # Before anything else, because everything else is worthless if this is
        # the wrong build. A freshly published version is not resolvable until
        # the simple index propagates, and `uvx` quietly serves the previous
        # release in the meantime.
        reported = server_info.get("version", "")
        if args.expect_version:
            passed &= check(
                f"serverInfo reports {args.expect_version}",
                reported == args.expect_version,
                f"resolved {reported or 'no version'} instead. Every check below "
                "passes against the previous release, so a PASS here would be a "
                "report about a version you are not shipping.",
            )
        else:
            print("note which version this proves is unknown (pass --expect-version)")

        client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        listed = client.request(2, "tools/list")
        names = {tool["name"] for tool in listed.get("tools", [])}
        passed &= check(
            f"tools/list is exactly {sorted(EXPECTED_TOOLS)}",
            names == EXPECTED_TOOLS,
            f"got {sorted(names)}",
        )

        # The lazy index is a design commitment, not an optimization: a client
        # that connects and asks nothing must not parse or download anything.
        passed &= check(
            "connecting and listing tools created no mirror",
            mirror.exists() == mirror_existed,
            f"{mirror} appeared during handshake",
        )

        called = client.request(
            3,
            "tools/call",
            {"name": "get_rfc", "arguments": {"number": OBSOLETE_RFC, "section": "13"}},
        )
        passed &= check(
            f"get_rfc {OBSOLETE_RFC} did not error",
            not called.get("isError"),
            json.dumps(called)[:400],
        )
        blob = json.dumps(called)
        passed &= check(
            f"get_rfc {OBSOLETE_RFC} carries the obsolescence banner",
            "OBSOLETED BY" in blob,
            "the feature that justifies the project is not reaching the model",
        )
        passed &= check(
            f"banner names {SUCCESSORS[0]}-{SUCCESSORS[-1]}",
            all(str(n) in blob for n in SUCCESSORS),
            f"missing: {[n for n in SUCCESSORS if str(n) not in blob]}",
        )
        content = called.get("content") or []
        text = next((c.get("text", "") for c in content if c.get("type") == "text"), "")
        passed &= check("get_rfc returned content", bool(text), "empty content block")
    finally:
        client.close()

    print()
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
