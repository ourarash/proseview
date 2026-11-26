"""One-click scene illustration generation, preview caching, and chapter-level asset insertion.

Keeps newly generated images in a quiet preview cache under
``.proseview/scene-images/`` until the writer explicitly clicks
**Insert into scene**, at which point the image is copied into the chapter's
asset folder (default ``<chapter_dir>/assets/<scene_stem>.<ext>``) and embedded
at the top of the scene Markdown as an ``<img src="/repo-asset/..." width="...">`` tag.

Supports:
- **Codex CLI** (native ``image_generation`` tool via ``codex app-server``)
- **Agy CLI** (native ``image-generator`` subagent via ``agy acp --stdio``)
- **Claude CLI** (when an image-generation MCP server is configured)
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import posixpath
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .config import (
    Config,
    DISCUSS_AGENTS,
    SCENE_IMAGE_ASPECT_RATIOS,
    SCENE_IMAGE_STYLE_PRESETS,
    SUGGESTION_PROMPT_MAX,
    SceneImageConfig,
)
from .repo import atomic_write_text, read_repo_text, record_file_backup
from .scenes import extract_scene_text, resolve_manuscript_dir, split_frontmatter

SCENE_IMAGE_SCHEMA_VERSION = 1
SCENE_IMAGE_AGENT_TIMEOUT = 240.0
SCENE_IMAGE_MAX_BYTES = 20 * 1024 * 1024

DEFAULT_SCENE_IMAGE_PROMPT = (
    "Create one atmospheric, literary illustration capturing the mood, setting, "
    "and emotional tension of this scene. Favor subtle lighting and grounded "
    "period or place details. Avoid embedded text, captions, watermarks, or "
    "book-cover typography."
)

BUILTIN_SCENE_IMAGE_STYLES: tuple[dict[str, str], ...] = (
    {
        "id": "ink_watercolor",
        "name": "Ink & Watercolor",
        "tagline": "Warm chiaroscuro, ink wash & paper grain",
        "thumb": "/assets/scene-styles/ink_watercolor.jpg",
        "prompt": (
            "Painterly ink-and-watercolor editorial book illustration, warm amber "
            "chiaroscuro, tactile paper grain, serene and cinematic, no text or watermarks."
        ),
    },
    {
        "id": "woodcut",
        "name": "Woodcut & Engraving",
        "tagline": "Monochrome linocut on antique cream paper",
        "thumb": "/assets/scene-styles/woodcut.jpg",
        "prompt": (
            "Monochrome literary woodcut engraving on warm cream antique book paper, "
            "crisp crosshatched ink lines, high-contrast chiaroscuro, classic chapter "
            "plate aesthetic, no text."
        ),
    },
    {
        "id": "film_still",
        "name": "35mm Film Still",
        "tagline": "Cinematic natural grain & practical lighting",
        "thumb": "/assets/scene-styles/film_still.jpg",
        "prompt": (
            "Atmospheric 35mm cinematic film still, subtle film grain, shallow depth of "
            "field, moody practical lighting, candid indie cinema realism, no text or subtitles."
        ),
    },
    {
        "id": "charcoal",
        "name": "Charcoal & Pencil",
        "tagline": "Expressive sketchbook shading & graphite",
        "thumb": "/assets/scene-styles/charcoal.jpg",
        "prompt": (
            "Expressive charcoal and graphite pencil sketch on warm off-white textured "
            "sketchbook paper, quiet tonal shading, delicate linework, calm literary "
            "storyboard feel, no text."
        ),
    },
    {
        "id": "oil_painting",
        "name": "Oil Painting",
        "tagline": "Classical brushwork & Hopper mood lighting",
        "thumb": "/assets/scene-styles/oil_painting.jpg",
        "prompt": (
            "Classical oil painting on canvas, visible painterly brushwork, Edward Hopper "
            "and Dutch chiaroscuro mood lighting, rich deep umber and warm ochre palette, no text."
        ),
    },
    {
        "id": "gouache",
        "name": "Minimalist Gouache",
        "tagline": "Matte mid-century book-jacket editorial art",
        "thumb": "/assets/scene-styles/gouache.jpg",
        "prompt": (
            "Minimalist mid-century gouache editorial illustration, flat matte gouache "
            "shapes, restrained poetic color palette, classic literary book-jacket "
            "composition, no text."
        ),
    },
)

STYLE_BY_ID: dict[str, dict[str, str]] = {row["id"]: row for row in BUILTIN_SCENE_IMAGE_STYLES}

_IMAGE_MIME_BY_EXT: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_EXT_BY_IMAGE_MIME: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

_IMAGE_MCP_KEYWORDS = (
    "image",
    "imagen",
    "imagine",
    "flux",
    "dall",
    "midjourney",
    "replicate",
    "ideogram",
    "stability",
    "recraft",
    "nano-banana",
    "nanobanana",
    "gpt-image",
    "fal",
)

_active_image_jobs: dict[str, dict[str, Any]] = {}
_active_image_lock = threading.Lock()
_claude_mcp_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_claude_mcp_lock = threading.Lock()

_LEADING_MD_IMAGE_RE = re.compile(
    r"^\s*!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)\s*$"
)
_LEADING_HTML_IMAGE_RE = re.compile(
    r'^\s*<img\b[^>]*\bsrc\s*=\s*["\'](?P<src>[^"\']+)["\'][^>]*>\s*$',
    re.IGNORECASE,
)
_DATA_URL_IMAGE_RE = re.compile(
    r"data:(image/(?:png|jpeg|jpg|webp|gif));base64,([A-Za-z0-9+/=\s]+)",
    re.IGNORECASE,
)
_ABS_IMAGE_PATH_RE = re.compile(
    r"(?P<path>(?:/[^\s\"'`<>|()]+|[A-Za-z]:\\[^\s\"'`<>|()]+)\.(?:png|jpe?g|webp|gif))",
    re.IGNORECASE,
)


def detect_image_format(data: bytes) -> tuple[str, str] | None:
    """Return ``(ext, mime)`` from image magic bytes, or None if not a valid raster image."""
    if not data or len(data) < 12 or len(data) > SCENE_IMAGE_MAX_BYTES:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif", "image/gif"
    return None


def _decode_base64_image(raw: str) -> tuple[bytes, str, str] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    m = _DATA_URL_IMAGE_RE.search(text)
    payload = m.group(2) if m else text
    compact = re.sub(r"\s+", "", payload)
    if len(compact) < 32:
        return None
    try:
        data = base64.b64decode(compact, validate=False)
    except Exception:
        return None
    fmt = detect_image_format(data)
    if fmt is None:
        return None
    ext, mime = fmt
    return data, ext, mime


def _read_valid_image_file(path_str: str) -> tuple[bytes, str, str] | None:
    raw = str(path_str or "").strip().strip("\"'`")
    if raw.lower().startswith("file://"):
        raw = unquote(raw[7:])
    if not raw:
        return None
    try:
        candidate = Path(raw).expanduser().resolve()
    except (OSError, ValueError):
        return None
    if not candidate.is_file():
        return None
    try:
        size = candidate.stat().st_size
        if size < 12 or size > SCENE_IMAGE_MAX_BYTES:
            return None
        data = candidate.read_bytes()
    except OSError:
        return None
    fmt = detect_image_format(data)
    if fmt is None:
        return None
    ext, mime = fmt
    return data, ext, mime


def _clean_rel_path(rel_path: str) -> str:
    return str(rel_path or "").strip().replace("\\", "/").lstrip("/")


def _resolve_scene_path(repo_root: Path, rel_path: str) -> tuple[Config, Path, Path, str]:
    cfg = Config.load(repo_root)
    manuscript_dir = resolve_manuscript_dir(repo_root, cfg.manuscript_subdir).resolve()
    clean = _clean_rel_path(rel_path)
    if not clean or ".." in Path(clean).parts:
        raise FileNotFoundError(f"Scene not found: {rel_path}")
    scene_path = (manuscript_dir / clean).resolve()
    if not scene_path.is_relative_to(manuscript_dir) or not scene_path.is_file():
        raise FileNotFoundError(f"Scene not found: {rel_path}")
    return cfg, manuscript_dir, scene_path, clean


def _scene_hash_key(rel_path: str) -> str:
    return hashlib.sha256(_clean_rel_path(rel_path).encode("utf-8")).hexdigest()[:16]


def scene_image_cache_dir(repo_root: Path) -> Path:
    return repo_root / ".proseview" / "scene-images"


def scene_image_chat_dir(repo_root: Path) -> Path:
    return scene_image_cache_dir(repo_root) / "chat"


def scene_image_meta_path(repo_root: Path, rel_path: str) -> Path:
    return scene_image_cache_dir(repo_root) / f"{_scene_hash_key(rel_path)}.json"


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(target)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def detect_claude_image_mcp(repo_root: Path | None = None, *, force: bool = False) -> dict[str, Any]:
    """Best-effort, read-only check for an image-generation MCP server in Claude Code config."""
    cache_key = str(repo_root.resolve()) if repo_root else ""
    now = time.monotonic()
    with _claude_mcp_lock:
        cached = _claude_mcp_cache.get(cache_key)
        if not force and cached and (now - cached[0]) < 30.0:
            return dict(cached[1])

    candidates: list[Path] = []
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    candidates.extend([
        Path.home() / ".claude.json",
        claude_dir / "settings.json",
        claude_dir / "mcp.json",
    ])
    if repo_root is not None:
        candidates.extend([
            repo_root / ".mcp.json",
            repo_root / ".claude" / "settings.json",
            repo_root / ".claude" / "settings.local.json",
        ])

    matched: list[str] = []
    seen: set[str] = set()

    def _scan_servers(mapping: Any) -> None:
        if not isinstance(mapping, dict):
            return
        for name, spec in mapping.items():
            name_str = str(name or "").strip()
            if not name_str or name_str in seen:
                continue
            haystack_parts = [name_str.lower()]
            if isinstance(spec, dict):
                for field in ("command", "url", "description"):
                    if spec.get(field):
                        haystack_parts.append(str(spec.get(field)).lower())
                args = spec.get("args")
                if isinstance(args, list):
                    haystack_parts.extend(str(a).lower() for a in args)
            haystack = " ".join(haystack_parts)
            if any(kw in haystack for kw in _IMAGE_MCP_KEYWORDS):
                seen.add(name_str)
                matched.append(name_str)

    for path in candidates:
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(raw, dict):
            continue
        _scan_servers(raw.get("mcpServers"))
        projects = raw.get("projects")
        if isinstance(projects, dict) and repo_root is not None:
            proj = projects.get(str(repo_root.resolve()))
            if isinstance(proj, dict):
                _scan_servers(proj.get("mcpServers"))

    result = {
        "available": bool(matched),
        "servers": matched,
    }
    with _claude_mcp_lock:
        _claude_mcp_cache[cache_key] = (now, dict(result))
    return result


_MAX_PREVIEW_TAKES = 20


def _load_preview_store(repo_root: Path, rel_path: str) -> dict[str, Any] | None:
    """Load the normalized multi-take preview store for ``rel_path``."""
    meta_path = scene_image_meta_path(repo_root, rel_path)
    if not meta_path.is_file():
        return None
    try:
        raw = json.loads(read_repo_text(meta_path))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    cache_root = scene_image_cache_dir(repo_root).resolve()
    clean = _clean_rel_path(rel_path)

    # Backwards-compatibility: upgrade legacy single-preview JSON into a 1-take store.
    if isinstance(raw.get("takes"), list):
        raw_takes = [t for t in raw["takes"] if isinstance(t, dict)]
        active_id = str(raw.get("active_take_id") or "").strip()
    elif raw.get("filename"):
        legacy = dict(raw)
        legacy.setdefault("id", str(raw.get("version") or "take1"))
        raw_takes = [legacy]
        active_id = legacy["id"]
    else:
        return None

    valid_takes: list[dict[str, Any]] = []
    for take in raw_takes:
        filename = str(take.get("filename") or "").strip()
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            continue
        img_path = (cache_root / filename).resolve()
        if not img_path.is_relative_to(cache_root) or not img_path.is_file():
            continue
        tid = str(take.get("id") or take.get("version") or "").strip()
        if not tid:
            continue
        entry = dict(take)
        entry["id"] = tid
        entry["abs_preview_path"] = str(img_path)
        entry["preview_url"] = (
            f"/api/scene/image/preview?path={clean}&take={tid}&v={entry.get('version', tid)}"
        )
        valid_takes.append(entry)

    if not valid_takes:
        return None
    if not any(t["id"] == active_id for t in valid_takes):
        active_id = valid_takes[-1]["id"]
    return {
        "schema_version": SCENE_IMAGE_SCHEMA_VERSION,
        "scene_path": clean,
        "active_take_id": active_id,
        "takes": valid_takes,
    }


def _format_active_preview(store: dict[str, Any], *, take_id: str = "") -> dict[str, Any] | None:
    takes = store.get("takes") or []
    if not takes:
        return None
    wanted = take_id or str(store.get("active_take_id") or "")
    idx = next((i for i, t in enumerate(takes) if t["id"] == wanted), len(takes) - 1)
    active = dict(takes[idx])
    active["take_id"] = active["id"]
    active["take_index"] = idx + 1
    active["take_count"] = len(takes)
    active["takes"] = [
        {
            "id": t["id"],
            "index": i + 1,
            "style_id": t.get("style_id", ""),
            "style_name": t.get("style_name", ""),
            "agent": t.get("agent", ""),
            "alt": t.get("alt", ""),
            "note": t.get("note", ""),
            "preview_url": t["preview_url"],
            "generated_at": t.get("generated_at", ""),
        }
        for i, t in enumerate(takes)
    ]
    return active


def load_scene_image_preview(repo_root: Path, rel_path: str, *, take_id: str = "") -> dict[str, Any] | None:
    """Load the active (or requested) cached scene image preview metadata."""
    store = _load_preview_store(repo_root, rel_path)
    if not store:
        return None
    return _format_active_preview(store, take_id=take_id)


def save_scene_image_preview(
    repo_root: Path,
    rel_path: str,
    image_bytes: bytes,
    ext: str,
    mime: str,
    *,
    agent: str,
    model: str = "",
    style_id: str = "ink_watercolor",
    style_name: str = "",
    note: str = "",
    prompt_used: str = "",
    revised_prompt: str = "",
    alt: str = "",
) -> dict[str, Any]:
    """Append a new generated preview take for ``rel_path`` and make it active."""
    cache_dir = scene_image_cache_dir(repo_root)
    cache_dir.mkdir(parents=True, exist_ok=True)
    stem = _scene_hash_key(rel_path)
    ext = ext if ext in _IMAGE_MIME_BY_EXT else ".png"
    take_id = uuid.uuid4().hex[:10]
    filename = f"{stem}_{take_id}{ext}"
    img_path = cache_dir / filename
    _atomic_write_bytes(img_path, image_bytes)

    clean = _clean_rel_path(rel_path)
    style_info = STYLE_BY_ID.get(style_id)
    new_take = {
        "id": take_id,
        "schema_version": SCENE_IMAGE_SCHEMA_VERSION,
        "scene_path": clean,
        "filename": filename,
        "ext": ext,
        "mime": mime or _IMAGE_MIME_BY_EXT.get(ext, "image/png"),
        "bytes": len(image_bytes),
        "version": take_id,
        "agent": agent,
        "model": model,
        "style_id": style_id,
        "style_name": style_name or (style_info["name"] if style_info else "Custom style"),
        "note": note,
        "prompt_used": prompt_used[:8000],
        "revised_prompt": revised_prompt[:4000],
        "alt": alt.strip()[:300],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    existing_store = _load_preview_store(repo_root, clean)
    takes_to_keep: list[dict[str, Any]] = []
    if existing_store:
        for old in existing_store["takes"]:
            cleaned = {k: v for k, v in old.items() if k not in {"abs_preview_path", "preview_url"}}
            takes_to_keep.append(cleaned)
    takes_to_keep.append(new_take)

    # Evict oldest takes beyond cap and remove their image files.
    while len(takes_to_keep) > _MAX_PREVIEW_TAKES:
        evicted = takes_to_keep.pop(0)
        ev_file = cache_dir / str(evicted.get("filename") or "")
        if ev_file.is_file():
            try:
                ev_file.unlink()
            except OSError:
                pass

    persisted = {
        "schema_version": SCENE_IMAGE_SCHEMA_VERSION,
        "scene_path": clean,
        "active_take_id": take_id,
        "takes": takes_to_keep,
    }
    atomic_write_text(scene_image_meta_path(repo_root, clean), json.dumps(persisted, indent=2, ensure_ascii=False))
    reloaded = _load_preview_store(repo_root, clean)
    assert reloaded is not None
    formatted = _format_active_preview(reloaded, take_id=take_id)
    assert formatted is not None
    return formatted


def select_scene_image_take(repo_root: Path, rel_path: str, take_id: str) -> dict[str, Any]:
    """Switch the active preview take for ``rel_path`` to ``take_id``."""
    clean = _clean_rel_path(rel_path)
    store = _load_preview_store(repo_root, clean)
    if not store:
        raise FileNotFoundError("No preview takes exist for this scene.")
    wanted = str(take_id or "").strip()
    if not any(t["id"] == wanted for t in store["takes"]):
        raise FileNotFoundError("Requested preview take was not found.")
    persisted = {
        "schema_version": SCENE_IMAGE_SCHEMA_VERSION,
        "scene_path": clean,
        "active_take_id": wanted,
        "takes": [
            {k: v for k, v in t.items() if k not in {"abs_preview_path", "preview_url"}}
            for t in store["takes"]
        ],
    }
    atomic_write_text(scene_image_meta_path(repo_root, clean), json.dumps(persisted, indent=2, ensure_ascii=False))
    reloaded = _load_preview_store(repo_root, clean)
    assert reloaded is not None
    formatted = _format_active_preview(reloaded, take_id=wanted)
    assert formatted is not None
    return {"ok": True, "preview": formatted}


def dismiss_scene_image_preview(repo_root: Path, rel_path: str) -> bool:
    """Delete cached preview takes and metadata for ``rel_path``."""
    removed = False
    store = _load_preview_store(repo_root, rel_path)
    if store:
        for t in store["takes"]:
            p = Path(t["abs_preview_path"])
            if p.is_file():
                try:
                    p.unlink()
                    removed = True
                except OSError:
                    pass
    meta_path = scene_image_meta_path(repo_root, rel_path)
    if meta_path.is_file():
        try:
            meta_path.unlink()
            removed = True
        except OSError:
            pass
    stem = _scene_hash_key(rel_path)
    cache_dir = scene_image_cache_dir(repo_root)
    if cache_dir.is_dir():
        for candidate in cache_dir.glob(f"{stem}*"):
            if candidate.is_file():
                try:
                    candidate.unlink()
                    removed = True
                except OSError:
                    pass
    return removed


def load_preview_image_bytes(repo_root: Path, rel_path: str, *, take_id: str = "") -> tuple[bytes, str] | None:
    """Return ``(bytes, mime)`` for the active or requested preview take of ``rel_path``."""
    meta = load_scene_image_preview(repo_root, rel_path, take_id=take_id)
    if not meta:
        return None
    img_path = Path(meta["abs_preview_path"])
    try:
        return img_path.read_bytes(), str(meta.get("mime") or "image/png")
    except OSError:
        return None


def save_chat_generated_image(
    repo_root: Path,
    image_bytes: bytes,
    ext: str,
    mime: str,
    *,
    agent: str,
    scene_path: str = "",
    revised_prompt: str = "",
    alt: str = "",
    image_id: str = "",
) -> dict[str, Any]:
    """Store an image generated inside a Discuss chat turn so the UI can display & promote it."""
    chat_dir = scene_image_chat_dir(repo_root)
    chat_dir.mkdir(parents=True, exist_ok=True)
    clean_id = re.sub(r"[^a-f0-9]", "", str(image_id or "").lower())[:16]
    if clean_id:
        existing = load_chat_image_meta(repo_root, clean_id)
        if existing is not None:
            return existing
    final_id = clean_id or uuid.uuid4().hex[:16]
    ext = ext if ext in _IMAGE_MIME_BY_EXT else ".png"
    filename = f"{final_id}{ext}"
    _atomic_write_bytes(chat_dir / filename, image_bytes)
    meta = {
        "image_id": final_id,
        "filename": filename,
        "ext": ext,
        "mime": mime or _IMAGE_MIME_BY_EXT.get(ext, "image/png"),
        "bytes": len(image_bytes),
        "agent": agent,
        "scene_path": _clean_rel_path(scene_path),
        "revised_prompt": revised_prompt[:4000],
        "alt": alt[:300],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "url": f"/api/scene/image/chat?id={final_id}",
    }
    atomic_write_text(chat_dir / f"{final_id}.json", json.dumps(meta, indent=2, ensure_ascii=False))
    return meta


def load_chat_image_meta(repo_root: Path, image_id: str) -> dict[str, Any] | None:
    clean_id = re.sub(r"[^a-f0-9]", "", str(image_id or "").lower())
    if not clean_id:
        return None
    chat_dir = scene_image_chat_dir(repo_root).resolve()
    meta_path = (chat_dir / f"{clean_id}.json").resolve()
    if not meta_path.is_relative_to(chat_dir) or not meta_path.is_file():
        return None
    try:
        meta = json.loads(read_repo_text(meta_path))
    except Exception:
        return None
    filename = str(meta.get("filename") or "")
    img_path = (chat_dir / filename).resolve()
    if not img_path.is_relative_to(chat_dir) or not img_path.is_file():
        return None
    meta["abs_path"] = str(img_path)
    return meta


def load_chat_image_bytes(repo_root: Path, image_id: str) -> tuple[bytes, str] | None:
    meta = load_chat_image_meta(repo_root, image_id)
    if not meta:
        return None
    try:
        return Path(meta["abs_path"]).read_bytes(), str(meta.get("mime") or "image/png")
    except OSError:
        return None


def capture_chat_image_from_event(
    repo_root: Path,
    event: dict[str, Any],
    *,
    agent: str,
    scene_path: str = "",
    deterministic_key: str = "",
) -> dict[str, Any] | None:
    """Extract and persist a generated image from a Codex ``image.generated`` event or thread item."""
    extracted = _extract_image_from_event_payload(event)
    if extracted is None:
        return None
    data, ext, mime = extracted
    det_id = ""
    if deterministic_key:
        det_id = hashlib.sha256(deterministic_key.encode("utf-8")).hexdigest()[:16]
    return save_chat_generated_image(
        repo_root,
        data,
        ext,
        mime,
        agent=agent,
        scene_path=scene_path,
        revised_prompt=str(event.get("revised_prompt") or event.get("revisedPrompt") or ""),
        image_id=det_id,
    )


_CODEX_GEN_IMG_LINK_RE = re.compile(
    r"!?\[[^\]]*\]\((?:file://|sandbox:)?(?P<path>(?:/[^\s)]+|\b[A-Za-z]:\\[^\s)]+)\.(?:png|jpe?g|webp))\)",
    re.IGNORECASE,
)


def capture_chat_image_from_text(
    repo_root: Path,
    text: str,
    *,
    agent: str,
    scene_path: str = "",
    activities: dict[str, Any] | None = None,
    deterministic: bool = False,
    force_signal: bool = False,
    explicit_only: bool = False,
) -> dict[str, Any] | None:
    """Best-effort capture of a generated image path returned in Discuss chat text or activities.

    With *explicit_only*, only the JSON reply an illustration prompt asks for
    counts; image paths and links in ordinary replies are left alone.
    """
    raw_text = str(text or "")
    # 1. Explicit JSON payload (Agy `image-generator` / Claude MCP):
    #    {"image_path": "/abs/path/to/file.jpg", "alt": "...", "revised_prompt": "..."}
    parsed = _extract_json_dict(raw_text)
    if parsed:
        parsed_alt = str(parsed.get("alt") or "").strip()
        parsed_rev = str(parsed.get("revised_prompt") or "").strip()
        for key in ("image_path", "path", "file_path", "saved_path"):
            val = parsed.get(key)
            if isinstance(val, str) and val.strip():
                found = _read_valid_image_file(val)
                if found is not None:
                    data, ext, mime = found
                    det_id = hashlib.sha256(f"json:{val}".encode("utf-8")).hexdigest()[:16] if deterministic else ""
                    return save_chat_generated_image(
                        repo_root,
                        data,
                        ext,
                        mime,
                        agent=agent,
                        scene_path=scene_path,
                        revised_prompt=parsed_rev,
                        alt=parsed_alt,
                        image_id=det_id,
                    )
        for key in ("image_base64", "data_url", "image_data", "result"):
            val = parsed.get(key)
            if isinstance(val, str) and val.strip():
                decoded = _decode_base64_image(val)
                if decoded is not None:
                    data, ext, mime = decoded
                    det_id = hashlib.sha256(data).hexdigest()[:16] if deterministic else ""
                    return save_chat_generated_image(
                        repo_root,
                        data,
                        ext,
                        mime,
                        agent=agent,
                        scene_path=scene_path,
                        revised_prompt=parsed_rev,
                        alt=parsed_alt,
                        image_id=det_id,
                    )

    if explicit_only:
        return None
    sources = [raw_text]
    low = raw_text.lower()
    has_image_signal = (
        force_signal
        or "image-generator" in low
        or "generate_image" in low
        or "image_path" in low
        or "/generated_images/" in low
        or ".codex/generated_images/" in low
        or "/.gemini/antigravity" in low
        or bool(_CODEX_GEN_IMG_LINK_RE.search(raw_text))
    )
    if isinstance(activities, dict):
        for act in activities.values():
            if not isinstance(act, dict):
                continue
            tool = str(act.get("tool") or "").lower()
            kind = str(act.get("kind") or "").lower()
            out = str(act.get("output") or "")
            if "image" in tool or "image" in kind or "subagent" in tool or "image-generator" in out.lower():
                has_image_signal = True
            if out:
                sources.append(out)
    if not has_image_signal:
        return None
    # Prefer explicit markdown image/file links first (e.g. Codex/Agy linking savedPath).
    for m in _CODEX_GEN_IMG_LINK_RE.finditer(raw_text):
        p = m.group("path")
        found = _read_valid_image_file(p)
        if found is not None:
            data, ext, mime = found
            det_id = hashlib.sha256(f"text:{p}".encode("utf-8")).hexdigest()[:16] if deterministic else ""
            return save_chat_generated_image(
                repo_root,
                data,
                ext,
                mime,
                agent=agent,
                scene_path=scene_path,
                image_id=det_id,
            )
    for chunk in sources:
        for match in _ABS_IMAGE_PATH_RE.finditer(chunk):
            p = match.group("path")
            found = _read_valid_image_file(p)
            if found is not None:
                data, ext, mime = found
                det_id = hashlib.sha256(f"text:{p}".encode("utf-8")).hexdigest()[:16] if deterministic else ""
                return save_chat_generated_image(
                    repo_root,
                    data,
                    ext,
                    mime,
                    agent=agent,
                    scene_path=scene_path,
                    image_id=det_id,
                )
    return None


_SCENE_IMAGE_JSON_KEYS = frozenset({"alt", "revised_prompt", "image_path", "path", "file_path", "saved_path"})


def format_scene_image_reply_text(text: str, *, has_images: bool = False) -> tuple[str, str, str]:
    """Unwrap legacy/Agy JSON scene-image replies into calm prose and return ``(clean_text, alt, revised_prompt)``."""
    raw = str(text or "").strip()
    if not raw:
        return "", "", ""
    parsed = _extract_json_dict(raw)
    parsed_alt = str(parsed.get("alt") or "").strip()
    parsed_rev = str(parsed.get("revised_prompt") or "").strip()
    keys_match = bool(parsed) and set(parsed.keys()).issubset(_SCENE_IMAGE_JSON_KEYS)
    if parsed and (has_images or keys_match) and (parsed_alt or parsed_rev or parsed.get("image_path")):
        if raw.startswith(("{", "```")) or (has_images and keys_match):
            # Replace raw machine JSON (including Agy replay with pre-tool text + JSON)
            # with a calm, human-readable caption.
            clean = parsed_alt or parsed_rev or ("Scene illustration ready." if has_images else raw)
            return clean, parsed_alt, parsed_rev
    if has_images:
        # Remove dead local file links to generated_images when the real card is attached right below.
        cleaned = _CODEX_GEN_IMG_LINK_RE.sub("", raw).strip()
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned, parsed_alt, parsed_rev
    return raw, parsed_alt, parsed_rev


def promote_chat_image_to_preview(repo_root: Path, rel_path: str, image_id: str) -> dict[str, Any]:
    """Copy a chat-generated image into the scene's preview slot."""
    _cfg, _ms, _scene_path, clean = _resolve_scene_path(repo_root, rel_path)
    meta = load_chat_image_meta(repo_root, image_id)
    if not meta:
        raise FileNotFoundError("Generated chat image not found.")
    data = Path(meta["abs_path"]).read_bytes()
    preview = save_scene_image_preview(
        repo_root,
        clean,
        data,
        str(meta.get("ext") or ".png"),
        str(meta.get("mime") or "image/png"),
        agent=str(meta.get("agent") or "codex"),
        style_id="custom",
        style_name="From Discuss chat",
        revised_prompt=str(meta.get("revised_prompt") or ""),
        alt=str(meta.get("alt") or ""),
    )
    return {"ok": True, "preview": preview}


