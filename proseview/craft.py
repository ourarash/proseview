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
#: it for one review. Every review card shares it; Bird by Bird keeps its single
#: assignment.
DEFAULT_MAX_FINDINGS = 5
MAX_FINDINGS_LIMIT = 8


def findings_limit_rule(limit: int, noun: str = "findings") -> str:
    """The cap as the prompt states it, with the reminder that fewer is fine."""
    return (f"Give at most {limit} {noun} across the entire selection, most important first. "
            f"{limit} is a limit, not a target: give fewer, or none, when fewer earn their place, "
            "and do not split one problem into several.")


# What works goes in its own short list, so the writer can tell it apart from
# the changes in Revision priorities.
KEEP_RULE = """When the prose supports it, add a **Keep** heading with one or two bullets, each
naming an effective moment to preserve: the exact quote, its source-line link,
and a one-sentence reason. Keep items are not revision priorities. Omit the heading when
nothing clearly earns it."""

# Manuscript prose is hard-wrapped, so a phrase search misses a phrase that
# breaks across lines; a review once built its top finding on such a miss.
# Linking facts from other scenes lets the citation check verify them.
ABSENCE_RULE = """Manuscript lines wrap mid-sentence. Before claiming that something never
appears, is never set up, or first appears in a given passage, search for one
distinctive word rather than a phrase, and read the hits. If you cannot check
the rest of the manuscript, say the claim is unverified and do not build a
finding on it. When a finding relies on a fact or line from another scene, link
that line, such as [02-btc.md · Line 159](manuscript/ch08/02-btc.md#L159), and
quote it exactly if you quote it; if you cannot find it, say the fact is
unverified."""


_SHARED_REVIEW_RULES = """Review the supplied prose in light of the writer's purpose, genre, draft stage,
voice, viewpoint, and known facts. Do not modify files. Story notes, frontmatter,
beat maps, titles, and TODO/NOTE annotations are background, not narrative prose.
Distinguish what the prose establishes from interpretation and writer-supplied
background. Say what context is missing when it limits a judgment. An intentional
exception still needs to work for the reader; do not manufacture faults or praise.

For a critique, first show **Book-based reading** using the fields below. Keep
each observation short and anchor the important turns in supplied source lines.
Describe what is present, not just what is missing. Mark an uncertain reading as
uncertain. This is an application of selected book principles, not the author's
personal judgment of the scene.

Then list what to preserve under **Keep** (see below).
Give **Revision priorities**: up to {max_findings} distinct, significant findings across
the selection, ordered by reader impact. Zero necessary revisions is acceptable.
Do not score the draft or require a quota of problems.

For each finding, quote the smallest complete passage that demonstrates the
problem exactly and link to its supplied repository-relative path and numbered
line, such as [scene.md · Line 18](manuscript/scene.md#L18). Do not abbreviate
evidence with ellipses. For a missing beat, cite a nearby existing passage or
insertion point and explain the absence. Never invent an original passage or
source location. Unnumbered adjacent excerpts are background, not line citations.

Explain the reader effect and the particular book principle that matters here.
Give a direct, specific revision action, followed by a concrete demonstration:
for a sentence-level issue, a short optional replacement; for a structural issue,
a specific possible beat or before/after sequence. A generic instruction such as
"clarify the stakes" is not sufficient. Label new story material as a possibility,
preserve established facts and voice, and avoid a polished scene rewrite.

Do not repeat one problem as several findings. Do not assume that unselected
scenes fail to bridge an apparent gap. Narrow findings to an explicitly selected
focus; other principles can supply context without becoming additional audits.
""" + "\n" + KEEP_RULE + "\n\n" + ABSENCE_RULE + "\n"

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

_PLAN_CHECK_OFF = """Frontmatter, beat maps, and TODO/NOTE annotations may record plans the writer
has since changed. Use them only to understand the scene's intent. Do not report
a beat, setup, or dependency they mention that the draft has not reached, and do
not base a finding on one. Judge the drafted prose on the page. Writer-supplied
story context for this review is current: let it inform character, viewpoint,
genre, and purpose, without turning the review into a check of planned beats."""


def craft_review_contract(
    action_id: str, *, focus: str = "", scene_count: int = 1, check_plan: bool = False,
    lane_ids: list[str] | None = None, max_findings: int = DEFAULT_MAX_FINDINGS,
) -> str:
    guide = craft_guide(action_id)
    if not guide:
        return ""
    selected = craft_focus(action_id, focus) if focus else None
    selected_lanes = ([lane for lane in guide["lanes"] if lane["id"] in lane_ids]
                      if lane_ids is not None else [selected] if selected else guide["lanes"])
    narrowed = len(selected_lanes) < len(guide["lanes"])
    selected_names = [lane_name(lane) for lane in selected_lanes]
    lines = [
        "Shared craft review requirements:",
        _SHARED_REVIEW_RULES.replace("{max_findings}", str(max_findings)),
        _PLAN_CHECK_ON if check_plan else _PLAN_CHECK_OFF,
    ]
    if action_id == "craft_lamott":
        lines.append(
            "For Bird by Bird, replace the formal Book-based reading, scene table, and "
            "Revision priorities with the skill's brief keep/one-assignment format. "
            "Give one concrete starting point, not a critique checklist or mandatory replacement."
        )
    else:
        lines.append(findings_limit_rule(max_findings, "revision priorities"))
        reading_fields = selected_names if narrowed else guide["analysisFields"]
        lines.append("Single-scene reading: one brief line for each applicable field: "
                     + "; ".join(reading_fields) + ".")
        if scene_count > 1:
            scene_fields = selected_names + ["Reader effect"] if narrowed else guide["sceneFields"]
            lines.append(
                "Multi-scene reading: show one compact table row for EVERY selected scene, "
                "in supplied order, before the revision priorities. Use these columns: Scene | "
                + " | ".join(scene_fields) + ". Include a useful source-line link "
                "in each row. Describe the actual development or mark insufficient evidence; "
                "a row is coverage, not a demand for a defect. Follow with at most "
                f"{max_findings} selection-wide priorities, rather than findings per scene."
            )
    lines.extend([
        "Feedback lane labels:",
        "For every suggested fix or next drafting assignment, use a short heading followed by "
        "a brief **Lane: <name> — <why this finding belongs here>** line. Include this line "
        "for numbered and unnumbered suggestions, regardless of the section heading. "
        "Use the exact names below, never checklist item numbers. "
        "For a finding spanning two topics, use **Lanes:** with at most two names and a brief connection.",
        "Available review lanes:\n" + "\n".join("- " + lane_name(lane) for lane in guide["lanes"]),
    ])
    if selected:
        lines.append("Selected focus: " + lane_name(selected) + " — " + selected["title"])
    if lane_ids is not None:
        lines.append("Selected review lanes: " + "; ".join(selected_names) + ". "
                     "Only these lanes may produce findings. Other principles are context, not additional audits.")
    lines.append("Selected book principles and what to look for:")
    for lane in selected_lanes:
        lines.append(f"{lane_name(lane)} — {lane['title']}\nPrinciple: {lane['summary']}\nLook for: {lane['spot']}")
    return "\n\n".join(lines)
