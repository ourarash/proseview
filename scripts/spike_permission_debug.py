"""Narrow probe: what does it take to make a tool call reach an approval gate?

Check 3 of the main spike first failed with "can_use_tool never fired". That
has two very different explanations, and they matter: either the model never
attempted the tool (a prompting problem, harmless), or it ran the tool without
asking us (a security problem, because Prosview's approval UI would be
bypassed).

The answer turned out to be the second one. Probes A-D all show Bash running to
completion without the callback firing; probe E shows a PreToolUse hook
catching the same call and enforcing a deny. The SDK itself warns about this:

    CanUseToolShadowedWarning: can_use_tool will not be invoked for: Bash. An
    allowed_tools entry that allows a whole tool auto-approves it before the
    callback is consulted. To gate every tool call, use a PreToolUse hook; or
    narrow the entry so calls fall through to can_use_tool. Allow rules from
    settings files can also shadow the callback but are not visible here.

Keep this script around: it is the regression test for "did our approval gate
quietly stop gating?"
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultDeny,
    ResultMessage,
    ToolUseBlock,
)

SCENE_ROOT = REPO_ROOT / "fixtures" / "demo-repo"


async def probe(label: str, **overrides: Any) -> None:
    asked: list[str] = []
    attempted: list[str] = []

    async def can_use_tool(tool_name: str, tool_input: dict[str, Any], context: Any):
        asked.append(tool_name)
        print(f"    callback fired: {tool_name}")
        print(f"      suggestions: {getattr(context, 'suggestions', None)}")
        print(f"      title: {getattr(context, 'title', None)!r}")
        print(f"      tool_use_id: {getattr(context, 'tool_use_id', None)}")
        return PermissionResultDeny(message="spike: denied")

    opts: dict[str, Any] = {
        "cwd": str(SCENE_ROOT),
        "setting_sources": None,
        "strict_mcp_config": True,
        "mcp_servers": {},
        "can_use_tool": can_use_tool,
        "max_turns": 3,
    }
    opts.update(overrides)

    print(f"\n=== {label} ===")
    print(f"    options: { {k: v for k, v in overrides.items()} }")
    try:
        async with ClaudeSDKClient(options=ClaudeAgentOptions(**opts)) as client:
            await client.query(
                "Run `wc -l manuscript/ch01/01-opening.md` with the Bash tool "
                "and report the number."
            )
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            attempted.append(block.name)
                            print(f"    tool_use seen: {block.name} {str(block.input)[:120]}")
                if isinstance(message, ResultMessage):
                    print(f"    result: {str(getattr(message, 'result', ''))[:200]}")
    except Exception as exc:  # noqa: BLE001
        print(f"    ERROR {type(exc).__name__}: {exc}")

    print(f"    -> attempted={attempted or 'none'}  callback_fired_for={asked or 'none'}")
    if attempted and not asked:
        print("    !! tool ran WITHOUT reaching can_use_tool — approval bypassed")


async def probe_hook() -> None:
    """The SDK's own suggested fix: gate with a PreToolUse hook instead.

    Unlike can_use_tool, a hook is not shadowed by allowed_tools entries or by
    allow rules in the user's settings files.
    """
    from claude_agent_sdk import HookMatcher

    gated: list[str] = []
    attempted: list[str] = []

    async def pre_tool_use(input_data: dict[str, Any], tool_use_id: Any, context: Any):
        tool = input_data.get("tool_name")
        gated.append(tool)
        print(f"    hook fired: {tool} {str(input_data.get('tool_input'))[:100]}")
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "Prosview spike: denied by policy.",
            }
        }

    print("\n=== E: PreToolUse hook ===")
    opts = ClaudeAgentOptions(
        cwd=str(SCENE_ROOT),
        setting_sources=None,
        strict_mcp_config=True,
        mcp_servers={},
        tools=["Bash", "Read"],
        max_turns=3,
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool_use])]},
    )
    try:
        async with ClaudeSDKClient(options=opts) as client:
            await client.query(
                "Run `wc -l manuscript/ch01/01-opening.md` with the Bash tool "
                "and report the number."
            )
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            attempted.append(block.name)
                            print(f"    tool_use seen: {block.name}")
                if isinstance(message, ResultMessage):
                    print(f"    result: {str(getattr(message, 'result', ''))[:200]}")
    except Exception as exc:  # noqa: BLE001
        print(f"    ERROR {type(exc).__name__}: {exc}")

    print(f"    -> attempted={attempted or 'none'}  hook_fired_for={gated or 'none'}")
    if attempted and not gated:
        print("    !! tool ran WITHOUT reaching the hook — approval bypassed")


async def main() -> None:
    # Vary one dimension at a time to find what gates the callback.
    await probe("A: tools list + default mode", tools=["Bash", "Read"], permission_mode="default")
    await probe("B: no tools restriction, default mode", permission_mode="default")
    await probe("C: allowed_tools instead of tools", allowed_tools=["Bash"], permission_mode="default")
    await probe("D: permission_mode=plan", tools=["Bash", "Read"], permission_mode="plan")
    await probe_hook()


if __name__ == "__main__":
    asyncio.run(main())
