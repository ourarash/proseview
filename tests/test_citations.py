from __future__ import annotations

from pathlib import Path

from proseview.citations import review_scene_paths, verify_review_citations


BTC = "\n".join([
    "---", "title: BTC", "---", "",
    "Amir talked about tenure again.",
    "He said the servers sat idle all night.",
    "I had root access to all of our servers.",
])
FRIENDS = "\n".join([
    "---", "title: Shadi's Friends", "---", "",
    "I drove slowly, watching the",
    "temperature gauge climbing higher and higher.",
    "The valet took the keys without looking at me.",
])


def _book(tmp_path: Path) -> Path:
    ch = tmp_path / "manuscript" / "ch08"
    ch.mkdir(parents=True)
    (ch / "02-btc.md").write_text(BTC, encoding="utf-8")
    (ch / "03-friends.md").write_text(FRIENDS, encoding="utf-8")
    return tmp_path


REQUEST = (
    "Craft review · Coyne · The Story Grid · 2 scenes\n\nCraft review instructions:\n...\n\n"
    "(Scenes analyzed (2): manuscript/ch08/02-btc.md, manuscript/ch08/03-friends.md. "
    "Analyze the attached scenes in order.)"
)


def test_review_scene_paths_reads_the_request_receipt():
    assert review_scene_paths(REQUEST) == ["manuscript/ch08/02-btc.md", "manuscript/ch08/03-friends.md"]
    assert review_scene_paths("What do you think of this scene?") == []


def test_a_paraphrase_linked_to_the_wrong_scene_is_moved(tmp_path):
    """The chapter table kept the right line and named the previous scene."""
    answer = "| **03 Friends** | The temperature gauge climbs ([L6](manuscript/ch08/02-btc.md#L6)). |"
    fixed = verify_review_citations(_book(tmp_path), REQUEST, answer)
    assert "[L6](manuscript/ch08/03-friends.md#L6)" in fixed
    assert "corrected 1 line link" in fixed


def test_a_quote_linked_to_the_wrong_scene_and_line_is_moved(tmp_path):
    answer = 'The valet ignores him: *"The valet took the keys without looking at me."* ([02-btc.md · Line 5](manuscript/ch08/02-btc.md#L5))'
    fixed = verify_review_citations(_book(tmp_path), REQUEST, answer)
    assert "[03-friends.md · Line 7](manuscript/ch08/03-friends.md#L7)" in fixed


def test_a_drifted_line_in_the_right_scene_is_corrected_with_its_label(tmp_path):
    answer = "> *I had root access to all of our servers.*\n\n[02-btc.md · Line 5](manuscript/ch08/02-btc.md#L5)"
    fixed = verify_review_citations(_book(tmp_path), REQUEST, answer.replace("#L5", "#L1").replace("Line 5", "Line 1"))
    # Line 1 is frontmatter; the quote starts on line 7, too far to be a wrap.
    assert "[02-btc.md · Line 7](manuscript/ch08/02-btc.md#L7)" in fixed


def test_a_quote_wrapped_across_lines_gets_a_range_without_a_correction_note(tmp_path):
    answer = '*"watching the temperature gauge climbing"* ([Line 5](manuscript/ch08/03-friends.md#L5))'
    fixed = verify_review_citations(_book(tmp_path), REQUEST, answer)
    assert fixed == answer.replace("[Line 5](manuscript/ch08/03-friends.md#L5)",
                                   "[Lines 5–6](manuscript/ch08/03-friends.md#L5-L6)")


def test_a_multi_paragraph_blockquote_link_covers_every_quoted_line(tmp_path):
    answer = ('> *"Amir talked about tenure again.*\n>\n> *He said the servers sat idle all night."*\n\n'
              '([02-btc.md · Line 5](manuscript/ch08/02-btc.md#L5))')
    fixed = verify_review_citations(_book(tmp_path), REQUEST, answer)
    assert "([02-btc.md · Lines 5–6](manuscript/ch08/02-btc.md#L5-L6))" in fixed
    assert "Citation check" not in fixed


