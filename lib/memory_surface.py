#!/usr/bin/env python3
"""memory_surface.py — taxonomy validation + catalog engine for tag-routed memory surfacing.

The SINGLE gated Python entry point for the memory hooks (the harness forbids per-tool-call
python; hooks cheap-gate in shell, then call this once). Phase 1 subcommands implemented here:

    validate      check taxonomy (_tags.md + _tag_links.md) integrity
    rebuild       regenerate _memory_catalog.json atomically from frontmatter (never bodies)
    check-write   validate a PROPOSED memory file's frontmatter/tags before it lands

Phase 2 will add: search / link / unlink / add-tag (token extraction, canonicalization, ranking).

Self-locates the box-brain store from $HOME ('/'->'-'); NEVER hardcodes the project key — the
pre-migration `-home-jangman` hardcode is exactly what broke the review-offer hook before.
Frontmatter parse/generate mirror _review_game.py's nested-metadata layout EXACTLY (see
[[fumble-restored-tool-read-ok-but-write-corrupts-on-format-drift]]) and additionally read the
block-list `tags:` form that _review_game.py's line parser silently drops.
"""
import datetime
import fnmatch
import hashlib
import json
import os
import re
import sys
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
META_ORDER = ["node_type", "type", "tags", "originSessionId",
              "lastReviewed", "declineCount", "nextEligible"]
FACET_HEADS = ("domain", "tool", "method-pattern")


# ---------------------------------------------------------------- store location
def resolve_memdir(explicit=None):
    if explicit:
        return Path(explicit)
    env = os.environ.get("MEMORY_SURFACE_DIR")
    if env:
        return Path(env)
    key = str(Path.home()).replace("/", "-")
    return Path.home() / ".claude" / "projects" / key / "memory"


# ---------------------------------------------------------------- frontmatter
def _parse_flow_tags(value):
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [t.strip().strip('"').strip("'") for t in value.split(",") if t.strip()]


