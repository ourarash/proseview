"""Scene Beat Map generation, caching, source anchoring, and validation.

Visual Beat Map provides an abstract progression overview of a scene:
- Sequenced narrative beats with estimated dramatic tension curve.
- Ordered moments (dialogue, action, silent reaction, interiority) with sequential numbering.
- Verbatim source references anchored to exact paragraphs and quote substrings.
- SHA-256 scene revision hash for on-demand invalidation and stale detection.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .lexical import paragraph_blocks, prose_only
from .repo import atomic_write_text, read_repo_text
from .scenes import extract_scene_text, resolve_manuscript_dir, split_frontmatter


BEATMAP_SCHEMA_VERSION = 1
#: How long an agent may take to map a scene. A real agent needs well over
#: 25 seconds for a scene of a few thousand words.
BEATMAP_AGENT_TIMEOUT = 180.0


def compute_scene_hash(text: str) -> str:
    """Compute sha256 checksum of raw scene text."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def beatmap_cache_dir(repo_root: Path) -> Path:
    """Return the directory where cached beatmaps are persisted."""
    return repo_root / ".proseview" / "beatmaps"


def beatmap_cache_path(repo_root: Path, rel_path: str) -> Path:
    """Return the persistent JSON cache path for a scene's beatmap."""
    clean_rel = str(Path(rel_path)).replace("\\", "/")
    stem = hashlib.sha256(clean_rel.encode("utf-8")).hexdigest()[:16]
    return beatmap_cache_dir(repo_root) / f"{stem}.json"


def load_cached_beatmap(repo_root: Path, rel_path: str) -> dict[str, Any] | None:
    """Load a previously saved beatmap from disk, or return None if missing/corrupt."""
    path = beatmap_cache_path(repo_root, rel_path)
    if not path.is_file():
        return None
    try:
        raw = read_repo_text(path)
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("schema_version") == BEATMAP_SCHEMA_VERSION:
            if not data.get("map_version"):
                data["map_version"] = f"bm_{uuid.uuid4().hex[:12]}"
            return data
    except Exception:
        pass
    return None


def save_cached_beatmap(repo_root: Path, rel_path: str, data: dict[str, Any]) -> None:
    """Save beatmap to disk atomically."""
    cache_dir = beatmap_cache_dir(repo_root)
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = beatmap_cache_path(repo_root, rel_path)
    atomic_write_text(target, json.dumps(data, indent=2, ensure_ascii=False))


VALID_MOMENT_TYPES = {"dialogue", "action", "silent_reaction", "interiority"}


def validate_beatmap_anchors(beatmap: dict[str, Any], raw_scene_text: str) -> dict[str, Any]:
    """Validate beat and moment source anchors against the live scene text.

    Sets 'stale' to True if the current file content does not match the
    analyzed_revision_hash. For every moment, verifies whether its exact_quote
    is an exact substring of the referenced paragraph.
    Also validates and sanitizes the schema of beats and moments to prevent
    unvalidated data or script injection.
    """
    current_hash = compute_scene_hash(raw_scene_text)
    analyzed_hash = beatmap.get("analyzed_revision_hash", "")
    is_stale = (current_hash != analyzed_hash)
    beatmap["stale"] = is_stale

    _fm, body = split_frontmatter(raw_scene_text)
    prose = prose_only(extract_scene_text(body))
    paras = paragraph_blocks(prose)

    for b_idx, beat in enumerate(beatmap.get("beats", [])):
        try:
            beat["order"] = int(beat.get("order"))
        except (ValueError, TypeError):
            beat["order"] = b_idx + 1
        clean_b_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(beat.get("id") or f"beat-{beat['order']}"))
        beat["id"] = clean_b_id or f"beat-{beat['order']}"
        beat["title"] = str(beat.get("title") or "Beat").strip()[:120]
        beat["summary"] = str(beat.get("summary") or "").strip()[:500]
        try:
            beat["estimated_tension"] = max(0, min(100, int(round(float(beat.get("estimated_tension", 50))))))
        except (ValueError, TypeError):
            beat["estimated_tension"] = 50
        beat["is_turning_point"] = bool(beat.get("is_turning_point", False))

        for m_idx, moment in enumerate(beat.get("moments", [])):
            try:
                moment["order"] = int(moment.get("order"))
            except (ValueError, TypeError):
                moment["order"] = m_idx + 1
            clean_m_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(moment.get("id") or f"m-{moment['order']:02d}"))
            moment["id"] = clean_m_id or f"m-{moment['order']:02d}"

            # Validate moment type against allowlist to prevent arbitrary strings / XSS
            raw_type = str(moment.get("type") or "").strip().lower()
            clean_type = re.sub(r'[^a-z0-9_-]', '', raw_type)
            if clean_type in VALID_MOMENT_TYPES:
                moment["type"] = clean_type
            else:
                moment["type"] = "action"

            if moment.get("speaker") is not None:
                moment["speaker"] = str(moment["speaker"]).strip()[:80]
            moment["text"] = str(moment.get("text") or "").strip()[:500]

            source_ref = moment.get("source_ref") or {}
            para_idx = source_ref.get("paragraph")
            quote = (source_ref.get("exact_quote") or "").strip()

            valid = False
            if isinstance(para_idx, int) and 0 <= para_idx < len(paras):
                p_text = paras[para_idx]
                if quote and (quote in p_text or quote.replace('"', '“').replace('"', '”') in p_text):
                    valid = True
                elif not quote:
                    valid = True

            # If paragraph shifted slightly due to edits, check neighboring paragraphs
            if not valid and quote:
                for idx, p_text in enumerate(paras):
                    if quote in p_text or quote.replace('"', '“').replace('"', '”') in p_text:
                        valid = True
                        source_ref["paragraph"] = idx
                        break

            moment["valid_anchor"] = valid
            source_ref["valid_anchor"] = valid
            moment["source_ref"] = source_ref

    return beatmap


