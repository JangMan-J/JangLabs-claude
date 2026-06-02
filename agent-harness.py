#!/usr/bin/env python3
"""agent-harness.py — install / remove / inspect the Claude Code harness for this box.

Supersedes the former install.sh + uninstall.sh bash pair with one idempotent CLI.
Dry-run by default; pass --apply to commit. JSON is merged natively (no jq dependency).

    agent-harness.py install [--apply]   symlink hooks + memory assets, merge the
                                         CLAUDE.md fragment and settings hooks into ~/.claude
    agent-harness.py remove  [--apply]   reverse exactly what install adds (symmetric)
    agent-harness.py status              report what is currently installed (read-only)

Only the `hooks` block of settings.json is ever touched — `permissions` (allow/deny,
defaultMode, bypass flags) is the user's alone, mirrored at runtime by config-drift-guard.sh.
Hook command paths are rewritten to this host's $HOME/.claude/hooks at merge time, so the
settings fragment stays host-agnostic regardless of the literal 'HOOKS_DIR/' it stores.

Settings merge semantics (the fix over the old jq merge): each hook command from the
fragment is reconciled into settings.json at PER-COMMAND granularity within its
(event, matcher) — a hook can be added INTO an existing matcher block, and a command
already present anywhere in that event is never duplicated. The old merge deduped whole
matcher blocks by their first command, so adding a hook into an existing block was a
silent no-op (it forced every hook into its own block).
"""
from __future__ import annotations

import argparse
import copy
import datetime
import difflib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import NoReturn

LAB_DIR = Path(__file__).resolve().parent
HOOKS_SRC = LAB_DIR / "hooks"
MEMORY_SRC = LAB_DIR / "memory"
FRAGMENT_SRC = LAB_DIR / "CLAUDE.md.fragment"
FRAG_JSON = LAB_DIR / "settings.global.fragment.json"

CLAUDE_HOME = Path(os.environ.get("CLAUDE_HOME") or (Path.home() / ".claude"))
HOOKS_DST = CLAUDE_HOME / "hooks"
CLAUDE_MD = CLAUDE_HOME / "CLAUDE.md"
SETTINGS = CLAUDE_HOME / "settings.json"

# Box-brain memory store: keyed to $HOME ('/' -> '-'), NEVER hardcoded — the
# pre-migration `-home-jangman` hardcode is exactly what stranded the hooks before.
PROJECT_KEY = str(Path.home()).replace("/", "-")
MEMDIR = CLAUDE_HOME / "projects" / PROJECT_KEY / "memory"

BEGIN_TAG = "# --- begin Claude-Lab harness fragment ---"
END_TAG = "# --- end Claude-Lab harness fragment ---"
BLOCK_RE = re.compile(re.escape(BEGIN_TAG) + r".*?" + re.escape(END_TAG), re.DOTALL)
BLOCK_RE_TRIM = re.compile(
    r"\n?" + re.escape(BEGIN_TAG) + r".*?" + re.escape(END_TAG) + r"\n?", re.DOTALL
)

# Lab-sourced memory assets are symlinked into the store; generated artifacts never are.
GENERATED_MEMORY = {"_memory_catalog.json", "_memory_surface_config.json"}


# --------------------------------------------------------------------- helpers
def log(apply: bool, msg: str) -> None:
    print(f"[{'apply' if apply else 'dry  '}] {msg}")


def die(msg: str) -> NoReturn:
    print(msg, file=sys.stderr)
    sys.exit(1)


def _ts() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def write_atomic(path: Path, text: str) -> None:
    """Write via a sibling temp file + os.replace so a crash can't truncate the target."""
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(text)
    os.replace(tmp, path)


def load_settings_or_die() -> dict:
    """Parse ~/.claude/settings.json, or die with a clean message (never a raw traceback) —
    returns {} if absent. The harness invites hand-editing settings.json, so a momentarily
    broken file is plausible; fail clearly and leave the file untouched."""
    if not SETTINGS.exists():
        return {}
    try:
        data = json.loads(SETTINGS.read_text())
    except json.JSONDecodeError as e:
        die(f"{SETTINGS} is not valid JSON ({e}); left untouched. Fix it and re-run.")
    if not isinstance(data, dict):
        die(f"{SETTINGS} top-level is not a JSON object; left untouched. Fix it and re-run.")
    if "hooks" in data and not isinstance(data["hooks"], dict):
        die(f"{SETTINGS} 'hooks' is not an object; left untouched. Fix it and re-run.")
    return data