def _find_leading_scene_image(body: str) -> dict[str, Any] | None:
    """Inspect whether the first non-blank line of a scene body is a standalone image."""
    lines = body.splitlines()
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        m_md = _LEADING_MD_IMAGE_RE.match(line)
        if m_md:
            return {
                "line_index": idx,
                "kind": "markdown",
                "alt": m_md.group("alt").strip(),
                "src": m_md.group("src").strip(),
                "raw_line": line,
            }
        m_html = _LEADING_HTML_IMAGE_RE.match(line)
        if m_html:
            return {
                "line_index": idx,
                "kind": "html",
                "alt": "",
                "src": m_html.group("src").strip(),
                "raw_line": line,
            }
        break
    return None


def _scene_title_from_file(raw_text: str, scene_path: Path) -> str:
    fm, _body = split_frontmatter(raw_text)
    if isinstance(fm, dict):
        title = str(fm.get("title") or fm.get("scene") or "").strip()
        if title:
            return title
    stem = re.sub(r"^\d+[-_]+", "", scene_path.stem)
    return re.sub(r"[-_]+", " ", stem).strip().title() or scene_path.stem


def _scene_asset_destination(
    repo_root: Path,
    cfg: SceneImageConfig,
    scene_path: Path,
    ext: str,
) -> tuple[Path, str, str]:
    """Compute ``(abs_dest, markdown_src, repo_rel_path)`` for inserting a scene image.

    When ``cfg.assets_dir`` is relative (default ``"assets"``), images are stored
    under the chapter's asset folder (e.g.
    ``manuscript/ch01/assets/01-opening.png``) and linked with a portable
    relative path (``assets/01-opening.png``) or ``/repo-asset/...``.
    When ``cfg.assets_dir`` starts with ``/``, images are stored under that
    repository-rooted folder (e.g. ``/assets/scenes`` -> ``assets/scenes/...``).
    """
    root_resolved = repo_root.resolve()
    raw_dir = str(cfg.assets_dir or "assets").strip().replace("\\", "/")
    ext = ext if ext in _IMAGE_MIME_BY_EXT else ".png"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", scene_path.stem).strip("-") or "scene"

    if raw_dir.startswith("/"):
        rel_dir = raw_dir.lstrip("/").rstrip("/") or "assets"
        if ".." in Path(rel_dir).parts:
            raise ValueError("Invalid assets_dir: path traversal is not allowed.")
        chapter_prefix = re.sub(r"[^A-Za-z0-9._-]+", "-", scene_path.parent.name).strip("-")
        filename = f"{chapter_prefix}-{stem}{ext}" if chapter_prefix else f"{stem}{ext}"
        dest = (root_resolved / rel_dir / filename).resolve()
        if not dest.is_relative_to(root_resolved):
            raise ValueError("Destination image path escapes repository root.")
        repo_rel = dest.relative_to(root_resolved).as_posix()
        md_src = f"/repo-asset/{repo_rel}"
        return dest, md_src, repo_rel

    rel_dir = raw_dir.rstrip("/") or "assets"
    if ".." in Path(rel_dir).parts:
        raise ValueError("Invalid assets_dir: path traversal is not allowed.")
    filename = f"{stem}{ext}"
    dest = (scene_path.parent / rel_dir / filename).resolve()
    if not dest.is_relative_to(root_resolved):
        raise ValueError("Destination image path escapes repository root.")
    repo_rel = dest.relative_to(root_resolved).as_posix()
    md_src = posixpath.join(rel_dir, filename)
    return dest, md_src, repo_rel


