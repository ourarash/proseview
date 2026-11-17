"""Shared scene-review guides and the model instructions for selected lanes."""

from functools import lru_cache
import json
from pathlib import Path

from .craft import (
    _PLAN_CHECK_OFF, _PLAN_CHECK_ON, ABSENCE_RULE, DEFAULT_MAX_FINDINGS, KEEP_RULE, MAX_FINDINGS_LIMIT,
    craft_guide, craft_review_contract, findings_limit_rule, lane_name,
)


@lru_cache(maxsize=1)
def review_guides() -> list[dict]:
    return json.loads((Path(__file__).parent / "skills" / "review_guides.json").read_text(encoding="utf-8"))


def review_guide(action_id: str) -> dict | None:
    return craft_guide(action_id) or next((guide for guide in review_guides() if guide["id"] == action_id), None)


def selected_review_lanes(action_id: str, lane_ids: list[str] | None, *, focus: str = "") -> list[dict]:
    """Use canonical IDs, preserving guide order. Legacy single focus still works."""
    guide = review_guide(action_id)
    if not guide:
        raise ValueError("this action has no review lanes")
    if lane_ids is None:
        if focus:
            return [lane for lane in guide["lanes"] if focus in (lane["id"], lane["title"], lane_name(lane))] or guide["lanes"]
        return guide["lanes"]
    if (not isinstance(lane_ids, list) or not lane_ids or len(lane_ids) > 12
            or any(not isinstance(value, str) for value in lane_ids)):
        raise ValueError("review lanes must be a non-empty list of at most 12 lane IDs")
    known = {lane["id"] for lane in guide["lanes"]}
    if any(value not in known for value in lane_ids):
        raise ValueError("unknown lane for this review type")
    return [lane for lane in guide["lanes"] if lane["id"] in lane_ids]