def backup(path: Path, backup_root: Path, apply: bool) -> None:
    """Copy `path` under a timestamped mirror tree, preserving symlinks (cp -a parity)."""
    if not path.exists() and not path.is_symlink():
        return
    if apply:
        dest = Path(str(backup_root) + str(path))
        dest.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            os.symlink(os.readlink(path), dest)
        else:
            shutil.copy2(path, dest)
    log(apply, f"backed up {path} -> {backup_root}{path}")


def ensure_exec(src: Path, apply: bool) -> None:
    # Hooks are symlinked, not copied, so the installed hook's executability is the source's.
    # Only touch the bit when actually missing — avoids a needless working-tree write and a
    # PermissionError on a read-only checkout.
    if apply and not os.access(src, os.X_OK):
        os.chmod(src, os.stat(src).st_mode | 0o111)


def link(src: Path, dst: Path, backup_root: Path, apply: bool) -> None:
    """Idempotently point `dst` at `src` (absolute symlink). -L also catches a broken
    link left by a lab move, so re-running after a rename repairs it."""
    if dst.is_symlink() and os.readlink(dst) == str(src):
        log(apply, f"ok: {dst} -> {src} (already linked)")
        return
    if dst.exists() or dst.is_symlink():
        backup(dst, backup_root, apply)
        if apply:
            dst.unlink()
        log(apply, f"rm {dst}")
    if apply:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.symlink_to(src)
    log(apply, f"ln -s {src} {dst}")


def unlink_ours(src: Path, dst: Path, apply: bool) -> None:
    if dst.is_symlink() and os.readlink(dst) == str(src):
        if apply:
            dst.unlink()
        log(apply, f"rm {dst}")
    else:
        log(apply, f"skip: {dst} is not a symlink to our source")


def _memory_sources():
    if not MEMORY_SRC.is_dir():
        return
    for src in sorted(MEMORY_SRC.iterdir()):
        if not src.is_file() or src.name.startswith(".") or src.name in GENERATED_MEMORY:
            continue
        yield src


# --------------------------------------------------------------------- CLAUDE.md fragment
def fragment_text() -> str:
    """The fragment with its 'Managed by' line normalized to this checkout's path."""
    return re.sub(
        r"(?m)^# Managed by .*$",
        f"# Managed by {LAB_DIR}/agent-harness.py.",
        FRAGMENT_SRC.read_text(),
        count=1,
    )


def install_fragment(apply: bool, backup_root: Path) -> None:
    log(apply, "==> CLAUDE.md")
    text = fragment_text()
    if not CLAUDE_MD.exists():
        log(apply, f"creating {CLAUDE_MD}")
        if apply:
            CLAUDE_MD.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(CLAUDE_MD, text)
        return
    cur = CLAUDE_MD.read_text()
    if BEGIN_TAG in cur:
        new = BLOCK_RE.sub(lambda _: text.rstrip("\n"), cur, count=1)
        if new == cur:
            log(apply, "ok: CLAUDE.md fragment already up to date")
            return
        log(apply, f"fragment present in {CLAUDE_MD}; replacing in place")
        backup(CLAUDE_MD, backup_root, apply)
        if apply:
            write_atomic(CLAUDE_MD, new)
    else:
        log(apply, f"appending fragment to {CLAUDE_MD}")
        backup(CLAUDE_MD, backup_root, apply)
        if apply:
            write_atomic(CLAUDE_MD, cur.rstrip("\n") + "\n\n" + text)


def remove_fragment(apply: bool, backup_root: Path) -> None:
    log(apply, "==> CLAUDE.md")
    if CLAUDE_MD.exists() and BEGIN_TAG in CLAUDE_MD.read_text():
        backup(CLAUDE_MD, backup_root, apply)
        new = BLOCK_RE_TRIM.sub("", CLAUDE_MD.read_text(), count=1)
        if new and not new.endswith("\n"):
            new += "\n"
        if apply:
            write_atomic(CLAUDE_MD, new)
        log(apply, f"removed fragment from {CLAUDE_MD}")
    else:
        log(apply, f"no fragment present in {CLAUDE_MD}; nothing to remove")


# --------------------------------------------------------------------- settings.json
def load_fragment_hooks() -> dict:
    """Fragment hooks with every command path rewritten to this host's hooks dir."""
    frag = json.loads(FRAG_JSON.read_text())
    for blocks in frag.get("hooks", {}).values():
        for b in blocks:
            for h in b.get("hooks", []):
                if "command" in h:
                    h["command"] = str(HOOKS_DST / Path(h["command"]).name)
    return frag.get("hooks", {})