def _split_frontmatter_raw(raw_text: str) -> tuple[str, str]:
    """Split a scene file into exact raw YAML frontmatter prefix and body text."""
    if not raw_text.startswith("---"):
        return "", raw_text
    m = re.match(r"^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)", raw_text)
    if not m:
        return "", raw_text
    return raw_text[: m.end()], raw_text[m.end() :]


def insert_scene_image(
    repo_root: Path,
    rel_path: str,
    *,
    chat_image_id: str = "",
    take_id: str = "",
    alt: str = "",
    width: int | None = None,
    replace_existing: bool = True,
) -> dict[str, Any]:
    """Copy preview (or chat) image into ``<scene>/assets/`` and embed as ``<img src="/repo-asset/..." ...>``."""
    cfg, _ms, scene_path, clean = _resolve_scene_path(repo_root, rel_path)
    if chat_image_id:
        chat_meta = load_chat_image_meta(repo_root, chat_image_id)
        if not chat_meta:
            raise FileNotFoundError("Generated chat image not found.")
        image_bytes = Path(chat_meta["abs_path"]).read_bytes()
        ext = str(chat_meta.get("ext") or ".png")
        default_alt = str(chat_meta.get("alt") or "")
    else:
        preview = load_scene_image_preview(repo_root, clean, take_id=take_id)
        if not preview:
            raise FileNotFoundError("No preview image is ready for this scene.")
        image_bytes = Path(preview["abs_preview_path"]).read_bytes()
        ext = str(preview.get("ext") or ".png")
        default_alt = str(preview.get("alt") or "")

    raw_text = read_repo_text(scene_path)
    fm_prefix, body = _split_frontmatter_raw(raw_text)
    scene_title = _scene_title_from_file(raw_text, scene_path)
    clean_alt = " ".join((alt or default_alt or scene_title).split()).strip()
    eff_width = cfg.scene_image.width if width is None else int(width)
    eff_width = max(120, min(1600, eff_width))

    dest, _rel_md_src, repo_rel = _scene_asset_destination(repo_root, cfg.scene_image, scene_path, ext)
    _atomic_write_bytes(dest, image_bytes)

    asset_url = f"/repo-asset/{repo_rel}"
    escaped_alt = html.escape(clean_alt, quote=True)
    image_line = f'<img src="{asset_url}" alt="{escaped_alt}" width="{eff_width}">'
    leading = _find_leading_scene_image(body)
    newline = "\r\n" if "\r\n" in raw_text else "\n"

    if leading and replace_existing:
        body_lines = body.splitlines()
        body_lines[leading["line_index"]] = image_line
        new_body = newline.join(body_lines)
        if raw_text.endswith(("\n", "\r\n")) and not new_body.endswith(("\n", "\r\n")):
            new_body += newline
    else:
        trimmed_body = body.lstrip("\r\n")
        if fm_prefix:
            new_body = f"{newline}{image_line}{newline}{newline}{trimmed_body}"
        else:
            new_body = f"{image_line}{newline}{newline}{trimmed_body}"

    new_text = fm_prefix + new_body
    # Record backup so Proseview History and Undo always work.
    record_file_backup(repo_root, scene_path, raw_text, "scene-image")
    atomic_write_text(scene_path, new_text)

    dismiss_scene_image_preview(repo_root, clean)

    return {
        "ok": True,
        "scene_path": clean,
        "asset_repo_path": repo_rel,
        "markdown_src": asset_url,
        "image_line": image_line,
        "alt": clean_alt,
        "width": eff_width,
        "asset_url": asset_url,
    }