def comedy_review_options(
    styles: list[str] | None = None, goal: str | None = None, *, goals: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    guide = review_guide("comedy_review")
    assert guide is not None
    styles = [] if styles is None else styles
    known = {style["id"] for style in guide["styles"]}
    if (not isinstance(styles, list) or len(styles) > len(known)
            or any(not isinstance(value, str) or value not in known for value in styles)):
        raise ValueError("comedy styles must be a list of the available style IDs")
    if goals is not None and goal is not None:
        raise ValueError("use comedy_goals or the legacy comedy_goal, not both")
    # By default a comedy review both tunes the humor already there and looks
    # for new comic chances; the writer can narrow it to either in Customize.
    goal_ids = (["strengthen", "explore"] if goal is None else [goal]) if goals is None else goals
    known_goals = {item["id"] for item in guide["goals"]}
    if (not isinstance(goal_ids, list) or not goal_ids or len(goal_ids) > len(known_goals)
            or any(not isinstance(value, str) or value not in known_goals for value in goal_ids)):
        raise ValueError("comedy goals must be a non-empty list of the available goal IDs")
    return ([style for style in guide["styles"] if style["id"] in styles],
            [item for item in guide["goals"] if item["id"] in goal_ids])


def scene_review_contract(
    action_id: str, lanes: list[dict], *, scene_count: int, check_plan: bool,
    comedy_styles: list[str] | None = None, comedy_goal: str | None = None,
    comedy_goals: list[str] | None = None, max_findings: int = DEFAULT_MAX_FINDINGS,
) -> str:
    if action_id.startswith("craft_"):
        return craft_review_contract(action_id, focus=lanes[0]["id"] if len(lanes) == 1 else "",
                                     scene_count=scene_count, check_plan=check_plan,
                                     lane_ids=[lane["id"] for lane in lanes], max_findings=max_findings)
    lines = [
        "Shared scene review requirements:",
        "Review the supplied scenes in order. Do not modify files. Respect the writer's purpose, "
        "voice, viewpoint, genre, and established facts. Frontmatter, beat maps, titles, and TODO/NOTE "
        "annotations are background, not narrative prose. Distinguish the prose from supplied notes "
        "and from your interpretation. Do not invent missing context or assume that unselected scenes "
        "fail to bridge a gap.",
        _PLAN_CHECK_ON if check_plan else _PLAN_CHECK_OFF,
        "Selected review lanes: " + "; ".join(lane_name(lane) for lane in lanes) + ". "
        "Only these lanes may produce suggestions; other topics can inform the reading without becoming extra audits.",
        "For each numbered finding or suggestion, add a brief **Lane: <name> — <why this belongs here>** "
        "line using the selected lane's exact name. Use **Lanes:** with at most two selected names when needed.",
        "Quote the smallest complete original passage exactly in an italicized blockquote. Link it to its "
        "supplied repository-relative file and numbered source line, such as "
        "[scene.md · Line 18](manuscript/scene.md#L18). Numeric prefixes label lines; omit them from quotations. "
        "Do not abbreviate evidence with ellipses or invent a passage or line number. For a missing beat, "
        "cite an existing insertion point. Adjacent excerpts are background, not source-line citations.",
        "Explain the reader effect in plain English. Give a specific revision action and an optional "
        "drop-in replacement in a plain blockquote. For a structural issue, show a concrete possible beat "
        "or before/after sequence. Label new story material as a possibility. 'Clarify the stakes' alone "
        "is not a useful fix. Preserve useful restraint and do not rewrite a whole scene.",
        ABSENCE_RULE,
    ]
    if scene_count > 1:
        lines.append("Before the suggestions, show one compact coverage table row for EVERY selected scene, "
                     "in manuscript order: Scene | Selected-lane reading | Source line. Describe what is "
                     "present or mark insufficient evidence. A row establishes coverage, not a quota of problems.")
    if action_id == "comedy_review":
        styles, goals = comedy_review_options(comedy_styles, comedy_goal, goals=comedy_goals)
        goal_labels = {
            "strengthen": "**Type: Strengthen existing humor**",
            "explore": "**Type: Comic opportunity**",
        }
        goal_types = " or ".join(goal_labels[goal["id"]] for goal in goals)
        lines.extend([
            "Selected comedy review goals: " + "; ".join(goal["label"] for goal in goals) + ". "
            "Apply only the selected goals, with up to " + str(max_findings) + " priorities TOTAL across all selected goals and scenes. "
            "Label each finding " + goal_types + ". "
            + ("Assess existing humor and suggest new opportunities in one combined review. " if len(goals) > 1 else "")
            + "An opportunity is an optional addition, not evidence that the original passage failed.",
            "Comic styles guide how you evaluate the selected lanes; they do not select additional lanes. "
            "When no style is selected, follow the draft's existing register, including any darkness or sarcasm already present.",
            "Begin with a brief Comic reading grounded in supplied lines: the comic idea or perspective, "
            "the recognizable pressure, and the expectation or contrast. Include only aspects relevant to selected lanes. "
            "Separate an interpretation of existing humor from an optional new comic direction.",
            KEEP_RULE,
            "Give up to " + str(max_findings) + " distinct Revision priorities "
            "across the entire selection. For each, identify the technique and explain what the reader expects, "
            "what changes, and the exact words or action affecting that change. Follow with a concrete optional "
            "replacement or beat sequence in the scene's voice, and explain the difference. Remove vague instructions "
            "such as 'make this funnier' or 'heighten the absurdity' unless you demonstrate the actual revision.",
            "Truth + pain is a starting point, not a scale on which more suffering earns more laughs. "
            "Playing it straight, using three beats, adding specific detail, or ending on a punch word are techniques "
            "to judge in context. Do not mechanically impose them. Keep the needed setup, speaker clarity, pauses, "
            "and aftermath. Heighten through consequence or commitment when appropriate, not just louder or darker wording.",
            "For a callback, connect the earlier seed to its changed later use with source links. "
            "If its setup or payoff lies outside the supplied scenes, identify what remains unverified. "
            "Do not invent a missing callback as a defect.",
            "Distinguish the speaker, the target of the joke, and the story's apparent stance. "
            "Explain competing readings when they matter without assuming the writer's beliefs. "
            "Preserve intentional bitterness, discomfort, and emotional stakes. Assess craft and likely reader effects; "
            "do not promise laughter, give numerical funniness scores, or present benign violation as a universal law.",
        ])
        lines.extend("Selected review goal: " + goal["label"] + ". " + goal["prompt"] for goal in goals)
        lines.extend("Selected comic style: " + style["label"] + ". " + style["prompt"] for style in styles)
    elif action_id == "deepen_and_layer":
        lines.append("Offer up to " + str(max_findings) + " useful opportunities across the entire selection, with the biggest "
                     "benefit first. Develop the scene's existing action rather than manufacturing tension, "
                     "extra gestures, or larger stakes. Show enough of each proposed expansion to judge it in context.")
    else:
        lines.append(KEEP_RULE)
        lines.append("Then give up to " + str(max_findings) + " distinct "
                     "revision priorities across the entire selection, ordered by reader impact. Remove abstract "
                     "or marginal notes. Do not force a quota of problems.")
    lines.append(findings_limit_rule(max_findings, "opportunities" if action_id == "deepen_and_layer" else "revision priorities"))
    lines.append("Selected principles and what to look for:")
    for lane in lanes:
        lines.append(f"{lane_name(lane)} — {lane['title']}\nPrinciple: {lane['summary']}\nLook for: {lane['spot']}")
        if action_id == "comedy_review":
            lines.append("Revision approach for " + lane_name(lane) + ": " + lane["fix"])
    return "\n\n".join(lines)