def merge_hooks(settings: dict, frag_hooks: dict) -> dict:
    """Reconcile fragment hooks into settings at per-command granularity within each
    (event, matcher). A command already present anywhere in the event is skipped, so the
    merge is idempotent and never duplicates a hook across blocks. NOTE: dedup is per-EVENT
    by design — a command may appear at most once per event; registering the same hook under
    two matchers of one event is intentionally unsupported (the second copy would be dropped)."""
    sh = settings.setdefault("hooks", {})
    for event, fblocks in frag_hooks.items():
        sblocks = sh.setdefault(event, [])
        present = {
            h["command"]
            for b in sblocks
            for h in b.get("hooks", [])
            if "command" in h
        }
        for fb in fblocks:
            matcher = fb.get("matcher")
            new_hooks = [h for h in fb.get("hooks", []) if h.get("command") not in present]
            if not new_hooks:
                continue
            target = next((b for b in sblocks if b.get("matcher") == matcher), None)
            if target is None:
                target = {"matcher": matcher} if matcher is not None else {}
                target["hooks"] = []
                sblocks.append(target)
            target.setdefault("hooks", [])
            for h in new_hooks:
                target["hooks"].append(copy.deepcopy(h))
                present.add(h.get("command"))
    return settings


def strip_hooks(settings: dict, our_cmds: set) -> dict:
    """Remove exactly our hook commands; drop emptied blocks, events, and the hooks key."""
    sh = settings.get("hooks")
    if not sh:
        return settings
    new_events = {}
    for event, blocks in sh.items():
        kept_blocks = []
        for b in blocks:
            kept = [h for h in b.get("hooks", []) if h.get("command") not in our_cmds]
            if kept:
                nb = {"matcher": b["matcher"]} if "matcher" in b else {}
                nb["hooks"] = kept
                kept_blocks.append(nb)
        if kept_blocks:
            new_events[event] = kept_blocks
    if new_events:
        settings["hooks"] = new_events
    else:
        settings.pop("hooks", None)
    return settings


def _print_diff(a: dict, b: dict) -> None:
    al = json.dumps(a, indent=2, sort_keys=True).split("\n")
    bl = json.dumps(b, indent=2, sort_keys=True).split("\n")
    for line in difflib.unified_diff(al, bl, "settings.json (current)",
                                     "settings.json (merged)", lineterm=""):
        print(line)


def install_settings(apply: bool, backup_root: Path) -> None:
    log(apply, "==> settings.json")
    if not FRAG_JSON.exists():
        die(f"missing {FRAG_JSON}")
    current = load_settings_or_die()
    merged = merge_hooks(copy.deepcopy(current), load_fragment_hooks())
    if json.dumps(current, sort_keys=True) == json.dumps(merged, sort_keys=True):
        log(apply, "ok: settings.json already up to date")
        return
    backup(SETTINGS, backup_root, apply)
    if apply:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(SETTINGS, json.dumps(merged, indent=2) + "\n")
        log(apply, "wrote merged settings.json")
    else:
        log(apply, "would write merged settings.json. diff:")
        _print_diff(current, merged)


def remove_settings(apply: bool, backup_root: Path) -> None:
    log(apply, "==> settings.json")
    if not SETTINGS.exists():
        log(apply, f"no {SETTINGS}; nothing to do")
        return
    our = {str(HOOKS_DST / s.name) for s in HOOKS_SRC.glob("*.sh")}
    current = load_settings_or_die()
    pruned = strip_hooks(copy.deepcopy(current), our)
    if json.dumps(current, sort_keys=True) == json.dumps(pruned, sort_keys=True):
        log(apply, "ok: no claude-harness hooks present in settings.json")
        return
    backup(SETTINGS, backup_root, apply)
    if apply:
        write_atomic(SETTINGS, json.dumps(pruned, indent=2) + "\n")
        log(apply, "stripped claude-harness hooks from settings.json")
    else:
        log(apply, "would strip claude-harness hooks. diff:")
        _print_diff(current, pruned)


# --------------------------------------------------------------------- commands
def _final(apply: bool, backup_root: Path, removed: bool = False) -> None:
    print()
    if not apply:
        print("DRY RUN. Re-run with --apply to commit.")
        return
    print(f"{'Uninstalled' if removed else 'Applied'}. Backups in {backup_root}")
    if not removed:
        print("Restart Claude Code (or run /reload-plugins) to pick up the changes.")