def remove_scene_image_from_scene(repo_root: Path, rel_path: str) -> dict[str, Any]:
    """Remove the leading embedded image from the scene Markdown (preserving backup)."""
    cfg, _ms, scene_path, clean = _resolve_scene_path(repo_root, rel_path)
    raw_text = read_repo_text(scene_path)
    fm_prefix, body = _split_frontmatter_raw(raw_text)
    leading = _find_leading_scene_image(body)
    if not leading:
        return {"ok": True, "removed": False, "scene_path": clean}

    lines = body.splitlines()
    idx = leading["line_index"]
    # Remove the image line and one following blank separator line if present.
    del lines[idx]
    while idx < len(lines) and not lines[idx].strip():
        del lines[idx]
    newline = "\r\n" if "\r\n" in raw_text else "\n"
    new_body = newline.join(lines).lstrip("\r\n")
    if fm_prefix and new_body:
        new_text = fm_prefix + newline + new_body
    else:
        new_text = fm_prefix + new_body
    if raw_text.endswith(("\n", "\r\n")) and new_text and not new_text.endswith(("\n", "\r\n")):
        new_text += newline

    record_file_backup(repo_root, scene_path, raw_text, "scene-image")
    atomic_write_text(scene_path, new_text)
    return {
        "ok": True,
        "removed": True,
        "scene_path": clean,
        "removed_src": leading["src"],
    }