def test_every_scene_review_card_is_checked(tmp_path):
    request = REQUEST.replace("Craft review · Coyne · The Story Grid · 2 scenes\n\nCraft review instructions:",
                              "Comedy review · 2 scenes\n\nScene review instructions:")
    answer = 'The valet ignores him: *"The valet took the keys without looking at me."* ([Line 5](manuscript/ch08/02-btc.md#L5))'
    assert "manuscript/ch08/03-friends.md#L7" in verify_review_citations(_book(tmp_path), request, answer)


def test_a_quoted_link_into_an_unsupplied_scene_is_checked_there(tmp_path):
    root = _book(tmp_path)
    (root / "manuscript" / "ch08" / "01-earlier.md").write_text(
        "---\ntitle: Earlier\n---\n\nShe was nice to me.\nI built her new desktop.\n", encoding="utf-8")
    drifted = '*"I built her new desktop."* ([01-earlier.md · Line 2](manuscript/ch08/01-earlier.md#L2))'
    assert "[01-earlier.md · Line 6](manuscript/ch08/01-earlier.md#L6)" in verify_review_citations(root, REQUEST, drifted)
    invented = '*"I moved her bookmarks one by one."* ([Line 6](manuscript/ch08/01-earlier.md#L6))'
    assert "could not find the quoted text for this link" in verify_review_citations(root, REQUEST, invented)
    paraphrase = "Nima calls her kind ([Line 2](manuscript/ch08/01-earlier.md#L2))."
    assert verify_review_citations(root, REQUEST, paraphrase) == paraphrase


def test_correct_links_are_left_alone(tmp_path):
    answer = (
        '*"I had root access to all of our servers."* ([L7](manuscript/ch08/02-btc.md#L7))\n'
        "| **02 BTC** | Idle servers at night ([L6](manuscript/ch08/02-btc.md#L6)). |"
    )
    assert verify_review_citations(_book(tmp_path), REQUEST, answer) == answer


def test_an_unfound_quote_is_listed_not_rewritten(tmp_path):
    answer = '*"He sold the car that winter."* ([L6](manuscript/ch08/02-btc.md#L6))'
    fixed = verify_review_citations(_book(tmp_path), REQUEST, answer)
    assert fixed.startswith(answer)
    assert "could not find the quoted text for this link" in fixed
    assert "L6" in fixed.split("Citation check:")[1]


def test_a_reopened_review_does_not_blame_later_revisions(tmp_path):
    """Reopening checks against today's manuscript; a revised quote is not an error."""
    answer = '*"He sold the car that winter."* ([L6](manuscript/ch08/02-btc.md#L6))'
    assert verify_review_citations(_book(tmp_path), REQUEST, answer, report_unfound=False) == answer


def test_a_suggested_replacement_above_a_link_is_not_flagged(tmp_path):
    """A plain blockquote may be new prose; only italic quotes count as evidence."""
    answer = "> The valet smiled and gave me a ticket.\n\n[L7](manuscript/ch08/03-friends.md#L7)"
    assert verify_review_citations(_book(tmp_path), REQUEST, answer) == answer


def test_ordinary_chat_is_never_touched(tmp_path):
    answer = "See ([L6](manuscript/ch08/02-btc.md#L6)) for the gauge."
    assert verify_review_citations(_book(tmp_path), "Where is the gauge?", answer) == answer


def test_live_document_content_is_used_before_disk(tmp_path):
    root = _book(tmp_path)
    live = "\n".join([
        "---",
        "title: BTC",
        "---",
        "First drafted line before the edit.",
        "Second drafted line before the edit.",
        "Waiter set the receipt beside the glass.",
    ])
    answer = '*"Waiter set the receipt beside the glass."* ([L6](manuscript/ch08/02-btc.md#L6))'
    assert verify_review_citations(
        root,
        REQUEST,
        answer,
        live_documents={"manuscript/ch08/02-btc.md": live},
    ) == answer