def parse_frontmatter(text):
    """Return (top, meta, body). `meta['tags']` is a list (flow OR block form). Other meta
    values are raw strings. Top-level keeps name/description. Mirrors _review_game.py, plus
    block-list tag reading."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, {}, text
    body = text[m.end():]
    lines = m.group(1).split("\n")
    top, meta = {}, {}
    in_meta = False
    i = 0
    while i < len(lines):
        raw = lines[i]
        if not raw.strip():
            i += 1
            continue
        if raw[0] in (" ", "\t"):                      # indented -> metadata child
            if in_meta:
                s = raw.strip()
                if s.startswith("- "):                 # stray block item (consumed via tags)
                    i += 1
                    continue
                if ":" in s:
                    k, v = s.split(":", 1)
                    k, v = k.strip(), v.strip()
                    if k == "tags":
                        if v:
                            meta["tags"] = _parse_flow_tags(v)
                            i += 1
                            continue
                        tags, j = [], i + 1            # block list on following lines
                        while j < len(lines):
                            li = lines[j]
                            ls = li.strip()
                            if li.startswith("  ") and ls.startswith("- "):
                                tags.append(ls[2:].strip().strip('"').strip("'"))
                                j += 1
                            elif not ls:
                                j += 1
                            else:
                                break
                        meta["tags"] = tags
                        i = j
                        continue
                    meta[k] = v
            i += 1
            continue
        if ":" not in raw:                             # top-level
            i += 1
            continue
        k, v = raw.split(":", 1)
        k, v = k.strip(), v.strip()
        if k == "metadata":
            in_meta = True
        else:
            in_meta = False
            top[k] = v
        i += 1
    return top, meta, body


def generate_frontmatter(top, meta, body):
    """Re-emit preserving nested metadata + field order; tags as a flow list (canonical,
    matching _review_game.py). Unknown top/meta keys preserved in original order."""
    out = []
    for k in ("name", "description"):
        if k in top:
            out.append(f"{k}: {top[k]}")
    for k, v in top.items():
        if k not in ("name", "description"):
            out.append(f"{k}: {v}")
    out.append("metadata:")

    def emit(k, v):
        if k == "tags":
            tv = v if isinstance(v, list) else _parse_flow_tags(str(v))
            out.append(f"  tags: [{', '.join(tv)}]")
        else:
            out.append(f"  {k}: {v}")

    seen = set()
    for k in META_ORDER:
        if k in meta:
            emit(k, meta[k])
            seen.add(k)
    for k, v in meta.items():
        if k not in seen:
            emit(k, v)
    return "---\n" + "\n".join(out) + "\n---\n" + body


# ---------------------------------------------------------------- taxonomy parsers
def parse_tags_md(path):
    """Live faceted grammar: '## domain|tool|method-pattern' headings, '- tag — gloss' (em-dash)
    lines. Plus optional '## Denylist' and '## Policy overrides' sections (same line grammar)."""
    active, deny, overrides = {}, {}, set()
    if not path.exists():
        return {"active": active, "deny": deny, "overrides": overrides}
    section = None
    line_re = re.compile(r"^- ([a-z0-9][a-z0-9-]{1,39})\s+[—-]\s+(.+)$")
    for raw in path.read_text().split("\n"):
        h = raw.strip()
        if h.startswith("## "):
            n = h[3:].strip().lower()
            if n.startswith("denylist"):
                section = "deny"
            elif n.startswith("policy overrides"):
                section = "override"
            elif any(n.startswith(f) for f in FACET_HEADS):
                section = "active"
            else:
                section = None
            continue
        m = line_re.match(raw)
        if not m:
            continue
        tag, rest = m.group(1), m.group(2)
        if section == "active":
            active[tag] = rest
        elif section == "deny":
            deny[tag] = rest
        elif section == "override":
            overrides.add(tag)
    return {"active": active, "deny": deny, "overrides": overrides}


def parse_tag_links(path):
    """P6 backtick grammar: ## Synonyms ('- `a` = `b` - reason'), ## Distinctions
    ('- `a` != `b` - reason'), ## Path Tags ('- `pat` -> `t1`, `t2` [@ strong|weak] [; reason'])."""
    syn, dist, paths = [], [], []
    if not path.exists():
        return {"synonyms": syn, "distinctions": dist, "path_tags": paths}
    section = None
    for raw in path.read_text().split("\n"):
        h = raw.strip()
        if h.startswith("## "):
            section = {"synonyms": "syn", "distinctions": "dist",
                       "path tags": "path"}.get(h[3:].strip().lower())
            continue
        if not raw.startswith("- "):
            continue
        if section == "syn":
            m = re.match(r"^- `([a-z0-9-]+)` = `([a-z0-9-]+)`(?:\s+-\s+(.*))?$", raw)
            if m:
                syn.append((m.group(1), m.group(2), m.group(3) or ""))
        elif section == "dist":
            m = re.match(r"^- `([a-z0-9-]+)` != `([a-z0-9-]+)`(?:\s+-\s+(.*))?$", raw)
            if m:
                dist.append((m.group(1), m.group(2), m.group(3) or ""))
        elif section == "path":
            m = re.match(r"^- `([^`]+)`\s*->\s*(.+?)(?:\s+@\s+(strong|weak))?(?:\s+;\s+(.*))?$", raw)
            if m:
                tags = re.findall(r"`([a-z0-9-]+)`", m.group(2))
                paths.append((m.group(1), tags, m.group(3) or "strong", m.group(4) or ""))
    return {"synonyms": syn, "distinctions": dist, "path_tags": paths}


def synonym_map(synonyms):
    """alias -> canonical (left side is canonical)."""
    return {alias: canon for (canon, alias, _) in synonyms}


# ---------------------------------------------------------------- validation
def validate(memdir):
    tags = parse_tags_md(memdir / "_tags.md")
    links = parse_tag_links(memdir / "_tag_links.md")
    active = set(tags["active"])
    errors = []
    for t in sorted(active):
        if t in tags["deny"] and t not in tags["overrides"]:
            errors.append(f"active tag '{t}' is denylisted without a '## Policy overrides' entry")
    syn_pairs = set()
    alias_to_canon = {}
    for (c, a, _) in links["synonyms"]:
        if c not in active:                            # left=canonical must be a real tag;
            errors.append(f"synonym canonical '{c}' is not an active tag")
        if a in alias_to_canon and alias_to_canon[a] != c:   # §18: one synonym set per tag
            errors.append(f"tag '{a}' is an alias in multiple synonym sets "
                          f"('{alias_to_canon[a]}' and '{c}')")
        alias_to_canon[a] = c
        syn_pairs.add(frozenset((c, a)))               # right=alias is a free query token
    for (a, b, _) in links["distinctions"]:
        for t in (a, b):
            if t not in active:
                errors.append(f"distinction references unknown tag '{t}'")
        if frozenset((a, b)) in syn_pairs:
            errors.append(f"'{a}'/'{b}' are both a synonym and a distinction")
    for (pat, ptags, _, _) in links["path_tags"]:
        for t in ptags:
            if t not in active:
                errors.append(f"path-tag `{pat}` references unknown tag '{t}'")
    return errors


