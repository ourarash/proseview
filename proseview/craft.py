"""The book principles shared by craft guides and review instructions."""

from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def craft_guides() -> list[dict]:
    return json.loads((Path(__file__).parent / "skills" / "craft_guides.json").read_text(encoding="utf-8"))


def craft_guide(action_id: str) -> dict | None:
    return next((guide for guide in craft_guides() if guide["id"] == action_id), None)


def lane_name(lane: dict) -> str:
    return lane["tab"].split(". ", 1)[-1]


def craft_focus(action_id: str, value: str) -> dict | None:
    guide = craft_guide(action_id)
    return next((lane for lane in (guide or {}).get("lanes", [])
                 if value in (lane["id"], lane["title"], lane_name(lane))), None)


#: How many revision priorities a review may give, unless the writer changes
#: it in Customize. Every review card shares it; Bird by Bird keeps its single
#: assignment. A whole chapter can need more than a scene, hence the high limit.
DEFAULT_MAX_FINDINGS = 5
MAX_FINDINGS_LIMIT = 20


# What works goes in its own short list, so the writer can tell it apart from
# the changes. The writer turns it on in Customize.
KEEP_RULE = """When the prose supports it, add a **Keep** heading with one or two bullets, each
naming an effective moment to preserve: the exact quote, its source-line link,
and a one-sentence reason. Keep items are not revision priorities. Omit the heading when
nothing clearly earns it."""


def selected_lanes_instruction(selected_lanes: list[dict], *, total_lanes: int, open_critique: bool = False) -> str:
    """How strictly the review sticks to the chosen lanes."""
    names = "; ".join(lane_name(lane) for lane in selected_lanes)
    if not open_critique:
        return f"Selected lanes: {names}. Stay within the selected lanes."
    if len(selected_lanes) < total_lanes:
        noun = "lane" if len(selected_lanes) == 1 else "lanes"
        return f"Focus on the selected {noun}: {names}."
    return (f"Selected lanes: {names}. "
            "Draw freely on the whole editorial lens.")


# Reviews got short and minor when this contract was 1,400 words of rules, most
# of them about what not to report. It now keeps only what the app depends on
# (the quote/link order, the Lane line, the rewrite lead-in) and one line for
# each failure a real review showed. Add a rule back only when a test of real
# reviews shows it is missing. See plans/review-prompt-rewrite.md.
def review_contract(
    *, scene_count: int, max_findings: int, check_plan: bool, include_keep: bool,
    goal: str = "", item: str = "finding", open_critique: bool = False,
) -> str:
    """The shared goal, output format, and rules for a review card."""
    scope = "scene" if scene_count == 1 else "selection of scenes"
    if open_critique:
        goal_line = (
            goal or "Give feedback on what would most improve this {scope}, "
            "using the editorial lens (up to {max_findings} distinct points, most important first)."
        ).format(scope=scope, max_findings=max_findings, item=item)
        lines = [
            "The review guide below supplies the editorial lens; these instructions govern only "
            "citations, the cap, and edits.",
            goal_line,
            "Choose whatever issues matter most—structural, dramatic, character, or prose—without "
            "collapsing distinct points together.",
            "Anchor observations with exact quotes (italic blockquote, no ellipses) and a clickable link "
            "on the line below each quote, such as [03-the-harbor.md · Line 18](manuscript/ch02/03-the-harbor.md#L18), "
            "using each quoted scene's own file name and path.",
            "Whenever a change can be written directly as prose, give a drop-in **Before:** / **After:** rewrite: "
            "**Before:** (italic blockquote + link below) and **After:** Replace "
            "[03-the-harbor.md · Line 18](manuscript/ch02/03-the-harbor.md#L18): "
            "(or **After:** Insert after [03-the-harbor.md · Line 18](manuscript/ch02/03-the-harbor.md#L18):) "
            "as a plain blockquote; for larger cuts or restructures, a brief direction is fine.",
        ]
        voice_rule = "Suggested text keeps the scene's voice. Mark any new story fact as a possibility."
    else:
        goal = (goal or "Find the changes that would most improve this {scope}, and write each {item} "
                "as text the writer can paste.").format(scope=scope, item=item)
        lines = [
            "The review guide supplies the editorial lens; this format governs the output. "
            "If they conflict on format, follow this format.",
            f"{goal} Give up to {max_findings}, most important first.",
        ]
        subject = "the scene" if scene_count == 1 else "the selection"
        lines.append(f"Within the selected review and lanes, start with improvements to how {subject} works as a whole"
                     + (", including development across scenes" if scene_count > 1 else "")
                     + ". Then address individual passages and wording.")
        lines.append(
            f"For each {item}, under a short numbered heading:\n"
            "- A **Lane: <name> — <why>** line, using a selected lane's exact name "
            "(**Lanes:** with two names if it spans both).\n"
            "- **Before:** on its own line, then the passage quoted exactly in an italic blockquote, "
            "with its link on the line below it, such as [03-the-harbor.md · Line 18](manuscript/ch02/03-the-harbor.md#L18).\n"
            "- **Why:** the specific weakness or missed opportunity, and what the change improves for the reader.\n"
            "- **After:** Replace [03-the-harbor.md · Line 18](manuscript/ch02/03-the-harbor.md#L18):, then the replacement "
            "in a plain blockquote, ready to paste. For an addition, cite the insertion point instead: "
            "**After:** Insert after [03-the-harbor.md · Line 18](manuscript/ch02/03-the-harbor.md#L18):. For a cut, show how "
            "the passage reads after it.\n"
            "Every link uses the quoted scene's own file name and path; the file name above is only an example."
        )
        lines.append("When a finding requires changes in several places, group the connected edits under one finding "
                     "and write out each replacement or insertion.")
        voice_rule = "Replacement text keeps the scene's voice. Mark any new story fact as a possibility."
    rules = [
        "Quote exactly, with no ellipses, and link every quote, including lines from other scenes.",
        "Manuscript lines wrap mid-sentence. Before saying something never appears or is never set up, "
        "search for one distinctive word. If you can't check, say so.",
        voice_rule,
    ]
    if not check_plan:
        rules.append("Notes and frontmatter are background, not requirements.")
    if not include_keep:
        rules.append("Don't add a section on what works.")
    rules.append("Do not modify files.")
    lines.append("Rules:\n" + "\n".join("- " + rule for rule in rules))
    if check_plan:
        lines.append(_PLAN_CHECK_ON)
    if include_keep:
        lines.append(KEEP_RULE)
    return "\n\n".join(lines)


