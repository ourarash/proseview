"""Shared scene-review guides and the model instructions for selected lanes."""

from functools import lru_cache
import json
from pathlib import Path

from .craft import (
    DEFAULT_MAX_FINDINGS, MAX_FINDINGS_LIMIT, craft_guide, craft_review_contract, lane_name, review_contract,
    selected_lanes_instruction,
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


def review_self_check(action_id: str, *, open_critique: bool = False) -> str:
    """The final review check, including when the writer supplies their own guide."""
    if action_id == "craft_lamott":
        questions = [
            "Have I considered the whole selection through the selected review and lanes?",
            "Is the single assignment useful, manageable, and clear about where to start?",
        ]
    elif open_critique:
        questions = [
            "Have I focused on what matters most for this selection?",
            "Did I keep distinct points separate within the configured limit?",
            "Is every quote exact and linked on the line below it, using each scene's own file name and path?",
        ]
    else:
        questions = [
            "Have I considered the whole selection through the selected review and lanes?",
            "Did I avoid duplicate findings—without merging distinct points—and retain worthwhile findings within the configured limit?",
            "Does every finding end in complete, pasteable edits?",
        ]
    return ("Before returning feedback, check silently:\n\n"
            + "\n".join("- " + question for question in questions)
            + "\n\nResolve any gaps before returning. Do not print this checklist.")


def scene_review_contract(
    action_id: str, lanes: list[dict], *, scene_count: int, check_plan: bool,
    comedy_styles: list[str] | None = None, comedy_goal: str | None = None,
    comedy_goals: list[str] | None = None, max_findings: int = DEFAULT_MAX_FINDINGS,
    include_keep: bool = False, open_critique: bool = False,
) -> str:
    if action_id.startswith("craft_"):
        return craft_review_contract(action_id, focus=lanes[0]["id"] if len(lanes) == 1 else "",
                                     scene_count=scene_count, check_plan=check_plan,
                                     lane_ids=[lane["id"] for lane in lanes], max_findings=max_findings,
                                     include_keep=include_keep, open_critique=open_critique)
    shared = {"scene_count": scene_count, "max_findings": max_findings, "check_plan": check_plan,
              "open_critique": open_critique}
    lines: list[str] = []
    if action_id == "comedy_review":
        styles, goals = comedy_review_options(comedy_styles, comedy_goal, goals=comedy_goals)
        goal_labels = {
            "strengthen": "**Type: Strengthen existing humor**",
            "explore": "**Type: Comic opportunity**",
        }
        lines.extend([
            review_contract(
                **shared, include_keep=include_keep,
                goal=(
                    "Give feedback on the comedy in this {scope}—what works, what misses, "
                    "or where the best chances are (up to {max_findings} distinct points, "
                    "most important first)."
                    if open_critique else
                    "Find where the comedy in this {scope} most needs work or has the best new "
                    "chance, and write each {item} as text the writer can paste."
                ),
            ),
            "Selected comedy review goals: " + "; ".join(goal["label"] for goal in goals) + ". "
            "The limit covers all selected goals together. Under each heading, label the finding "
            + " or ".join(goal_labels[goal["id"]] for goal in goals) + ". "
            "An opportunity is an optional addition, not evidence that the passage failed; "
            "cite its insertion point.",
            "Comic styles guide how you judge the selected lanes; they do not select more lanes. "
            "With no style selected, follow the draft's own register.",
        ])
        lines.extend("Selected review goal: " + goal["label"] + ". " + goal["prompt"] for goal in goals)
        lines.extend("Selected comic style: " + style["label"] + ". " + style["prompt"] for style in styles)
    elif action_id == "deepen_and_layer":
        lines.extend([
            # Deepen offers opportunities, not faults, so it has no Keep list or open critique mode.
            review_contract(scene_count=scene_count, max_findings=max_findings, check_plan=check_plan,
                            include_keep=False, item="opportunity",
                            goal="Find the moments in this {scope} that most need deepening, and write "
                                 "each {item} out as an expansion the writer can paste."),
            "Develop the scene's existing action rather than adding tension, gestures, or stakes it doesn't need.",
        ])
    else:
        lines.append(review_contract(**shared, include_keep=include_keep))
    guide = review_guide(action_id) or {}
    total_lanes = len(guide.get("lanes", [])) or len(lanes)
    lines.append(selected_lanes_instruction(
        lanes, total_lanes=total_lanes, open_critique=open_critique and action_id != "deepen_and_layer",
    ))
    sources = {source["id"]: source["label"].replace(" · ", ", ") for source in guide.get("sources", [])}
    rows = []
    for lane in lanes:
        cited = "; ".join(sources[source] for source in lane.get("sources", []) if source in sources)
        rows.append(f"- {lane_name(lane)}" + (f" ({cited})" if cited else "") + f" — {lane['brief']}")
    lines.append("Selected lane descriptions:\n" + "\n".join(rows))
    return "\n\n".join(lines)