def _collect_character_context(repo_root: Path, cfg: Config, fm: Any, prose: str) -> str:
    """Gather concise character bios referenced in frontmatter or prose (capped cleanly)."""
    chars_dir = (repo_root / cfg.characters_dir).resolve()
    if not chars_dir.is_dir():
        return ""
    mentioned_lower = prose.lower()
    fm_names: set[str] = set()
    if isinstance(fm, dict):
        for key in ("pov", "characters", "cast"):
            val = fm.get(key)
            if isinstance(val, str) and val.strip():
                fm_names.add(val.strip().lower())
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and item.strip():
                        fm_names.add(item.strip().lower())

    snippets: list[str] = []
    budget = 3500
    for md in sorted(chars_dir.glob("*.md")):
        stem = md.stem.replace("-", " ").replace("_", " ").strip()
        stem_lower = stem.lower()
        first_word = stem_lower.split()[0] if stem_lower else ""
        if not (
            stem_lower in fm_names
            or (first_word and len(first_word) >= 3 and first_word in mentioned_lower)
            or stem_lower in mentioned_lower
        ):
            continue
        try:
            text = read_repo_text(md).strip()
        except OSError:
            continue
        if not text:
            continue
        chunk = text[:900]
        if len(chunk) > budget:
            break
        snippets.append(f"### Character: {stem.title()}\n{chunk}")
        budget -= len(chunk)
        if budget <= 200 or len(snippets) >= 4:
            break
    return "\n\n".join(snippets)


def is_scene_image_prompt(prompt: str) -> bool:
    """True for the prompt of an illustration request (see :func:`start_scene_image_job`)."""
    question = str(prompt or "").rsplit("\n\nUSER QUESTION\n", 1)[-1]
    return question.startswith(("Generate a scene illustration (", "Refine the scene illustration ("))


def build_scene_image_prompt(
    repo_root: Path,
    cfg: Config,
    rel_path: str,
    raw_scene_text: str,
    *,
    agent: str,
    style_id: str = "",
    style_text: str = "",
    aspect_ratio: str = "",
    note: str = "",
    refine_image_path: str = "",
    staging_dir: Path | None = None,
) -> tuple[str, dict[str, str]]:
    """Build the agent prompt for creating or refining a scene illustration."""
    si = cfg.scene_image
    effective_style_id = (style_id or si.style_preset or "ink_watercolor").strip().lower()
    preset = STYLE_BY_ID.get(effective_style_id)
    effective_style_text = (
        style_text.strip()
        or (si.style.strip() if effective_style_id == "custom" else "")
        or (preset["prompt"] if preset else STYLE_BY_ID["ink_watercolor"]["prompt"])
    )
    effective_style_name = preset["name"] if preset else "Custom style"
    effective_aspect = (aspect_ratio or si.aspect_ratio or "16:9").strip()
    if effective_aspect not in SCENE_IMAGE_ASPECT_RATIOS:
        effective_aspect = "16:9"
    base_prompt = (si.prompt or DEFAULT_SCENE_IMAGE_PROMPT).strip()

    fm, body = split_frontmatter(raw_scene_text)
    scene_prose = extract_scene_text(body).strip()
    if len(scene_prose) > 20_000:
        scene_prose = scene_prose[:20_000] + "\n… [scene truncated for length] …"

    sections: list[str] = [base_prompt]
    sections.append(f"VISUAL STYLE ({effective_style_name}):\n{effective_style_text}")
    sections.append(f"ASPECT RATIO: {effective_aspect} (landscape/matching framing; no borders or text).")

    if note.strip():
        sections.append(f"AUTHOR DIRECTION FOR THIS SCENE:\n{note.strip()}")

    if refine_image_path:
        sections.append(
            "ITERATION / REFINEMENT:\n"
            f"Refine and edit the existing scene illustration at `{refine_image_path}` "
            "while keeping its overall mood and continuity unless the author direction asks to change it."
        )

    if si.include_frontmatter and isinstance(fm, dict) and fm:
        fm_lines = [f"- {k}: {v}" for k, v in fm.items() if v not in (None, "", [])]
        if fm_lines:
            sections.append("SCENE METADATA:\n" + "\n".join(fm_lines[:15]))

    if si.include_characters:
        char_ctx = _collect_character_context(repo_root, cfg, fm, scene_prose)
        if char_ctx:
            sections.append("RELEVANT CHARACTER NOTES (for visual consistency):\n" + char_ctx)

    sections.append(f"SCENE ({rel_path}):\n{scene_prose}")

    if agent == "codex":
        sections.append(
            "EXECUTION INSTRUCTIONS (IMPORTANT):\n"
            "- Use your built-in raster image generation tool once to create the illustration.\n"
            "- Do NOT edit or create any manuscript files and do NOT run shell commands to save the file; "
            "Proseview captures and renders your generated image automatically in chat and above the scene.\n"
            "- After generating the image, reply in 1–2 brief natural sentences describing what you depicted "
            "(plain prose — do NOT return JSON and do NOT include local file paths or markdown image links)."
        )
    elif agent == "agy":
        sections.append(
            "EXECUTION INSTRUCTIONS (IMPORTANT):\n"
            "- Invoke your built-in `image-generator` subagent once with a rich visual brief based on the style, "
            "aspect ratio, author direction, and scene above"
            + (f", asking it to edit/refine the existing image at `{refine_image_path}`" if refine_image_path else "")
            + ".\n"
            "- Do NOT edit any manuscript files.\n"
            "- Once `image-generator` returns the saved image file path, reply with ONLY a JSON object: "
            '{"image_path": "<exact absolute path returned by image-generator>", '
            '"alt": "<1-sentence descriptive alt text>", "revised_prompt": "<brief summary>"}.'
        )
    else:
        target_hint = (
            f"Save the generated PNG or JPEG image inside `{staging_dir}`."
            if staging_dir is not None
            else "Return the absolute file path or data URL of the generated PNG/JPEG image."
        )
        sections.append(
            "EXECUTION INSTRUCTIONS (IMPORTANT):\n"
            "- Use your connected image-generation MCP tool once to generate a raster PNG or JPEG illustration.\n"
            f"- {target_hint}\n"
            "- Do NOT edit any manuscript files.\n"
            "- Reply with ONLY a JSON object: "
            '{"image_path": "<absolute path to the generated image file>", '
            '"alt": "<1-sentence descriptive alt text>", "revised_prompt": "<brief summary>"}.'
        )

    full_prompt = "\n\n".join(sections)
    meta = {
        "style_id": effective_style_id,
        "style_name": effective_style_name,
        "style_text": effective_style_text,
        "aspect_ratio": effective_aspect,
    }
    return full_prompt, meta