def heuristic_beatmap_extractor(rel_path: str, raw_scene_text: str, agent: str = "claude", guidance: str = "") -> dict[str, Any]:
    """Deterministic, robust fallback extractor for scene beats and moments.

    Segments the scene's paragraphs into logical narrative beats and extracts
    sequential dialogue/action moments with verified verbatim quotations.
    """
    _fm, body = split_frontmatter(raw_scene_text)
    prose = prose_only(extract_scene_text(body))
    paras = paragraph_blocks(prose)

    total_paras = max(1, len(paras))
    # Determine number of beats (between 3 and 6, obeying guidance if specified)
    match_beats = re.search(r'\b([2-8])\s+beats?\b', guidance.lower()) if guidance else None
    if match_beats:
        num_beats = min(8, max(2, int(match_beats.group(1))))
    else:
        num_beats = min(6, max(3, (total_paras + 2) // 3))
    paras_per_beat = max(1, total_paras // num_beats)

    # Common dramatic curve templates based on beat count
    tension_curves = {
        3: [30, 85, 45],
        4: [25, 60, 90, 40],
        5: [25, 45, 75, 95, 50],
        6: [20, 40, 65, 80, 95, 50],
    }
    curve = tension_curves.get(num_beats, [20 + int(70 * (i / max(1, num_beats - 1))) for i in range(num_beats)])

    beat_titles = [
        "The opening / Setup",
        "The shift / Rising pressure",
        "The complication / Evidence",
        "The confrontation",
        "The revelation / Turning point",
        "The aftermath / Resolution",
    ]

    beats: list[dict[str, Any]] = []
    moment_counter = 1

    dialogue_re = re.compile(r'[“"][^”"]+[”"]')

    for b_idx in range(num_beats):
        start_p = b_idx * paras_per_beat
        if b_idx == num_beats - 1:
            end_p = total_paras - 1
        else:
            end_p = min(total_paras - 1, (b_idx + 1) * paras_per_beat - 1)
        if start_p > end_p:
            start_p = end_p

        is_tp = (b_idx == max(1, num_beats - 2))
        tension = curve[b_idx] if b_idx < len(curve) else 50
        title = beat_titles[min(b_idx, len(beat_titles) - 1)]

        beat_moments: list[dict[str, Any]] = []

        for p_idx in range(start_p, end_p + 1):
            if p_idx >= len(paras):
                break
            p_text = paras[p_idx].strip()
            if not p_text:
                continue

            matches = list(dialogue_re.finditer(p_text))
            if matches:
                for match in matches:
                    quote = match.group(0).strip('“”"')
                    # Infer speaker from following or preceding tag if available
                    after_text = p_text[match.end(): match.end() + 40]
                    speaker_match = re.search(r'\b(said|asked|whispered|murmured|answered|shouted)\s+([A-Z][a-z]+)', after_text)
                    if not speaker_match:
                        speaker_match = re.search(r'([A-Z][a-z]+)\s+(said|asked|whispered|murmured|answered|shouted)', after_text)
                    speaker = speaker_match.group(2) if speaker_match else None
                    if not speaker and speaker_match:
                        speaker = speaker_match.group(1)

                    beat_moments.append({
                        "id": f"m-{moment_counter:02d}",
                        "order": moment_counter,
                        "type": "dialogue",
                        "speaker": speaker,
                        "text": f'"{quote}"',
                        "source_ref": {
                            "paragraph": p_idx,
                            "exact_quote": match.group(0),
                        },
                        "valid_anchor": True,
                    })
                    moment_counter += 1
            else:
                # Narrative action / reaction
                sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', p_text) if s.strip()]
                first_sent = sentences[0] if sentences else p_text[:80]
                m_type = "action"
                if any(w in first_sent.lower() for w in ["silence", "paused", "looked", "stared", "hesitated"]):
                    m_type = "silent_reaction"
                elif any(w in first_sent.lower() for w in ["thought", "remembered", "wished", "knew", "felt"]):
                    m_type = "interiority"

                beat_moments.append({
                    "id": f"m-{moment_counter:02d}",
                    "order": moment_counter,
                    "type": m_type,
                    "speaker": None,
                    "text": first_sent,
                    "source_ref": {
                        "paragraph": p_idx,
                        "exact_quote": first_sent,
                    },
                    "valid_anchor": True,
                })
                moment_counter += 1

        first_p_summary = paras[start_p][:90].strip() if start_p < len(paras) else ""
        summary = first_p_summary.rstrip(".,;:!?") + "..." if first_p_summary else "Scene progression."

        beats.append({
            "id": f"beat-{b_idx + 1}",
            "order": b_idx + 1,
            "title": title,
            "summary": summary,
            "start_paragraph": start_p,
            "end_paragraph": end_p,
            "estimated_tension": tension,
            "is_turning_point": is_tp,
            "moments": beat_moments,
        })

    revision_hash = compute_scene_hash(raw_scene_text)
    now_iso = datetime.now(timezone.utc).isoformat()

    return {
        "schema_version": BEATMAP_SCHEMA_VERSION,
        "map_version": f"bm_{uuid.uuid4().hex[:12]}",
        "scene_path": str(Path(rel_path)).replace("\\", "/"),
        "analyzed_revision_hash": revision_hash,
        "generated_at": now_iso,
        "agent_used": agent,
        "model_used": f"{agent}-heuristic-v1",
        "overall_scene_summary": f"Scene progression spanning {total_paras} paragraphs and {moment_counter - 1} ordered moments.",
        "beats": beats,
        "stale": False,
    }


def build_beatmap_prompt(scene_text: str, rel_path: str, guidance: str = "") -> str:
    """Build the prompt instructing the AI agent to produce a structured beat map."""
    _fm, body = split_frontmatter(scene_text)
    prose = prose_only(extract_scene_text(body))
    paras = paragraph_blocks(prose)

    numbered_paras = "\n\n".join(f"[Paragraph {i}]: {p}" for i, p in enumerate(paras))
    guidance_section = (
        f"\nSpecial Author Guidance:\n{guidance.strip()}\n"
        "Please prioritize and adhere strictly to this author guidance when structuring the beats and tension curve.\n"
        if guidance
        else ""
    )

    return f"""You are analyzing a manuscript scene for Proseview's Visual Beat Map.
Scene Path: {rel_path}
Total Paragraphs: {len(paras)}
{guidance_section}
Instructions:
1. Divide this scene into 4 to 6 chronological narrative beats.
2. For each beat, provide:
   - title: concise (2-4 words)
   - summary: 1 clear sentence summarizing the causal progression
   - start_paragraph: integer paragraph index
   - end_paragraph: integer paragraph index
   - estimated_tension: integer between 0 and 100 representing narrative dramatic tension (psychological stakes, conflict, uncertainty, and emotional intensity).
     Scoring Rubric:
     * 0-25: Low / Calm exposition, domestic routine, low external or internal conflict.
     * 26-50: Moderate / Simmering friction, subtle unease, curiosity, subtext.
     * 51-75: High / Active confrontation, escalation, heightened stakes, urgency.
     * 76-100: Peak / Climax, major revelation, acute crisis, life-altering turning point.
   - is_turning_point: boolean (mark true for the pivotal shift or crisis beat)
   - moments: ordered sequence of events inside this beat.
3. For each moment:
   - order: sequential 1-based integer numbered continuously across the entire scene (1, 2, 3...)
   - type: one of "dialogue", "action", "silent_reaction", "interiority"
   - speaker: character name if dialogue or attributed reaction, else null
   - text: concise description of the moment
   - source_ref: {{"paragraph": <int>, "exact_quote": "<EXACT VERBATIM SUBSTRING FROM MANUSCRIPT>"}}
   CRITICAL: "exact_quote" MUST be an exact character-for-character substring of that paragraph in the manuscript so Proseview can highlight and anchor to it. Do NOT paraphrase.

Numbered Scene Paragraphs:
{numbered_paras}

Output valid JSON matching this schema:
{{
  "overall_scene_summary": "1-2 sentence overview of the scene",
  "beats": [
    {{
      "order": 1,
      "title": "Beat Title",
      "summary": "Beat summary sentence.",
      "start_paragraph": 0,
      "end_paragraph": 2,
      "estimated_tension": 25,
      "is_turning_point": false,
      "moments": [
        {{
          "order": 1,
          "type": "dialogue",
          "speaker": "Alice",
          "text": "Alice asks if the tea is ready.",
          "source_ref": {{
            "paragraph": 0,
            "exact_quote": "Is the tea ready?"
          }}
        }}
      ]
    }}
  ]
}}
"""


def extract_beatmap_with_agent(
    repo_root: Path,
    rel_path: str,
    raw_scene_text: str,
    agent: str = "claude",
    model: str = "",
    guidance: str = "",
    discuss_manager: Any = None,
) -> dict[str, Any]:
    """Extract a beat map using the configured agent CLI via DiscussManager, or fallback."""
    if discuss_manager is not None and hasattr(discuss_manager, "_client_for"):
        client = discuss_manager._client_for(agent)
        if not client:
            raise RuntimeError(f"Agent '{agent}' client could not be started.")

        prompt = build_beatmap_prompt(raw_scene_text, rel_path, guidance=guidance)
        # Ephemeral turn call
        thread_params: dict[str, Any] = {
            "cwd": str(repo_root),
            "approvalPolicy": "never",
            "ephemeral": True,
        }
        started = client.request("thread/start", thread_params)
        thread = started.get("thread") if isinstance(started.get("thread"), dict) else {}
        thread_id = str(thread.get("id") or "")
        if not thread_id:
            raise RuntimeError(f"Failed to start thread for agent '{agent}'.")

        turn_params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
            "cwd": str(repo_root),
            "approvalPolicy": "never",
            "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
            "mayWrite": False,
        }
        if model:
            turn_params["model"] = model

        # Check if client can execute one-off turn
        one_off = getattr(discuss_manager, "_one_offs", None)
        if not isinstance(one_off, dict):
            raise RuntimeError("Discuss manager does not support one-off turns.")

        key = discuss_manager._thread_key(agent, thread_id)
        from .discuss import _OneOff
        holder = _OneOff()
        discuss_manager._one_offs[key] = holder
        try:
            client.request("turn/start", turn_params)
            if not holder.done.wait(timeout=BEATMAP_AGENT_TIMEOUT):
                raise TimeoutError(f"Agent '{agent}' timed out after {BEATMAP_AGENT_TIMEOUT:.0f} seconds.")
            if not holder.text:
                raise RuntimeError(f"Agent '{agent}' returned empty response.")
            # Extract JSON block
            m = re.search(r'\{[\s\S]*\}', holder.text)
            if not m:
                raise ValueError(f"Agent '{agent}' output did not contain valid JSON.")
            parsed = json.loads(m.group(0))
            if "beats" not in parsed or not isinstance(parsed["beats"], list):
                raise ValueError(f"Agent '{agent}' output missing 'beats' array.")
            parsed["schema_version"] = BEATMAP_SCHEMA_VERSION
            parsed["map_version"] = f"bm_{uuid.uuid4().hex[:12]}"
            parsed["scene_path"] = str(Path(rel_path)).replace("\\", "/")
            parsed["analyzed_revision_hash"] = compute_scene_hash(raw_scene_text)
            parsed["generated_at"] = datetime.now(timezone.utc).isoformat()
            parsed["agent_used"] = agent
            parsed["model_used"] = model or f"{agent}-cli"
            # Add IDs if missing
            for b_idx, b in enumerate(parsed["beats"]):
                b["id"] = b.get("id") or f"beat-{b_idx + 1}"
                b["order"] = b.get("order") or (b_idx + 1)
                for m_idx, mo in enumerate(b.get("moments", [])):
                    mo["id"] = mo.get("id") or f"m-{mo.get('order', m_idx + 1):02d}"
            return parsed
        finally:
            discuss_manager._one_offs.pop(key, None)

    return heuristic_beatmap_extractor(rel_path, raw_scene_text, agent=agent, guidance=guidance)


def get_scene_beatmap(repo_root: Path, rel_path: str) -> dict[str, Any]:
    """Retrieve the beatmap for a scene, returning whether it exists and is stale."""
    cfg = Config.load(repo_root)
    manuscript_dir = resolve_manuscript_dir(repo_root, cfg.manuscript_subdir)
    scene_path = (manuscript_dir / rel_path).resolve()

    if not scene_path.is_relative_to(manuscript_dir.resolve()) or not scene_path.is_file():
        raise FileNotFoundError(f"Scene not found: {rel_path}")

    raw_text = read_repo_text(scene_path)
    cached = load_cached_beatmap(repo_root, rel_path)

    if not cached:
        return {
            "ok": True,
            "has_map": False,
            "stale": False,
            "scene_path": str(Path(rel_path)).replace("\\", "/"),
        }

    validated = validate_beatmap_anchors(cached, raw_text)
    return {
        "ok": True,
        "has_map": True,
        "stale": validated.get("stale", False),
        "beatmap": validated,
    }


def generate_scene_beatmap(
    repo_root: Path,
    rel_path: str,
    agent: str = "claude",
    model: str = "",
    guidance: str = "",
    discuss_manager: Any = None,
) -> dict[str, Any]:
    """Generate or update the beatmap for a scene on demand and persist it."""
    cfg = Config.load(repo_root)
    manuscript_dir = resolve_manuscript_dir(repo_root, cfg.manuscript_subdir)
    scene_path = (manuscript_dir / rel_path).resolve()

    if not scene_path.is_relative_to(manuscript_dir.resolve()) or not scene_path.is_file():
        raise FileNotFoundError(f"Scene not found: {rel_path}")

    raw_text = read_repo_text(scene_path)
    beatmap = extract_beatmap_with_agent(
        repo_root=repo_root,
        rel_path=rel_path,
        raw_scene_text=raw_text,
        agent=agent,
        model=model,
        guidance=guidance,
        discuss_manager=discuss_manager,
    )

    # Re-read manuscript text AFTER agent extraction to catch any edits made during generation
    current_text = read_repo_text(scene_path)
    beatmap["map_version"] = f"bm_{uuid.uuid4().hex[:12]}"
    validated = validate_beatmap_anchors(beatmap, current_text)
    save_cached_beatmap(repo_root, rel_path, validated)

    return {
        "ok": True,
        "has_map": True,
        "stale": validated.get("stale", False),
        "beatmap": validated,
    }


def patch_scene_beatmap(
    repo_root: Path,
    rel_path: str,
    patch_payload: dict[str, Any],
) -> dict[str, Any]:
    """Patch one or more beats in an existing cached beatmap or create one if absent.

    Supports modifying:
    - estimated_tension (0-100)
    - title (string)
    - summary (string)
    - is_turning_point (bool)
    """
    cfg = Config.load(repo_root)
    manuscript_dir = resolve_manuscript_dir(repo_root, cfg.manuscript_subdir)
    scene_path = (manuscript_dir / rel_path).resolve()

    if not scene_path.is_relative_to(manuscript_dir.resolve()) or not scene_path.is_file():
        raise FileNotFoundError(f"Scene not found: {rel_path}")

    raw_text = read_repo_text(scene_path)
    beatmap = load_cached_beatmap(repo_root, rel_path)
    if not beatmap:
        gen = generate_scene_beatmap(repo_root, rel_path)
        beatmap = gen["beatmap"]

    # Check map version conflict if expected_map_version or target_map_version was bound to the proposal
    expected_map_ver = (
        patch_payload.get("expected_map_version")
        or patch_payload.get("target_map_version")
        or patch_payload.get("map_version")
    )
    if expected_map_ver and beatmap.get("map_version"):
        if beatmap["map_version"] != expected_map_ver:
            raise ValueError(
                f"Beatmap version conflict: proposal was created for map version {expected_map_ver}, "
                f"but active map version is {beatmap['map_version']}. The beat map has been recreated or modified."
            )

    # Check revision conflict if expected_revision or target_revision was bound to the proposal
    expected_rev = (
        patch_payload.get("expected_revision")
        or patch_payload.get("target_revision")
        or patch_payload.get("revision")
    )
    if expected_rev and beatmap.get("analyzed_revision_hash"):
        if beatmap["analyzed_revision_hash"] != expected_rev:
            raise ValueError(
                f"Beatmap revision conflict: proposal was created for revision {expected_rev[:8]}, "
                f"but active map revision is {beatmap['analyzed_revision_hash'][:8]}."
            )

    # Support full structural replacement if supplied directly by chat agent
    if patch_payload.get("replace") is True and "beats" in patch_payload and isinstance(patch_payload["beats"], list):
        new_beats = patch_payload["beats"]
        for b_idx, b in enumerate(new_beats):
            b["order"] = b_idx + 1
            b["id"] = b.get("id") or f"beat-{b_idx + 1}"
            if "estimated_tension" in b:
                try:
                    b["estimated_tension"] = max(0, min(100, int(round(float(b["estimated_tension"])))))
                except (ValueError, TypeError):
                    b["estimated_tension"] = 50
            b["is_turning_point"] = bool(b.get("is_turning_point", False))
            for m_idx, mo in enumerate(b.get("moments", [])):
                mo["id"] = mo.get("id") or f"m-{mo.get('order', m_idx + 1):02d}"
        beatmap["beats"] = new_beats
        if "overall_scene_summary" in patch_payload and patch_payload["overall_scene_summary"]:
            beatmap["overall_scene_summary"] = str(patch_payload["overall_scene_summary"])[:500]
        beatmap["generated_at"] = datetime.now(timezone.utc).isoformat()
        beatmap["map_version"] = f"bm_{uuid.uuid4().hex[:12]}"
        validated = validate_beatmap_anchors(beatmap, raw_text)
        save_cached_beatmap(repo_root, rel_path, validated)
        return {
            "ok": True,
            "has_map": True,
            "stale": validated.get("stale", False),
            "replaced": True,
            "beatmap": validated,
        }

    beats = beatmap.get("beats", [])
    if not beats:
        raise ValueError("Beatmap contains no beats to patch.")

    # Normalize patches list
    patch_list: list[dict[str, Any]] = []
    if "beats" in patch_payload and isinstance(patch_payload["beats"], list):
        patch_list = patch_payload["beats"]
    else:
        order = patch_payload.get("beat_order", patch_payload.get("order"))
        if order is not None:
            fields = dict(patch_payload.get("patch", patch_payload))
            fields["order"] = order
            patch_list.append(fields)

    if not patch_list:
        raise ValueError("No beat patches provided in payload.")

    beats_by_order = {b.get("order"): b for b in beats}
    updated_orders: list[int] = []

    for item in patch_list:
        if not isinstance(item, dict):
            continue
        order = item.get("order", item.get("beat_order"))
        try:
            order_int = int(order)
        except (TypeError, ValueError):
            continue

        target_beat = beats_by_order.get(order_int)
        if not target_beat:
            continue

        # Tension update (clamped 0 to 100)
        if "estimated_tension" in item:
            try:
                t_val = int(round(float(item["estimated_tension"])))
                target_beat["estimated_tension"] = max(0, min(100, t_val))
            except (ValueError, TypeError):
                pass

        # Title update
        if "title" in item and isinstance(item["title"], str):
            clean_title = item["title"].strip()
            if clean_title:
                target_beat["title"] = clean_title[:120]

        # Summary update
        if "summary" in item and isinstance(item["summary"], str):
            clean_summary = item["summary"].strip()
            if clean_summary:
                target_beat["summary"] = clean_summary[:1000]

        # Turning point update
        if "is_turning_point" in item:
            target_beat["is_turning_point"] = bool(item["is_turning_point"])

        updated_orders.append(order_int)

    if not updated_orders:
        raise ValueError("No matching beats found to patch.")

    beatmap["generated_at"] = datetime.now(timezone.utc).isoformat()
    beatmap["map_version"] = f"bm_{uuid.uuid4().hex[:12]}"
    validated = validate_beatmap_anchors(beatmap, raw_text)
    save_cached_beatmap(repo_root, rel_path, validated)

    return {
        "ok": True,
        "has_map": True,
        "stale": validated.get("stale", False),
        "patched_beats": updated_orders,
        "beatmap": validated,
    }


def format_beatmap_for_context(beatmap: dict[str, Any]) -> str:
    """Format a beatmap into a clean, structured textual representation for LLM context."""
    if not beatmap or not beatmap.get("beats"):
        return ""

    lines = [
        "BEGIN SCENE BEAT MAP",
        f"Scene Path: {beatmap.get('scene_path', 'unknown')}",
        f"Map Version: {beatmap.get('map_version', 'initial')}",
        f"Status: {'OUTDATED (Manuscript edited since map was created)' if beatmap.get('stale') else 'UP-TO-DATE'}",
        f"Overall Summary: {beatmap.get('overall_scene_summary', '')}",
        "Beats and Narrative Trajectory:",
    ]
    for b in beatmap.get("beats", []):
        order = b.get("order", 1)
        title = b.get("title", "")
        tension = b.get("estimated_tension", 50)
        tp_flag = " [TURNING POINT]" if b.get("is_turning_point") else ""
        p_start = b.get("start_paragraph", 0)
        p_end = b.get("end_paragraph", 0)
        lines.append(
            f"- Beat {order}: \"{title}\"{tp_flag} | Dramatic Tension: {tension}/100 | Paragraphs: {p_start}–{p_end}"
        )
        if b.get("summary"):
            lines.append(f"  Summary: {b.get('summary')}")
        moments = b.get("moments", [])
        if moments:
            lines.append(f"  Moments ({len(moments)} total):")
            for m in moments[:25]:
                speaker_prefix = f"{m.get('speaker')}: " if m.get("speaker") else ""
                txt = (m.get("text") or "").replace("\n", " ").strip()
                if len(txt) > 85:
                    txt = txt[:82] + "..."
                p_idx = m.get("source_ref", {}).get("paragraph", "?")
                unverified = ""
                if m.get("valid_anchor") is False or (m.get("source_ref") and m["source_ref"].get("valid_anchor") is False):
                    unverified = " [UNVERIFIED: Anchor quote missing/changed in manuscript]"
                lines.append(
                    f"    - #{m.get('order', 0):02d} [{m.get('type', 'moment')}]{unverified} {speaker_prefix}\"{txt}\" (p.{p_idx})"
                )
            if len(moments) > 25:
                lines.append(f"    ... [{len(moments) - 25} more moments in Beat {order}]")

    lines.append("END SCENE BEAT MAP")
    lines.append(
        "\nBeat Map Modification Guidance for Agent:\n"
        "- If the user asks you to adjust or update a beat (e.g. change tension score, title, summary, or turning point), "
        "explain your choices and provide a ```proseview:beatmap-patch block with the changes, for example:\n"
        "```proseview:beatmap-patch\n"
        "{\n"
        f"  \"expected_map_version\": \"{beatmap.get('map_version', '')}\",\n"
        "  \"beat_order\": 3,\n"
        "  \"patch\": {\n"
        "    \"estimated_tension\": 85,\n"
        "    \"title\": \"The Confrontation\"\n"
        "  }\n"
        "}\n"
        "```\n"
        "- If the user asks you to restructure or recreate the beat map (e.g. changing beat count, focus on a character), "
        "explain your choices and provide a ```proseview:beatmap-recreate block with guidance, for example:\n"
        "```proseview:beatmap-recreate\n"
        "{\n"
        "  \"guidance\": \"Restructure into 4 beats with a strong focus on Babak's hesitation.\"\n"
        "}\n"
        "```\n"
        "Proseview will automatically render interactive 1-click action cards allowing the user to apply your update."
    )
    return "\n".join(lines)
