# Send to Group

Fork the current single-agent chat through its latest completed turn into a Group, where the writer continues and can tag either participant.

- Setup: choose provider and model for **Original assistant** and **Second opinion**. Default to the source settings and the other available provider's default model; fall back to the same provider when necessary.
- Offer **None — I'll direct it** (default), which sends nothing and runs no agent automatically, and **Second opinion & recap**: the other agent assesses the existing answer, the original responds, then a recap closes the exchange. Start the selected workflow after opening Group.
- Group separates **Conversation workflows** from **Task presets** using one shared library, card renderer, options, and execution, with a workflow/task type flag. **Editorial critique** and **Trim & tighten** retain their own task prompts and stay out of fork setup.

The Original assistant continues in a native fork of its session. The Second opinion, and any fresh-session fallback, receives the transferred context below. Persist the native fork; never resume the source in place or replay its transcript into the fork. Changing the Original assistant's provider/model requires a fresh session. Disclose unavailable or failed forks and any fresh-session fallback. Private reasoning is not exported: promise conversation context and available evidence, not identical model context.

Transfer visible messages and each request's instructions, preserving inline selections, facts, and constraints. Separate attached file bodies and include the current scenes/files once. Recover instructions from provider history when needed; truncated Context-inspector receipts are insufficient. Include tool results where session read-back provides them and flag missing evidence. Reuse available history rather than adding raw prompt/tool-log storage.
Include structured review results and alternatives as read-only history, preserving IDs, finding numbers, quotes, and statuses. Live approvals, queued edits, and actionable proposals stay in the source chat.

- Disable forking while the source has running or queued work or awaits approval; recheck on the server when creating the fork.
- Show forked history by author and model. Record models per message going forward; label chat-level model fallbacks for older messages as inferred.
- Link both directions using the exact source session, Group ID, and participant session IDs. Save the scene's previous active Group and any book-wide active Group being replaced in History. Before replacing or forking, check `_groupSessionsByScene[scenePath]`, `_groupActiveSession`, and the server's running Group state; block if a Group anywhere in the book is running.
- Groups opened from a fork route untagged messages like any other Group (current target selector and last-speaker fallback); no @tag is required.
- Check context size in setup only against reliably known model limits; warn before running. Skip preflight for custom/unknown limits and surface provider errors. Offer no trimming option.
- Implementation note: a Claude native fork must persist. After its first turn, clear `fork_from_session_id` and resume using the fork's own `session_id`, so later turns and reconnects do not fork again from the source chat. Test that the fork's second turn remembers its first.

Disable **Second opinion & recap** until Group contains an answer. It has no **Continue to 5 turns** action.

Recaps optionally show a positions table: suggestion, each agent's final stance (**agree**, **disagree**, **revised**, **withdrawn**), and one line of evidence. This shared option behaves identically from either entry point. **Second opinion & recap** turns it on by default and shows the positions table; task presets keep the **Revision plan** card (plus the table when the option is on).
When the positions table is on, the first step numbers the suggestions (keeping review finding numbers; new ones start above the highest existing number), and every participating turn emits STANCE lines. Use `STANCE | suggestion ID | stance | evidence`. Hide these records during streaming and afterward; show their contents only in the table. Split at the first three pipes and use each agent's latest explicit stance per suggestion. Unstated stances stay blank.