def _extract_json_dict(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except ValueError:
        pass
    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE):
        try:
            parsed = json.loads(m.group(1).strip())
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
    decoder = json.JSONDecoder()
    idx = 0
    while (pos := text.find("{", idx)) != -1:
        try:
            obj, _end = decoder.raw_decode(text, pos)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
        idx = pos + 1
    return {}


def _extract_image_from_event_payload(event: dict[str, Any]) -> tuple[bytes, str, str] | None:
    if not isinstance(event, dict):
        return None
    saved = str(event.get("saved_path") or event.get("savedPath") or "").strip()
    if saved:
        found = _read_valid_image_file(saved)
        if found is not None:
            return found
    raw_res = str(event.get("result") or "").strip()
    if raw_res:
        decoded = _decode_base64_image(raw_res)
        if decoded is not None:
            return decoded
    return None


def _extract_image_from_one_off(
    holder: Any,
    raw_output: str,
    staging_dir: Path | None = None,
) -> tuple[bytes, str, str, str, str]:
    """Return ``(bytes, ext, mime, alt, revised_prompt)`` from a completed one-off turn."""
    parsed = _extract_json_dict(raw_output)
    alt = str(parsed.get("alt") or "").strip()
    revised = str(parsed.get("revised_prompt") or "").strip()

    # 1. Codex native ImageGenerationThreadItem events captured on _OneOff
    for ev in reversed(getattr(holder, "generated_images", []) or []):
        if isinstance(ev, dict):
            if not revised and ev.get("revised_prompt"):
                revised = str(ev.get("revised_prompt") or "").strip()
            extracted = _extract_image_from_event_payload(ev)
            if extracted is not None:
                data, ext, mime = extracted
                return data, ext, mime, alt, revised
            failure = ev.get("failure")
            if isinstance(failure, dict) and failure.get("type"):
                raise RuntimeError(f"Image generation failed: {failure.get('type')}")

    # 2. Explicit image_path / image_base64 in agent's JSON output (Agy & Claude MCP)
    for key in ("image_path", "path", "file_path", "saved_path"):
        val = parsed.get(key)
        if isinstance(val, str) and val.strip():
            found = _read_valid_image_file(val)
            if found is not None:
                data, ext, mime = found
                return data, ext, mime, alt, revised
    for key in ("image_base64", "data_url", "image_data", "result"):
        val = parsed.get(key)
        if isinstance(val, str) and val.strip():
            decoded = _decode_base64_image(val)
            if decoded is not None:
                data, ext, mime = decoded
                return data, ext, mime, alt, revised

    # 3. Staging directory created for Claude MCP tools
    if staging_dir is not None and staging_dir.is_dir():
        for file_path in sorted(staging_dir.rglob("*"), key=lambda p: p.stat().st_mtime if p.is_file() else 0, reverse=True):
            if file_path.is_file():
                found = _read_valid_image_file(str(file_path))
                if found is not None:
                    data, ext, mime = found
                    return data, ext, mime, alt, revised

    # 4. Data URL or absolute file path in raw output or tool activity outputs
    chunks = [raw_output]
    for act in (getattr(holder, "activities", None) or {}).values():
        if isinstance(act, dict) and act.get("output"):
            chunks.append(str(act["output"]))
    for chunk in chunks:
        if not chunk:
            continue
        decoded = _decode_base64_image(chunk)
        if decoded is not None:
            data, ext, mime = decoded
            return data, ext, mime, alt, revised
        for m in _ABS_IMAGE_PATH_RE.finditer(chunk):
            found = _read_valid_image_file(m.group("path"))
            if found is not None:
                data, ext, mime = found
                return data, ext, mime, alt, revised

    raise RuntimeError(
        "The agent finished without returning a raster image. "
        "Try Codex or Agy (both have native image generation), or verify your image MCP server."
    )