# Notes outlive the plans they record. Comparing the draft with them is a pass
# the writer asks for; otherwise a stale note would lead every review.
_PLAN_CHECK_ON = """The writer asked to check the draft against their notes. When relevant notes,
frontmatter, or annotations explicitly identify a planned beat, setup, or
downstream dependency, compare that stated intention with the supplied draft,
including any setup this scene is meant to establish for a later one. Check whether the prose already
fulfills the note before flagging an omission. Report a confirmed omission in a
brief **Writer-plan gap** note, even if it is not one of the revision priorities,
and cite a nearby existing passage or insertion point. If a priority already
covers the gap, point to it in one line instead of repeating it. If the later
scene is not supplied, label its dependency as writer-reported, not verified.
Assess this gap against the writer's stated plan; a note is not a rule from the book."""

def craft_review_contract(
    action_id: str, *, focus: str = "", scene_count: int = 1, check_plan: bool = False,
    lane_ids: list[str] | None = None, max_findings: int = DEFAULT_MAX_FINDINGS,
    include_keep: bool = False, open_critique: bool = False,
) -> str:
    guide = craft_guide(action_id)
    if not guide:
        return ""
    selected = craft_focus(action_id, focus) if focus else None
    selected_lanes = ([lane for lane in guide["lanes"] if lane["id"] in lane_ids]
                      if lane_ids is not None else [selected] if selected else guide["lanes"])
    if action_id == "craft_lamott":
        # Its keep/one-assignment format is the review itself.
        lines = [
            "Use the skill's brief keep/one-assignment format. Give one concrete starting point, "
            "not a critique checklist or mandatory replacement. Label it with a "
            "**Lane: <name> — <why>** line, using a selected lane's exact name.",
            KEEP_RULE,
            "Rules:\n- Quote exactly, with no ellipses, and link every quote, such as "
            "[03-the-harbor.md · Line 18](manuscript/ch02/03-the-harbor.md#L18).\n"
            "- Mark any new story fact as a possibility.\n"
            + ("" if check_plan else "- Notes and frontmatter are background, not requirements.\n")
            + "- Do not modify files.",
        ]
        if check_plan:
            lines.append(_PLAN_CHECK_ON)
        lines.append(selected_lanes_instruction(selected_lanes, total_lanes=len(guide["lanes"])))
    else:
        lines = [review_contract(scene_count=scene_count, max_findings=max_findings,
                                 check_plan=check_plan, include_keep=include_keep,
                                 open_critique=open_critique)]
        lines.append(selected_lanes_instruction(selected_lanes, total_lanes=len(guide["lanes"]),
                                                open_critique=open_critique))
    if open_critique and action_id != "craft_lamott":
        lines.append(f"Selected book: {guide['book']} ({guide['author']})\nSelected lane briefs:")
        for lane in selected_lanes:
            lines.append(f"- {lane_name(lane)} — {lane['brief']}")
    else:
        lines.append(f"Selected book: {guide['book']}\nSelected book principles:")
        for lane in selected_lanes:
            lines.append(f"- {lane_name(lane)} — {lane['brief']}\nPrinciple: {lane['summary']}")
    return "\n\n".join(lines)
