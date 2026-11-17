---
name: update_frontmatter
description: Rewrite YAML frontmatter from the current drafted scene prose.
---

Rewrite this scene's YAML frontmatter using the drafted scene prose as the single source of truth.

1. Preserve structural keys already in the scene when they still apply: `chapter`, `scene`, `timeline`, `status`, and `source` (along with any `todos`, `notes`, or custom structural keys placed there intentionally, unless clearly contradicted by the prose).
2. Completely rewrite all semantic story fields strictly from what actually happens on the page in this draft (`title`, `summary`, `pov`, `when`, `where`, `characters`, `goal`, `conflict`, `outcome`, and any similar beat/plot fields). Drop or replace outdated characters, locations, or goals from earlier versions that are not in the scene text.
3. Set `frontmatter_updated` to today's ISO date (`YYYY-MM-DD`, provided in the scene notes). If the file has no frontmatter block yet, prepend a valid `---` ... `---` YAML block at the top.
4. Edit **only** the YAML frontmatter header in the target scene file. Do not alter the scene prose body or inline annotations.
5. Keep your reply concise: summarize what changed in the YAML (noting stale details removed or updated), confirm which structural keys were kept, and invite the writer to ask for adjustments below.