def generate_scene_image(
    repo_root: Path,
    rel_path: str,
    *,
    agent: str = "",
    model: str = "",
    style_id: str = "",
    style_text: str = "",
    aspect_ratio: str = "",
    note: str = "",
    refine: bool = False,
    discuss_manager: Any = None,
    allow_claude_without_mcp: bool = False,
    job_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a scene image via the configured agent and store it in the preview cache."""
    cfg, _ms, scene_path, clean = _resolve_scene_path(repo_root, rel_path)
    chosen_agent = (agent or cfg.scene_image.agent or "codex").strip().lower()
    if chosen_agent not in DISCUSS_AGENTS:
        chosen_agent = "codex"
    chosen_model = (model or cfg.scene_image.model or "").strip()

    if chosen_agent == "claude" and not allow_claude_without_mcp:
        mcp = detect_claude_image_mcp(repo_root)
        if not mcp["available"]:
            raise RuntimeError(
                "Claude CLI has no built-in raster image generator. "
                "Switch to Codex or Agy, or connect an image-generation MCP server in Claude Code."
            )

    if discuss_manager is None:
        raise RuntimeError("Discuss manager is unavailable; cannot invoke agent for scene image.")

    raw_text = read_repo_text(scene_path)
    refine_path = ""
    if refine:
        existing_preview = load_scene_image_preview(repo_root, clean)
        if existing_preview and existing_preview.get("abs_preview_path"):
            refine_path = str(existing_preview["abs_preview_path"])
        else:
            # Also check if there's an inserted image at the top of the scene!
            _fm, body = split_frontmatter(raw_text)
            leading = _find_leading_scene_image(body)
            if leading:
                from .epub import resolve_image
                try:
                    resolved = resolve_image(repo_root, leading["src"], scene_path.relative_to(repo_root.resolve()), clean)
                    if resolved.is_file():
                        refine_path = str(resolved)
                except Exception:
                    pass

    staging_dir: Path | None = None
    if chosen_agent == "claude":
        staging_dir = scene_image_cache_dir(repo_root) / "_staging" / uuid.uuid4().hex[:12]
        staging_dir.mkdir(parents=True, exist_ok=True)

    prompt, prompt_meta = build_scene_image_prompt(
        repo_root,
        cfg,
        clean,
        raw_text,
        agent=chosen_agent,
        style_id=style_id,
        style_text=style_text,
        aspect_ratio=aspect_ratio,
        note=note,
        refine_image_path=refine_path,
        staging_dir=staging_dir,
    )

    client_getter = getattr(discuss_manager, "_client_for", None) or getattr(discuss_manager, "_ensure_client", None)
    if not callable(client_getter):
        raise RuntimeError("Discuss manager cannot start an agent client.")
    client = client_getter(chosen_agent)
    if not client:
        raise RuntimeError(f"Agent '{chosen_agent}' client could not be started.")
    thread_params: dict[str, Any] = {
        "cwd": str(repo_root.resolve()),
        "ephemeral": True,
        "approvalPolicy": "never",
    }
    if chosen_agent == "codex":
        if not cfg.scene_image.instructions:
            thread_params["config"] = {"project_doc_max_bytes": 0}
    elif chosen_agent == "claude":
        thread_params["settingSources"] = ["user", "project", "local"] if cfg.scene_image.instructions else ["user"]
    started = client.request("thread/start", thread_params, timeout=30.0)
    thread_id = str((started.get("thread") or {}).get("id") or "")
    if not thread_id:
        raise RuntimeError(f"Agent '{chosen_agent}' did not return a thread id.")

    turn_input: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if chosen_agent == "codex" and refine_path and Path(refine_path).is_file():
        turn_input.append({"type": "localImage", "path": refine_path})

    turn_params: dict[str, Any] = {
        "threadId": thread_id,
        "cwd": str(repo_root.resolve()),
        "input": turn_input,
        "approvalPolicy": "never",
        "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
        "mayWrite": False,
    }
    if chosen_agent == "agy":
        turn_params["autoApproveTools"] = ["invoke_subagent"]
    if chosen_model:
        turn_params["model"] = chosen_model

    from .discuss import _OneOff
    holder = _OneOff()
    key = discuss_manager._thread_key(chosen_agent, thread_id)
    discuss_manager._one_offs[key] = holder
    if job_record is not None:
        job_record["holder"] = holder

    try:
        turn_res = client.request("turn/start", turn_params, timeout=60.0)
        turn_id = str((turn_res.get("turn") or {}).get("id") or "")

        def _interrupt() -> None:
            if turn_id:
                try:
                    client.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout=10.0)
                except Exception:
                    pass

        holder.interrupt = _interrupt
        if job_record is not None and job_record.get("cancelled"):
            _interrupt()
            raise RuntimeError("Cancelled")

        if not holder.done.wait(timeout=SCENE_IMAGE_AGENT_TIMEOUT):
            _interrupt()
            raise TimeoutError(f"Agent '{chosen_agent}' timed out after {SCENE_IMAGE_AGENT_TIMEOUT:.0f}s.")

        if job_record is not None and job_record.get("cancelled"):
            raise RuntimeError("Cancelled")

        if holder.status == "failed" and holder.error and not holder.generated_images:
            raise RuntimeError(holder.error)

        raw_output = (holder.text or holder.draft or "").strip()
        data, ext, mime, alt, revised = _extract_image_from_one_off(holder, raw_output, staging_dir=staging_dir)
        scene_title = _scene_title_from_file(raw_text, scene_path)
        preview = save_scene_image_preview(
            repo_root,
            clean,
            data,
            ext,
            mime,
            agent=chosen_agent,
            model=chosen_model,
            style_id=prompt_meta["style_id"],
            style_name=prompt_meta["style_name"],
            note=note.strip(),
            prompt_used=prompt,
            revised_prompt=revised,
            alt=alt or scene_title,
        )
        return {"ok": True, "preview": preview}
    finally:
        discuss_manager._one_offs.pop(key, None)
        discard = getattr(client, "discard_ephemeral_thread", None)
        if callable(discard):
            try:
                discard(thread_id)
            except Exception:
                pass
        if staging_dir is not None and staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def _job_key(repo_root: Path, rel_path: str) -> str:
    return f"{repo_root.resolve()}:{_clean_rel_path(rel_path)}"


def get_scene_image_status(repo_root: Path, rel_path: str) -> dict[str, Any]:
    """Return live generation job status + current preview/embedded info for a scene."""
    clean = _clean_rel_path(rel_path)
    key = _job_key(repo_root, clean)
    with _active_image_lock:
        job = _active_image_jobs.get(key)
        job_snap = dict(job) if job else None

    if job_snap and job_snap.get("active"):
        holder = job_snap.get("holder")
        elapsed = int(max(0.0, time.time() - float(job_snap.get("started_at", time.time()))))
        progress = str(getattr(holder, "progress", "") or "").strip() if holder else ""
        return {
            "ok": True,
            "active": True,
            "scene_path": clean,
            "job_id": job_snap.get("job_id", ""),
            "conversation_id": job_snap.get("conversation_id", ""),
            "agent": job_snap.get("agent", "codex"),
            "style_id": job_snap.get("style_id", "ink_watercolor"),
            "style_name": job_snap.get("style_name", "Ink & Watercolor"),
            "note": job_snap.get("note", ""),
            "refine": bool(job_snap.get("refine")),
            "elapsed_seconds": elapsed,
            "progress_text": progress[:300],
        }

    preview = load_scene_image_preview(repo_root, clean)
    embedded: dict[str, Any] | None = None
    try:
        _cfg, _ms, scene_path, _clean = _resolve_scene_path(repo_root, clean)
        raw_text = read_repo_text(scene_path)
        _fm, body = split_frontmatter(raw_text)
        embedded = _find_leading_scene_image(body)
    except FileNotFoundError:
        pass

    error_text = ""
    if job_snap and not job_snap.get("active") and job_snap.get("error"):
        error_text = str(job_snap["error"])

    return {
        "ok": True,
        "active": False,
        "scene_path": clean,
        "has_preview": preview is not None,
        "preview": preview,
        "embedded": embedded,
        "error": error_text,
    }


def start_scene_image_job(
    repo_root: Path,
    rel_path: str,
    *,
    agent: str = "",
    model: str = "",
    style_id: str = "",
    style_text: str = "",
    aspect_ratio: str = "",
    note: str = "",
    refine: bool = False,
    discuss_manager: Any = None,
) -> dict[str, Any]:
    """Start non-blocking scene image generation and return immediately.

    When ``discuss_manager`` supports ``submit_scene_image``, the request runs
    directly inside the scene's live Discuss conversation so the user sees the
    request, progress, and generated image in chat and can follow up in the
    exact same thread.
    """
    cfg, _ms, scene_path, clean = _resolve_scene_path(repo_root, rel_path)
    chosen_agent = (agent or cfg.scene_image.agent or "codex").strip().lower()
    if chosen_agent not in DISCUSS_AGENTS:
        chosen_agent = "codex"
    if chosen_agent == "claude":
        mcp = detect_claude_image_mcp(repo_root)
        if not mcp["available"]:
            raise ValueError(
                "Claude CLI has no built-in raster image generator. "
                "Switch to Codex or Agy, or connect an image-generation MCP server in Claude Code."
            )

    chosen_style_id = (style_id or cfg.scene_image.style_preset or "ink_watercolor").strip().lower()
    style_info = STYLE_BY_ID.get(chosen_style_id)
    style_name = style_info["name"] if style_info else "Custom style"
    chosen_model = (model or cfg.scene_image.model or "").strip()
    key = _job_key(repo_root, clean)
    job_id = uuid.uuid4().hex[:12]

    with _active_image_lock:
        existing = _active_image_jobs.get(key)
        if existing and existing.get("active"):
            existing["cancelled"] = True
            holder = existing.get("holder")
            if holder and callable(getattr(holder, "interrupt", None)):
                try:
                    holder.interrupt()
                except Exception:
                    pass
        job: dict[str, Any] = {
            "job_id": job_id,
            "active": True,
            "cancelled": False,
            "scene_path": clean,
            "conversation_id": "",
            "discuss_manager": discuss_manager,
            "agent": chosen_agent,
            "style_id": chosen_style_id,
            "style_name": style_name,
            "note": note.strip(),
            "refine": bool(refine),
            "started_at": time.time(),
            "holder": None,
            "error": "",
        }
        _active_image_jobs[key] = job

    # Preferred path: run directly inside the scene's Discuss chat so the writer
    # sees the request, progress, and image card in the chat tab and can iterate
    # naturally in the same conversation thread.
    submit_fn = getattr(discuss_manager, "submit_scene_image", None)
    if callable(submit_fn):
        raw_text = read_repo_text(scene_path)
        scene_title = _scene_title_from_file(raw_text, scene_path)
        refine_path = ""
        if refine:
            existing_preview = load_scene_image_preview(repo_root, clean)
            if existing_preview and existing_preview.get("abs_preview_path"):
                refine_path = str(existing_preview["abs_preview_path"])
            else:
                _fm, body = split_frontmatter(raw_text)
                leading = _find_leading_scene_image(body)
                if leading:
                    from .epub import resolve_image
                    try:
                        resolved = resolve_image(
                            repo_root, leading["src"], scene_path.relative_to(repo_root.resolve()), clean
                        )
                        if resolved.is_file():
                            refine_path = str(resolved)
                    except Exception:
                        pass

        full_prompt, prompt_meta = build_scene_image_prompt(
            repo_root,
            cfg,
            clean,
            raw_text,
            agent=chosen_agent,
            style_id=chosen_style_id,
            style_text=style_text,
            aspect_ratio=aspect_ratio,
            note=note,
            refine_image_path=refine_path,
        )
        eff_aspect = prompt_meta["aspect_ratio"]
        clean_note = note.strip()
        if refine:
            visible_question = (
                f"Refine the scene illustration ({prompt_meta['style_name']}, {eff_aspect}): {clean_note}"
                if clean_note
                else f"Refine the scene illustration ({prompt_meta['style_name']}, {eff_aspect})."
            )
        else:
            visible_question = (
                f"Generate a scene illustration ({prompt_meta['style_name']}, {eff_aspect}): {clean_note}"
                if clean_note
                else f"Generate a scene illustration ({prompt_meta['style_name']}, {eff_aspect})."
            )

        def _on_complete(_preview: dict[str, Any] | None, err: str) -> None:
            with _active_image_lock:
                if not job.get("cancelled") and err:
                    job["error"] = err
                job["active"] = False

        try:
            submitted = submit_fn(
                clean,
                agent=chosen_agent,
                visible_question=visible_question,
                full_prompt=full_prompt,
                refine_image_path=refine_path,
                model=chosen_model,
                scene_image_job={
                    "scene_path": clean,
                    "scene_title": scene_title,
                    "style_id": prompt_meta["style_id"],
                    "style_name": prompt_meta["style_name"],
                    "model": chosen_model,
                    "note": clean_note,
                    "prompt_used": full_prompt,
                    "on_complete": _on_complete,
                },
            )
            with _active_image_lock:
                job["conversation_id"] = str(submitted.get("conversation_id") or "")
                job["client_request_id"] = str(submitted.get("client_request_id") or "")
        except Exception as exc:
            with _active_image_lock:
                job["active"] = False
                job["error"] = str(exc)
            raise

        return {
            "ok": True,
            "active": True,
            "job_id": job_id,
            "conversation_id": job["conversation_id"],
            "scene_path": clean,
            "agent": chosen_agent,
            "style_id": chosen_style_id,
            "style_name": style_name,
            "note": clean_note,
            "refine": bool(refine),
        }

    def _worker() -> None:
        try:
            generate_scene_image(
                repo_root,
                clean,
                agent=chosen_agent,
                model=chosen_model,
                style_id=chosen_style_id,
                style_text=style_text,
                aspect_ratio=aspect_ratio,
                note=note,
                refine=refine,
                discuss_manager=discuss_manager,
                job_record=job,
            )
        except Exception as exc:
            if not job.get("cancelled"):
                job["error"] = str(exc)
        finally:
            with _active_image_lock:
                job["active"] = False
                job["holder"] = None

    thread = threading.Thread(target=_worker, name=f"proseview-scene-img-{job_id}", daemon=True)
    thread.start()
    return {
        "ok": True,
        "active": True,
        "job_id": job_id,
        "conversation_id": "",
        "scene_path": clean,
        "agent": chosen_agent,
        "style_id": chosen_style_id,
        "style_name": style_name,
        "note": note.strip(),
        "refine": bool(refine),
    }


def cancel_scene_image_job(repo_root: Path, rel_path: str) -> dict[str, Any]:
    """Cancel an active scene image generation job if one is running."""
    clean = _clean_rel_path(rel_path)
    key = _job_key(repo_root, clean)
    with _active_image_lock:
        job = _active_image_jobs.get(key)
        if not job or not job.get("active"):
            return {"ok": True, "cancelled": False, "scene_path": clean}
        job["cancelled"] = True
        job["active"] = False
        job["error"] = ""
        holder = job.get("holder")
        conv_id = str(job.get("conversation_id") or "")
        req_id = str(job.get("client_request_id") or "")
        mgr = job.get("discuss_manager")
    if holder and callable(getattr(holder, "interrupt", None)):
        try:
            holder.interrupt()
        except Exception:
            pass
    if conv_id and mgr is not None:
        cancelled_queued = False
        if req_id and hasattr(mgr, "cancel_queued"):
            try:
                mgr.cancel_queued(conv_id, req_id)
                cancelled_queued = True
            except Exception:
                cancelled_queued = False
        if not cancelled_queued and hasattr(mgr, "stop"):
            try:
                conv = getattr(mgr, "_conversations", {}).get(conv_id)
                turn_id = str(getattr(conv, "active_turn_id", "") or "") if conv else ""
                if turn_id:
                    mgr.stop(conv_id, turn_id)
            except Exception:
                pass
    return {"ok": True, "cancelled": True, "scene_path": clean}


def scene_image_settings_payload(repo_root: Path) -> dict[str, Any]:
    """Return the full settings + style gallery + agent capability payload for Settings & Popover."""
    cfg = Config.load(repo_root)
    si = cfg.scene_image
    preset = STYLE_BY_ID.get(si.style_preset)
    effective_style_text = si.style or (preset["prompt"] if preset else STYLE_BY_ID["ink_watercolor"]["prompt"])
    claude_mcp = detect_claude_image_mcp(repo_root)
    return {
        "book": {
            "agent": si.agent,
            "model": si.model,
            "style_preset": si.style_preset,
            "style": effective_style_text,
            "aspect_ratio": si.aspect_ratio,
            "assets_dir": si.assets_dir,
            "width": si.width,
            "include_frontmatter": si.include_frontmatter,
            "include_characters": si.include_characters,
            "instructions": si.instructions,
            "prompt": si.prompt or DEFAULT_SCENE_IMAGE_PROMPT,
        },
        "defaults": {
            "agent": SceneImageConfig().agent,
            "model": "",
            "style_preset": SceneImageConfig().style_preset,
            "style": STYLE_BY_ID[SceneImageConfig().style_preset]["prompt"],
            "aspect_ratio": SceneImageConfig().aspect_ratio,
            "assets_dir": SceneImageConfig().assets_dir,
            "width": SceneImageConfig().width,
            "include_frontmatter": SceneImageConfig().include_frontmatter,
            "include_characters": SceneImageConfig().include_characters,
            "instructions": SceneImageConfig().instructions,
            "prompt": DEFAULT_SCENE_IMAGE_PROMPT,
        },
        "styles": [dict(row) for row in BUILTIN_SCENE_IMAGE_STYLES],
        "aspect_ratios": list(SCENE_IMAGE_ASPECT_RATIOS),
        "capabilities": {
            "codex": {"native": True, "note": "Native image generation"},
            "agy": {"native": True, "note": "Native image-generator"},
            "claude": {
                "native": False,
                "mcp_detected": bool(claude_mcp["available"]),
                "mcp_servers": list(claude_mcp["servers"]),
                "note": (
                    f"Image MCP detected ({', '.join(claude_mcp['servers'])})"
                    if claude_mcp["available"]
                    else "Requires an image MCP server in Claude Code"
                ),
            },
        },
    }


def save_scene_image_settings_payload(repo_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist ``scene_image:`` settings into ``.proseview.yaml``."""
    raw_book = body.get("book") if isinstance(body.get("book"), dict) else None
    if raw_book is not None:
        cfg = Config.load(repo_root)
        defaults = SceneImageConfig()
        agent = str(raw_book.get("agent") or defaults.agent).strip().lower()
        if agent not in DISCUSS_AGENTS:
            agent = defaults.agent
        model = str(raw_book.get("model") or "").strip()
        style_preset = str(raw_book.get("style_preset") or defaults.style_preset).strip().lower()
        if style_preset not in SCENE_IMAGE_STYLE_PRESETS:
            style_preset = defaults.style_preset
        style_text = str(raw_book.get("style") or "").strip()
        if len(style_text) > 2000:
            raise ValueError("Art direction style must be 2,000 characters or fewer.")
        preset = STYLE_BY_ID.get(style_preset)
        if preset and style_text == preset["prompt"].strip():
            style_to_save = ""
        elif style_preset == "custom":
            style_to_save = style_text
        else:
            # Writer edited text while leaving preset selected -> save as custom if different
            if preset and style_text and style_text != preset["prompt"].strip():
                style_preset = "custom"
                style_to_save = style_text
            else:
                style_to_save = ""

        aspect_ratio = str(raw_book.get("aspect_ratio") or defaults.aspect_ratio).strip()
        if aspect_ratio not in SCENE_IMAGE_ASPECT_RATIOS:
            aspect_ratio = defaults.aspect_ratio
        raw_assets_dir = str(raw_book.get("assets_dir") or defaults.assets_dir).strip().replace("\\", "/")
        assets_dir = raw_assets_dir.rstrip("/") or defaults.assets_dir
        if ".." in Path(assets_dir).parts:
            raise ValueError("Scene asset folder cannot contain '..'.")

        raw_width = raw_book.get("width", defaults.width)
        try:
            width_val = int(raw_width)
        except (TypeError, ValueError):
            raise ValueError("Image width must be a whole number of pixels (120–1600).") from None
        if width_val < 120 or width_val > 1600:
            raise ValueError("Image width must be between 120 and 1600 pixels.")

        include_frontmatter = bool(raw_book.get("include_frontmatter", defaults.include_frontmatter))
        include_characters = bool(raw_book.get("include_characters", defaults.include_characters))
        instructions = bool(raw_book.get("instructions", defaults.instructions))

        prompt = str(raw_book.get("prompt") or "").strip()
        if len(prompt) > SUGGESTION_PROMPT_MAX:
            raise ValueError(f"Scene image prompt is too long (max {SUGGESTION_PROMPT_MAX} characters).")
        prompt_to_save = "" if (not prompt or prompt == DEFAULT_SCENE_IMAGE_PROMPT.strip()) else prompt

        cfg.with_overrides(
            scene_image=SceneImageConfig(
                agent=agent,
                model=model,
                style_preset=style_preset,
                style=style_to_save,
                aspect_ratio=aspect_ratio,
                assets_dir=assets_dir,
                width=width_val,
                include_frontmatter=include_frontmatter,
                include_characters=include_characters,
                instructions=instructions,
                prompt=prompt_to_save,
            )
        ).save(repo_root)
    return scene_image_settings_payload(repo_root)