# ---------------------------------------------------------------- catalog
def _memory_files(memdir):
    for p in sorted(memdir.glob("*.md")):
        if p.name == "MEMORY.md" or p.name.startswith("_"):
            continue
        yield p


def fingerprint(memdir):
    h = hashlib.sha256()
    for name in ("_tags.md", "_tag_links.md"):
        p = memdir / name
        h.update(f"{name}:{p.stat().st_mtime_ns if p.exists() else 0}\0".encode())
    for p in _memory_files(memdir):
        h.update(f"{p.name}:{p.stat().st_mtime_ns}\0".encode())
    return "sha256:" + h.hexdigest()[:32]


def write_atomic(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def rebuild(memdir):
    tags = parse_tags_md(memdir / "_tags.md")
    active = set(tags["active"])
    smap = synonym_map(parse_tag_links(memdir / "_tag_links.md")["synonyms"])
    memories, invalid, tag_index = [], [], {}
    for p in _memory_files(memdir):
        top, meta, _ = parse_frontmatter(p.read_text())
        mtags = meta.get("tags", []) or []
        bad = [t for t in mtags if t not in active]
        if bad:
            invalid.append({"file": p.name, "error": f"unknown tags: {sorted(set(bad))}"})
            continue
        canon = sorted({smap.get(t, t) for t in mtags})
        desc = (top.get("description", "") or "").strip().strip('"').strip("'")
        try:
            decline = int(str(meta.get("declineCount", 0)).strip() or 0)
        except ValueError:
            decline = 0
        memories.append({
            "id": p.stem, "file": p.name, "path": str(p),
            "name": top.get("name", p.stem), "description": desc,
            "type": meta.get("type", ""), "tags": mtags, "canonicalTags": canon,
            "lastReviewed": (meta.get("lastReviewed", "") or "").strip(),
            "declineCount": decline,
        })
        for t in canon:
            tag_index.setdefault(t, []).append(p.stem)
    catalog = {
        "schemaVersion": 1,
        "sourceFingerprint": fingerprint(memdir),
        "generatedAt": datetime.date.today().isoformat(),
        "memoryDir": str(memdir),
        "activeTags": sorted(active),
        "memories": memories,
        "tagToMemoryIds": tag_index,
        "invalidMemories": invalid,
    }
    write_atomic(memdir / "_memory_catalog.json",
                 json.dumps(catalog, indent=1, ensure_ascii=False) + "\n")
    return catalog


# ---------------------------------------------------------------- check-write
def _closest(tag, active, n=3):
    def score(a):
        if a.startswith(tag[:3]) or tag.startswith(a[:3]):
            common = len(set(tag) & set(a))
            return (1, common)
        return (0, len(set(tag) & set(a)))
    return [a for a, _ in sorted(((a, score(a)) for a in active),
                                 key=lambda x: x[1], reverse=True)[:n]]


def check_write(memdir, content):
    tags = parse_tags_md(memdir / "_tags.md")
    active = set(tags["active"])
    top, meta, _ = parse_frontmatter(content)
    if "tags" in top:                                  # tags MUST nest under metadata: else they
        return 2, ("memory tags must be nested under 'metadata:' — found a top-level 'tags' key; "
                   "move it under the metadata: block so the tags are validated.")
    mtags = meta.get("tags", []) or []
    for t in mtags:
        if not TAG_RE.match(t):
            why = "malformed (must match ^[a-z0-9][a-z0-9-]{1,39}$)"
        elif t in tags["deny"] and t not in tags["overrides"]:
            why = "denylisted (too generic); use a specific tag or add a Policy override"
        elif t not in active:
            why = "not in _tags.md"
        else:
            continue
        close = _closest(t, active)
        hint = f"; closest active: {', '.join(close)}" if close else ""
        return 2, f"memory tag '{t}' is {why}{hint}. Add it to _tags.md first if it is genuinely new."
    return 0, ""


# ================================================================ Phase 2: search engine
# ---------------------------------------------------------------- config (§17)
DEFAULT_CONFIG = {
    "schemaVersion": 1, "enabled": True, "mode": "advisory",
    "requiredMode": "strict-high-confidence", "maxResults": 3, "maxRequiredReads": 2,
    "maxDescriptionChars": 220, "maxBlockChars": 4000, "dedupeTtlSeconds": 900,
    "obligationTtlSeconds": 1800, "confidenceHighThreshold": 10,
    "confidenceMediumThreshold": 6, "requireAllRequiredReads": False, "debug": False,
}


def load_config(memdir):
    cfg = dict(DEFAULT_CONFIG)
    p = memdir / "_memory_surface_config.json"
    if p.exists():
        try:
            user = json.loads(p.read_text())
            if isinstance(user, dict):
                cfg.update(user)
        except (json.JSONDecodeError, OSError):
            pass                                       # malformed config -> safe defaults
    return cfg


# ---------------------------------------------------------------- token extraction (§11)
GENERIC_BASH = {"ls", "pwd", "cd", "cat", "sed", "awk", "grep", "rg",
                "find", "head", "tail", "wc", "jq"}
GENERIC_TWO = {"git status", "git diff"}
INSTALLERS = {"pacman", "paru", "yay", "pip", "pip3", "npm", "pnpm", "yarn", "cargo", "apt"}
UNIT_RE = re.compile(r"\.(service|socket|timer|target|mount|path|scope)$")
_ENVVAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")    # leading VAR=val env assignment
_PRIVILEGE = {"sudo", "doas", "pkexec"}


def _pkgname(a):
    return re.split(r"[=<>@~!]", a, maxsplit=1)[0]      # strip a version specifier (nvidia=550.1)


def _norm(s):
    s = (s or "").strip().lower()
    return s if TAG_RE.match(s) else None


def _expand(pat):
    if pat == "~":
        return str(Path.home())
    if pat.startswith("~/"):
        return str(Path.home()) + pat[1:]
    return pat


def _abspath(path, cwd):
    if path.startswith("~"):
        return _expand(path)
    if path.startswith("/"):
        return path
    return (cwd.rstrip("/") + "/" + path) if cwd else path


def path_tag_hits(abspath, path_tags):
    """(tags, strength) for path-tag rules matching abspath. fnmatch.fnmatchcase; recursive
    ** only as a trailing /** suffix (§7)."""
    hits = []
    for (pat, tags, strength, _) in path_tags:
        p = _expand(pat)
        if p.endswith("/**"):
            prefix = p[:-3]
            if abspath == prefix or abspath.startswith(prefix + "/"):
                hits.append((tags, strength))
        elif "**" in p:
            continue                                   # ** is sanctioned ONLY as a trailing /** (§7)
        elif fnmatch.fnmatchcase(abspath, p):
            hits.append((tags, strength))
    return hits


def extract_tokens(event, active, aliases, path_tags, memdir):
    """Per-tool evidence extraction (§11). Returns {tokens, pathRuleTags}: tokens is a list of
    {value, kind, strength}; pathRuleTags is the set of tags emitted by matched path rules."""
    tool = event.get("tool_name", "") or ""
    ti = event.get("tool_input", {}) or {}
    cwd = event.get("cwd", "") or ""
    seen, tokens, path_rule_tags = set(), [], set()

    def add(value, kind, strength):
        v = _norm(value)
        if v and (v, kind) not in seen:
            seen.add((v, kind))
            tokens.append({"value": v, "kind": kind, "strength": strength})

    def add_path(raw):
        ap = _abspath(raw, cwd)
        for tags, _ in path_tag_hits(ap, path_tags):
            path_rule_tags.update(tags)
        base = ap.rsplit("/", 1)[-1]
        stem = base.rsplit(".", 1)[0] if "." in base[1:] else base   # keep leading-dot names (.bashrc)
        add(stem.lstrip("."), "path", "weak")
        for comp in ap.split("/"):
            add(comp.lstrip("."), "path", "weak")

    if tool == "Bash":
        for seg in re.split(r"\s*(?:;|&&|\|\||\|)\s*", ti.get("command", "") or ""):
            words = [w.strip("\"'") for w in seg.split()]           # strip surrounding quotes
            while words and (words[0] in _PRIVILEGE or _ENVVAR_RE.match(words[0])):
                words = words[1:]                                  # drop sudo/doas/pkexec / VAR=val prefix
            if not words:
                continue
            base = words[0].rsplit("/", 1)[-1]
            is_generic = base in GENERIC_BASH or " ".join(words[:2]) in GENERIC_TWO
            installer = base in INSTALLERS
            if not is_generic:
                add(base, "command", "weak")
            args = [w for w in words[1:] if not w.startswith("-")]
            if args and not is_generic and not installer:
                add(args[0], "argument", "strong")                 # generic/installer first-arg isn't strong
            if installer:
                pkgs = args[1:] if (args and args[0] in ("install", "add", "i", "remove", "rm")) else args
                for a in pkgs:
                    add(_pkgname(a), "package", "weak")            # version specifier stripped
            for w in words:
                if UNIT_RE.search(w):
                    add(UNIT_RE.sub("", w.rsplit("/", 1)[-1]), "unit", "strong")
                if w.startswith("/") or w.startswith("~/"):
                    add_path(w)
    elif tool == "Read":
        p = ti.get("file_path") or ti.get("path") or ""
        if p:
            add_path(p)
    elif tool in ("Edit", "Write", "MultiEdit"):
        p = ti.get("file_path") or ti.get("path") or ""
        ap = _abspath(p, cwd) if p else ""
        if ap and not (ap == str(memdir) or ap.startswith(str(memdir) + "/")):
            add_path(p)                                # memory writes route to write hooks, not recall
    elif tool == "WebSearch":
        # findall (not \W+ split) so hyphenated tags like 'plasma-compositor' survive intact
        for w in re.findall(r"[a-z0-9][a-z0-9-]*", (ti.get("query", "") or "").lower()):
            if w in active or w in aliases:
                add(w, "tag", "strong")
    elif tool == "WebFetch":
        for w in re.findall(r"[a-z0-9][a-z0-9-]*", (ti.get("url", "") or "").lower()):
            if w in active or w in aliases:            # host + path tokens; known tags/aliases only
                add(w, "tag", "strong")
    elif tool.startswith("mcp__") and "context7" in tool:
        for key in ("libraryName", "context7CompatibleLibraryID", "libraryId", "query"):
            val = ti.get(key)
            if val:
                for w in re.findall(r"[a-z0-9][a-z0-9-]*", str(val).lower()):
                    if w in active or w in aliases:
                        add(w, "tag", "strong")        # a library that IS a known tag = strong signal
                    else:
                        add(w, "package", "weak")
    return {"tokens": tokens, "pathRuleTags": path_rule_tags}


# ---------------------------------------------------------------- queryHash (§15)
def query_hash(tool_name, canonical_tags, strong_tokens):
    payload = "{}\0{}\0{}".format(tool_name, ",".join(sorted(canonical_tags)),
                                  ",".join(sorted(strong_tokens)))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- ranking (§12)
TYPE_PRIORITY = {"feedback": 0, "method": 1, "project": 2, "reference": 3, "todo": 4}


def _type_boost(t):
    return 1.0 if t in ("feedback", "method") else (0.5 if t == "project" else 0.0)


def _is_stale(last_reviewed, now):
    if not last_reviewed:
        return False
    try:
        return (now - datetime.date.fromisoformat(last_reviewed[:10])).days > 180
    except ValueError:
        return False


_CAT_PRIORITY = ["strong_exact", "path_rule", "synonym", "path_component", "command_pkg"]


def score_memory(mem, ext, active, aliases, distinctions, now):
    """(score, cats, matchedTags) for one memory vs evidence (§12). Each DISTINCT canonical
    tag is counted in exactly ONE category — its highest-priority match — so a tag matched by
    several tokens/mechanisms never stacks weights across categories."""
    ct = set(mem.get("canonicalTags", []))
    raw = set(mem.get("tags", []))
    slug = {p for p in mem.get("id", "").split("-") if p}
    rank = {c: i for i, c in enumerate(_CAT_PRIORITY)}
    best, strong_canon, slug_hits = {}, set(), set()

    def consider(ctag, cat):
        if ctag in ct and (ctag not in best or rank[cat] < rank[best[ctag]]):
            best[ctag] = cat

    for tok in ext["tokens"]:
        v = tok["value"]
        cv = aliases.get(v, v)
        if tok["strength"] == "strong" and cv in active:
            strong_canon.add(cv)
        if cv in ct:
            if tok["kind"] in ("tag", "argument"):
                consider(cv, "strong_exact" if v in raw else "synonym")
            elif tok["kind"] in ("command", "package", "unit"):
                consider(cv, "command_pkg")
            else:
                consider(cv, "path_component")
        if v in slug:
            slug_hits.add(v)
    for t in ext["pathRuleTags"] & ct:
        consider(t, "path_rule")
    strong_canon |= (ext["pathRuleTags"] & active)     # path rules are strong distinction evidence (§7)

    cats = {c: 0 for c in _CAT_PRIORITY}
    cats["slug"] = len(slug_hits)
    for cat in best.values():
        cats[cat] += 1

    conflict = 0
    for a, b in distinctions:
        if a in strong_canon and b in ct and a not in ct and b not in strong_canon:
            conflict += 1
        if b in strong_canon and a in ct and b not in ct and a not in strong_canon:
            conflict += 1
    stale = 1 if _is_stale(mem.get("lastReviewed", ""), now) else 0
    decline = min(int(mem.get("declineCount", 0) or 0), 3)
    score = (10 * cats["strong_exact"] + 9 * cats["path_rule"] + 7 * cats["synonym"]
             + 4 * cats["path_component"] + 3 * cats["command_pkg"] + 2 * cats["slug"]
             + _type_boost(mem.get("type", "")) - 5 * stale - 2 * decline - 8 * conflict)
    return score, cats, sorted(best.keys())


def _meets_min_candidate(cats):
    return (cats["strong_exact"] >= 1 or cats["synonym"] >= 1 or cats["path_rule"] >= 1
            or (cats["path_component"] + cats["command_pkg"]) >= 2)


def _confidence(score, cats, cfg):
    support = (cats["path_rule"] + cats["synonym"] + cats["command_pkg"]
               + cats["path_component"] + cats["slug"])
    if score >= cfg.get("confidenceHighThreshold", 10) or (cats["strong_exact"] >= 1 and support >= 1):
        return "high"
    if score >= cfg.get("confidenceMediumThreshold", 6):
        return "medium"
    return "low"


# ---------------------------------------------------------------- surface block (§16)
def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _trunc_escaped(s, n):
    """Escape first, THEN truncate to <= n chars without splitting an &entity; (§16 ordering)."""
    e = _esc(s)
    if len(e) <= n:
        return e
    cut = e[:n - 1]
    amp = cut.rfind("&")
    if amp != -1 and ";" not in cut[amp:]:             # don't cut a half-written entity
        cut = cut[:amp]
    return cut.rstrip() + "…"


def surface_text(query_id, mode, confidence, results, cfg):
    maxd = cfg.get("maxDescriptionChars", 220)
    out = [f'<memory-recall query-id="{_esc(query_id)}" mode="{_esc(mode)}" '
           f'confidence="{_esc(confidence)}">', "Possible memory match for this tool call.", ""]
    for i, r in enumerate(results, 1):
        out += [f"{i}. {_esc(r['file'])}", f"   path: {_esc(r['path'])}",
                f"   why: matched {_esc(', '.join(r['matchedTags']))}",
                f"   note: {_trunc_escaped(r['description'], maxd)}"]
    out.append("</memory-recall>")
    block = "\n".join(out)
    maxb = cfg.get("maxBlockChars", 4000)
    return block if len(block) <= maxb else block[:maxb - 14].rstrip() + "\n…(truncated)"


# ---------------------------------------------------------------- search (§10)
def _neg_date(s):
    try:
        return -datetime.date.fromisoformat(s[:10]).toordinal()
    except (ValueError, TypeError):
        return 0


def _load_catalog(memdir):
    # Missing/corrupt catalog -> fail CLOSED (None): search surfaces nothing rather than calling
    # rebuild() here, which would read memory frontmatter during a search (§19 / bodies-never-loaded).
    # Catalog freshness is the PostToolUse catalog-refresh hook's job, not search's.
    p = memdir / "_memory_catalog.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _response_mode(cfg):
    # §10/§16 response-mode vocabulary is advisory|required, NOT the raw config mode string.
    return "required" if cfg.get("mode") == "strict-high-confidence" else "advisory"


def _empty_response(mode):
    return {"schemaVersion": 1, "queryId": "memq_00000000", "mode": mode, "confidence": "low",
            "tokens": [], "canonicalTags": [], "results": [], "surfaceText": ""}


def search(memdir, event, now=None):
    now = now or datetime.date.today()
    cfg = load_config(memdir)
    rmode = _response_mode(cfg)
    if not cfg.get("enabled", True) or cfg.get("mode") == "disabled" \
            or (memdir / ".surface-disabled").exists():
        return _empty_response(rmode)
    catalog = _load_catalog(memdir)
    if catalog is None:                                # missing/corrupt catalog -> fail closed
        return _empty_response(rmode)
    tags = parse_tags_md(memdir / "_tags.md")
    active = set(tags["active"])
    links = parse_tag_links(memdir / "_tag_links.md")
    aliases = synonym_map(links["synonyms"])
    distinctions = [(a, b) for (a, b, _) in links["distinctions"]]
    ext = extract_tokens(event, active, aliases, links["path_tags"], memdir)
    tokens = ext["tokens"]
    canon_tags = sorted({aliases.get(t["value"], t["value"]) for t in tokens
                         if aliases.get(t["value"], t["value"]) in active}
                        | (ext["pathRuleTags"] & active))   # path-rule tags are canonical too (§10/§15)
    strong_tokens = sorted({t["value"] for t in tokens if t["strength"] == "strong"})
    qhash = query_hash(event.get("tool_name", "") or "", canon_tags, strong_tokens)
    qid = "memq_" + qhash.split(":")[1][:12]
    scored = []
    for mem in catalog.get("memories", []):
        score, cats, matched = score_memory(mem, ext, active, aliases, distinctions, now)
        if _meets_min_candidate(cats):
            scored.append((score, cats, matched, mem))
    scored.sort(key=lambda x: (
        -x[0], -x[1]["strong_exact"],
        1 if (x[1]["strong_exact"] == 0 and x[1]["synonym"] > 0) else 0,   # direct over synonym-only
        TYPE_PRIORITY.get(x[3].get("type", ""), 9),
        _neg_date(x[3].get("lastReviewed", "")), x[3].get("file", "")))
    top = scored[:cfg.get("maxResults", 3)]
    confidence = _confidence(top[0][0], top[0][1], cfg) if top else "low"
    strict = cfg.get("mode") == "strict-high-confidence"
    results = []
    for score, _, matched, mem in top:
        results.append({
            "id": mem["id"], "path": mem["path"], "file": mem["file"], "name": mem["name"],
            "description": mem["description"], "tags": mem["tags"], "matchedTags": matched,
            "score": score, "mustRead": confidence == "high" and strict,
        })
    return {"schemaVersion": 1, "queryId": qid, "mode": rmode, "confidence": confidence,
            "tokens": tokens, "canonicalTags": canon_tags, "results": results,
            "surfaceText": surface_text(qid, rmode, confidence, results, cfg) if results else ""}


# ---------------------------------------------------------------- taxonomy mutators
def _sanitize(s):
    """Collapse newlines/backticks so a free-text reason/description can't smuggle a new
    taxonomy line (`- \\`x\\` = \\`y\\``) or active-tag line past validation."""
    return re.sub(r"[\r\n`]+", " ", (s or "")).strip()


def _drop_pair_lines(text, a, b, op):
    """Remove any '- `x` <op> `y`' line whose backtick pair equals {a, b} (op is '=' or '!=')."""
    pat = re.compile(r"^- `([a-z0-9-]+)` " + re.escape(op) + r" `([a-z0-9-]+)`")
    return "\n".join(ln for ln in text.split("\n")
                     if not ((m := pat.match(ln)) and {m.group(1), m.group(2)} == {a, b}))


def _insert_under_heading(text, heading, line):
    """Insert `line` as the last entry under '## {heading}', creating the heading at EOF if
    absent. Returns the new text (caller writes atomically)."""
    lines = text.split("\n")
    target = "## " + heading
    hi = next((i for i, ln in enumerate(lines) if ln.strip() == target), None)
    if hi is None:
        return text.rstrip("\n") + "\n\n" + target + "\n" + line + "\n"
    last = hi
    j = hi + 1
    while j < len(lines) and not lines[j].strip().startswith("## "):
        if lines[j].strip():
            last = j
        j += 1
    lines.insert(last + 1, line)
    return "\n".join(lines)


def _mutate_then_validate(memdir, path, old_text, new_text):
    """Write new_text atomically; roll back only if it introduces a NEW validation error
    (pre-existing unrelated errors must not block an edit). Rebuild on success, and fail closed
    (rollback) if rebuild raises so the taxonomy and catalog never diverge."""
    pre = set(validate(memdir))
    write_atomic(path, new_text if new_text.endswith("\n") else new_text + "\n")
    new_errs = [e for e in validate(memdir) if e not in pre]
    if new_errs:
        write_atomic(path, old_text)
        rc = 3 if any(("both a synonym and a distinction" in e
                       or "multiple synonym sets" in e) for e in new_errs) else 2   # §10: 3 = graph
        return rc, "validation failed (rolled back): " + "; ".join(new_errs)
    try:
        rebuild(memdir)
    except Exception as e:                             # taxonomy already written -> roll back
        write_atomic(path, old_text)
        return 2, f"rebuild failed after mutation (rolled back): {e}"
    return 0, ""


def add_tag(memdir, tag, description="", facet="tool"):
    if not TAG_RE.match(tag):
        return 2, f"tag '{tag}' is malformed"
    if facet not in FACET_HEADS:
        return 2, f"facet must be one of {FACET_HEADS}"
    desc = _sanitize(description)
    if not (6 <= len(desc.split()) <= 32):             # §6/§18: substantive 6-32-word gloss
        return 2, f"tag description must be 6-32 words (got {len(desc.split())})"
    tags = parse_tags_md(memdir / "_tags.md")
    if tag in tags["active"]:
        return 0, f"tag '{tag}' already active"
    if tag in tags["deny"] and tag not in tags["overrides"]:
        return 2, f"tag '{tag}' is denylisted; add a Policy override first"
    path = memdir / "_tags.md"
    old = path.read_text() if path.exists() else "# tags\n"
    new = _insert_under_heading(old, facet, f"- {tag} — {desc}")
    rc, msg = _mutate_then_validate(memdir, path, old, new)
    return rc, msg or f"added tag '{tag}' under '{facet}'"


def link(memdir, a, b, reason=""):
    for t in (a, b):
        if not TAG_RE.match(t):
            return 2, f"tag '{t}' is malformed"
    path = memdir / "_tag_links.md"
    old = path.read_text() if path.exists() else "# tag links\n"
    r = _sanitize(reason)
    suffix = f" - {r}" if r else ""
    cleaned = _drop_pair_lines(old, a, b, "!=")        # §7: link removes any distinction between a,b
    new = _insert_under_heading(cleaned, "Synonyms", f"- `{a}` = `{b}`{suffix}")
    rc, msg = _mutate_then_validate(memdir, path, old, new)
    return rc, msg or f"linked `{a}` = `{b}`"


def unlink(memdir, a, b, distinguish=False, reason=""):
    for t in (a, b):
        if not TAG_RE.match(t):
            return 2, f"tag '{t}' is malformed"
    path = memdir / "_tag_links.md"
    old = path.read_text() if path.exists() else "# tag links\n"
    if distinguish:
        r = _sanitize(reason)
        suffix = f" - {r}" if r else ""
        cleaned = _drop_pair_lines(old, a, b, "=")     # §7: distinguishing removes any synonym
        new = _insert_under_heading(cleaned, "Distinctions", f"- `{a}` != `{b}`{suffix}")
    else:
        new = _drop_pair_lines(old, a, b, "=")         # drop the a=b / b=a synonym edge
    rc, msg = _mutate_then_validate(memdir, path, old, new)
    verb = "distinguished" if distinguish else "unlinked"
    return rc, msg or f"{verb} `{a}` / `{b}`"


def dismiss(query_id, reason):
    # Obligation state is Phase 4 (strict mode). In Phase 2 (advisory) there is no obligation
    # to dismiss; succeed and record intent. (No-op until strict mode ships.)
    return 0, f"dismiss noted (advisory; no obligation state in Phase 2): {query_id} — {reason}"


# ---------------------------------------------------------------- CLI
def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


VALUE_FLAGS = {"--memory-dir", "--reason", "--description", "--event",
               "--content-file", "--query-id", "--facet"}


def _positionals():
    out, i, argv = [], 2, sys.argv
    while i < len(argv):
        a = argv[i]
        if a in VALUE_FLAGS:
            i += 2
        elif a.startswith("--"):
            i += 1
        else:
            out.append(a)
            i += 1
    return out


def _err(msg):
    print(msg, file=sys.stderr)
    return 2


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    memdir = resolve_memdir(_arg("--memory-dir"))
    if not memdir.is_dir():
        return 0                                       # fail open: no store, nothing to do
    if cmd == "validate":
        errs = validate(memdir)
        for e in errs:
            print(e, file=sys.stderr)
        return 0 if not errs else 2
    if cmd == "rebuild":
        cat = rebuild(memdir)
        if cat["invalidMemories"]:
            print(json.dumps({"invalidMemories": cat["invalidMemories"]}), file=sys.stderr)
        return 0
    if cmd == "check-write":
        cf = _arg("--content-file")
        content = Path(cf).read_text() if cf else sys.stdin.read()
        rc, msg = check_write(memdir, content)
        if rc:
            print(msg)
        return rc
    if cmd == "search":
        ef = _arg("--event")
        event = json.loads((Path(ef).read_text() if ef else sys.stdin.read()) or "{}")
        print(json.dumps(search(memdir, event), ensure_ascii=False))
        return 0
    if cmd in ("link", "unlink", "add-tag", "dismiss"):
        pos = _positionals()
        if cmd == "link":
            if len(pos) < 2:
                return _err("usage: link <a> <b> [--reason R]")
            rc, msg = link(memdir, pos[0], pos[1], _arg("--reason", ""))
        elif cmd == "unlink":
            if len(pos) < 2:
                return _err("usage: unlink <a> <b> [--distinguish] [--reason R]")
            rc, msg = unlink(memdir, pos[0], pos[1], "--distinguish" in sys.argv, _arg("--reason", ""))
        elif cmd == "add-tag":
            if len(pos) < 1:
                return _err("usage: add-tag <tag> [--description D] [--facet domain|tool|method-pattern]")
            rc, msg = add_tag(memdir, pos[0], _arg("--description", ""), _arg("--facet", "tool"))
        else:
            rc, msg = dismiss(_arg("--query-id", ""), _arg("--reason", ""))
        print(msg, file=(sys.stderr if rc else sys.stdout))
        return rc
    print(f"unknown command: {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
