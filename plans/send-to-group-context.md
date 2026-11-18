# Send to Group: choose conversation context

Let the writer control how much conversation goes into a Group. Add this choice to the existing fork setup, independently of the workflow and participant settings.

- **Whole conversation:** keep the current transfer behavior, including a native fork for the Original assistant where available.
- **Recent exchanges:** retain the last **[3] exchanges** verbatim; allow **1–10**, with **Include a summary of earlier exchanges** checked by default. There is no summary-only mode. An exchange includes a writer request, its assistant replies, and associated structured results; status updates and tool steps do not count separately.
- Default to Whole conversation on first use, then remember the writer’s context choice, exchange count, and summary checkbox.

Recent-exchange mode preserves the retained requests’ instructions, relevant file references, structured results, and quoted evidence. **Always include the current scene with line numbers**, as `chat_prompt` does, using the unsaved draft when present. Include it once. Remove bodies of other attached/referenced files; agents can read those current files with their tools. Do not resend all historical attachments or tool output.
The optional summary covers only older exchanges: goals, constraints, corrections, decisions, unresolved questions, and the suggestion IDs and evidence needed to continue. Condense older request instructions into it.

- Opening setup and changing options run nothing. On **Fork**, capture the latest completed source turn, prepare the summary if selected, then open the Group and start any chosen workflow. Show **Summarizing 9 earlier exchanges…** while waiting. No separate preparation or editing step.
- Before forking, check kept exchanges plus the current numbered scene, including unsaved content, against known model limits. After preparing the summary, run the existing limit check again before any Group agent starts. Keep the existing treatment of unknown/custom model limits.
- Reuse `/btw`’s temporary-fork mechanics in `discuss.py`: `thread/fork` with `ephemeral=True`, timeout, and interrupt/cancel. Use the **source session’s provider/model**, no tools, and `approvalPolicy: "never"`; reuse neither `/btw`’s permissions nor its source-facing `side_question.*` events. Leave the source untouched and discard the temporary fork afterward; do not promise caching or a particular saving.
- Give the summarizer an explicit cutoff at the **last message before the kept exchanges**, with available structured result snapshots. Summarize only history through that message; modest overlap is acceptable.
- If that fork or summary fails, or its context cannot fit, transfer only the recent exchanges and show a persistent notice that the summary is missing. Do not silently fall back to replaying the whole transcript.
- While summarizing, **Cancel** interrupts the temporary fork, opens no Group, and returns to setup with every choice preserved. Cancellation is not a summary failure and must not trigger the fallback.
- Unchecking the summary option makes no summary call. Skip it when all exchanges are retained, too.
- **Both participants start fresh sessions in recent-exchange mode**, with or without a summary. Say so beside the choice: a native fork would retain the full original history.

In the Group, show any generated summary first, labeled **Generated conversation summary**, followed by the retained exchanges with their original author/model labels. Excluded history stays accessible through the source-chat link.
**None — I’ll direct it** starts no Group turns. The summary checkbox explicitly authorizes the one preparation call at fork time. Existing workflows, links, approval boundaries, busy-state checks, and model-limit checks apply to the resulting context.

Mock: [clickable dark setup](mocks/send-to-group-context.html).