def cmd_install(apply: bool) -> None:
    # Pre-flight: validate sources + the existing settings BEFORE touching disk, so a missing
    # source or a hand-broken settings.json aborts up front rather than half-applying.
    for src in (HOOKS_SRC, FRAGMENT_SRC, FRAG_JSON):
        if not src.exists():
            die(f"missing required source: {src}")
    try:
        json.loads(FRAG_JSON.read_text())
    except json.JSONDecodeError as e:
        die(f"{FRAG_JSON} is not valid JSON ({e}).")
    load_settings_or_die()
    backup_root = LAB_DIR / ".install-backups" / _ts()
    log(apply, "==> hooks")
    for src in sorted(HOOKS_SRC.glob("*.sh")):
        link(src, HOOKS_DST / src.name, backup_root, apply)
        ensure_exec(src, apply)
    log(apply, "==> memory store assets")
    if not MEMDIR.is_dir():
        log(apply, f"skip: box-brain store {MEMDIR} does not exist yet (nothing to link into)")
    else:
        for src in _memory_sources():
            link(src, MEMDIR / src.name, backup_root, apply)
    install_fragment(apply, backup_root)
    install_settings(apply, backup_root)
    _final(apply, backup_root)


def cmd_remove(apply: bool) -> None:
    backup_root = LAB_DIR / ".uninstall-backups" / _ts()
    log(apply, "==> hooks")
    for src in sorted(HOOKS_SRC.glob("*.sh")):
        unlink_ours(src, HOOKS_DST / src.name, apply)
    log(apply, "==> memory store assets")
    for src in _memory_sources():
        unlink_ours(src, MEMDIR / src.name, apply)
    remove_fragment(apply, backup_root)
    remove_settings(apply, backup_root)
    _final(apply, backup_root, removed=True)


def cmd_status() -> None:
    def linkstate(src: Path, dst: Path) -> str:
        if dst.is_symlink():
            return "linked" if os.readlink(dst) == str(src) else f"-> {os.readlink(dst)} (other)"
        return "MISSING" if not dst.exists() else "present (not our symlink)"

    print("hooks:")
    for src in sorted(HOOKS_SRC.glob("*.sh")):
        print(f"  {src.name}: {linkstate(src, HOOKS_DST / src.name)}")

    print("memory store assets:")
    if not MEMDIR.is_dir():
        print(f"  (store {MEMDIR} absent)")
    else:
        for src in _memory_sources():
            print(f"  {src.name}: {linkstate(src, MEMDIR / src.name)}")

    present = CLAUDE_MD.exists() and BEGIN_TAG in CLAUDE_MD.read_text()
    print(f"CLAUDE.md fragment: {'present' if present else 'absent'}")

    settings: dict | None = {}
    if SETTINGS.exists():
        try:
            loaded = json.loads(SETTINGS.read_text())
            settings = loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError:
            settings = None
    if settings is None:
        print("settings.json hooks: UNPARSEABLE (left untouched)")
        return
    hooks = settings.get("hooks", {})
    registered = {
        h.get("command")
        for blocks in (hooks.values() if isinstance(hooks, dict) else [])
        for b in blocks
        for h in b.get("hooks", [])
    }
    print("settings.json hooks:")
    for src in sorted(HOOKS_SRC.glob("*.sh")):
        cmd = str(HOOKS_DST / src.name)
        print(f"  {src.name}: {'registered' if cmd in registered else 'NOT registered'}")


def main() -> None:
    p = argparse.ArgumentParser(
        prog="agent-harness.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")
    for name, aliases in (("install", []), ("remove", ["uninstall"]), ("status", [])):
        sp = sub.add_parser(name, aliases=aliases)
        if name != "status":
            g = sp.add_mutually_exclusive_group()
            g.add_argument("--apply", action="store_true",
                           help="commit changes (default: dry-run preview)")
            g.add_argument("--dry-run", action="store_true",
                           help="preview only (the default)")
    args = p.parse_args()
    cmd = args.cmd or "status"
    if cmd in ("remove", "uninstall"):
        cmd_remove(getattr(args, "apply", False))
    elif cmd == "status":
        cmd_status()
    else:
        cmd_install(getattr(args, "apply", False))


if __name__ == "__main__":
    main()
