#!/usr/bin/env python3
"""Phase-2 tests for memory_surface.py — token extraction, canonicalization, path-tag
matching, ranking, queryHash, confidence, search response, config modes, and mutators.

Fixture memory IDs are OPAQUE (rec-a … rec-h) so slug matches don't contaminate the
ranking math; slug scoring is tested separately. Frozen against now=2026-06-02 so stale
penalties are deterministic. No third-party deps.
Run:  python3 claude/tests/memory_surface/test_phase2.py
"""
import datetime
import hashlib
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

LAB = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(LAB / "lib"))
import memory_surface as ms                            # noqa: E402

NOW = datetime.date(2026, 6, 2)

TAGS_MD = """\
# tags
## domain
- nvidia — gpu
- kde-wayland — wayland path
- kde-x11 — x11 path
- terminal-theme — terminal theming
## tool
- kwin — window manager
- plasma-compositor — compositor (alias of kwin)
- git — version control
- tailscale — vpn
- rustdesk — remote desktop
- kitty — terminal
- zsh — shell
## method-pattern
- verify-live — check the live artifact
## Denylist
- config — too generic
## Policy overrides
"""

LINKS_MD = """\
# tag links
## Synonyms
- `kwin` = `plasma-compositor` - kwin is the compositor for retrieval
## Distinctions
- `kde-wayland` != `kde-x11` - the paths diverge on this box
## Path Tags
- `~/.config/kitty/**` -> `kitty`, `terminal-theme`
- `~/.zshenv` -> `zsh`
"""


def _mem(name, tags, type_="feedback", last="2026-05-01", decline=0):
    return (
        f"---\nname: {name}\ndescription: \"about {name}\"\nmetadata:\n"
        f"  node_type: memory\n  type: {type_}\n  tags: [{', '.join(tags)}]\n"
        f"  lastReviewed: {last}\n  declineCount: {decline}\n---\n\nbody of {name}\n"
    )


MEMORIES = {
    "rec-a.md": _mem("rec-a", ["kwin"]),
    "rec-b.md": _mem("rec-b", ["plasma-compositor"]),
    "rec-c.md": _mem("rec-c", ["kde-wayland"]),
    "rec-d.md": _mem("rec-d", ["kde-x11", "git"]),
    "rec-e.md": _mem("rec-e", ["kitty", "terminal-theme"], type_="project"),
    "rec-f.md": _mem("rec-f", ["zsh"]),
    "rec-g.md": _mem("rec-g", ["git"], last="2025-01-01"),       # stale (>180d before NOW)
    "rec-h.md": _mem("rec-h", ["nvidia"], decline=2),
}


def make_store(tmp, tags=TAGS_MD, links=LINKS_MD, memories=MEMORIES, config=None):
    (tmp / "_tags.md").write_text(tags)
    (tmp / "_tag_links.md").write_text(links)
    for fn, body in memories.items():
        (tmp / fn).write_text(body)
    if config is not None:
        (tmp / "_memory_surface_config.json").write_text(json.dumps(config))
    ms.rebuild(tmp)
    return tmp


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.store = Path(self._td.name)
        make_store(self.store)

    def tearDown(self):
        self._td.cleanup()

    def _search(self, event, **kw):
        return ms.search(self.store, event, now=NOW, **kw)

    def _by_id(self, resp):
        return {r["id"]: r for r in resp["results"]}


class TokenExtraction(Base):
    def test_websearch_known_tags_only(self):
        r = self._search({"tool_name": "WebSearch",
                          "tool_input": {"query": "kwin foobar totally-unknown nonsense"}})
        self.assertEqual([(t["value"], t["kind"], t["strength"]) for t in r["tokens"]],
                         [("kwin", "tag", "strong")])

    def test_generic_bash_silent(self):
        r = self._search({"tool_name": "Bash", "tool_input": {"command": "ls -la"}, "cwd": "/tmp"})
        self.assertEqual(r["tokens"], [])
        self.assertEqual(r["results"], [])

    def test_bash_unit_and_arg(self):
        r = self._search({"tool_name": "Bash",
                          "tool_input": {"command": "systemctl restart tailscale.service"}, "cwd": "/"})
        kinds = {t["value"]: (t["kind"], t["strength"]) for t in r["tokens"]}
        self.assertEqual(kinds.get("tailscale"), ("unit", "strong"))
        self.assertEqual(kinds.get("restart"), ("argument", "strong"))

    def test_edit_on_memory_path_is_skipped(self):
        r = self._search({"tool_name": "Edit",
                          "tool_input": {"file_path": str(self.store / "rec-a.md"),
                                         "new_string": "x"}, "cwd": "/"})
        self.assertEqual(r["tokens"], [])               # memory writes route to write hooks

    def test_context7_known_lib_is_strong(self):
        r = self._search({"tool_name": "mcp__plugin_context7_context7__get-library-docs",
                          "tool_input": {"libraryName": "tailscale"}})
        self.assertTrue(any(t["value"] == "tailscale" and t["strength"] == "strong"
                            for t in r["tokens"]))


class PathTags(unittest.TestCase):
    def test_double_star_suffix(self):
        pts = [("~/.config/kitty/**", ["kitty"], "strong", "")]
        home = str(Path.home())
        self.assertTrue(ms.path_tag_hits(home + "/.config/kitty/theme.conf", pts))
        self.assertTrue(ms.path_tag_hits(home + "/.config/kitty/sub/x", pts))
        self.assertFalse(ms.path_tag_hits(home + "/.config/other/x", pts))

    def test_tilde_only_expansion(self):
        pts = [("~/.zshenv", ["zsh"], "strong", "")]
        self.assertTrue(ms.path_tag_hits(str(Path.home()) + "/.zshenv", pts))
        self.assertFalse(ms.path_tag_hits("/etc/zshenv", pts))


class Ranking(Base):
    def test_direct_vs_synonym(self):
        r = self._search({"tool_name": "WebSearch", "tool_input": {"query": "kwin"}})
        by = self._by_id(r)
        self.assertEqual(by["rec-a"]["score"], 11.0)         # 10 strong_exact + 1 feedback
        self.assertEqual(by["rec-b"]["score"], 8.0)          # 7 synonym + 1 feedback
        self.assertEqual(r["results"][0]["id"], "rec-a")
        self.assertEqual(r["confidence"], "high")

    def test_synonym_symmetry(self):
        r = self._search({"tool_name": "WebSearch", "tool_input": {"query": "plasma-compositor"}})
        by = self._by_id(r)
        self.assertEqual(by["rec-b"]["score"], 11.0)         # direct
        self.assertEqual(by["rec-a"]["score"], 8.0)          # via synonym
        self.assertEqual(r["canonicalTags"], ["kwin"])

    def test_path_rule(self):
        r = self._search({"tool_name": "Read", "tool_input": {"file_path": "~/.zshenv"}, "cwd": "/"})
        by = self._by_id(r)
        self.assertEqual(by["rec-f"]["score"], 10.0)         # 9 path_rule + 1 feedback
        self.assertEqual(r["confidence"], "high")

    def test_stale_penalty(self):
        r = self._search({"tool_name": "WebSearch", "tool_input": {"query": "git"}})
        by = self._by_id(r)
        self.assertEqual(by["rec-g"]["score"], 6.0)          # 10 + 1 - 5 stale
        self.assertEqual(by["rec-d"]["score"], 11.0)         # fresh

    def test_decline_penalty(self):
        r = self._search({"tool_name": "WebSearch", "tool_input": {"query": "nvidia"}})
        by = self._by_id(r)
        self.assertEqual(by["rec-h"]["score"], 7.0)          # 10 + 1 - 2*min(2,3)
        self.assertEqual(r["confidence"], "medium")          # strong_exact but no support, <10

    def test_distinction_conflict_suppresses_wrong_side(self):
        r = self._search({"tool_name": "WebSearch", "tool_input": {"query": "kde-wayland git"}})
        by = self._by_id(r)
        self.assertEqual(by["rec-c"]["score"], 11.0)
        self.assertEqual(by["rec-d"]["score"], 3.0)          # 10 git + 1 - 8 conflict
        order = [x["id"] for x in r["results"]]
        self.assertLess(order.index("rec-g"), order.index("rec-d"))  # wrong-side sinks below plain git

    def test_slug_match_adds_two(self):
        mem = {"id": "foo-kwin-bar", "tags": ["kwin"], "canonicalTags": ["kwin"],
               "type": "feedback", "lastReviewed": "2026-05-01", "declineCount": 0}
        ext = {"tokens": [{"value": "kwin", "kind": "tag", "strength": "strong"}], "pathRuleTags": set()}
        score, cats, _ = ms.score_memory(mem, ext, {"kwin"}, {}, [], NOW)
        self.assertEqual(cats["strong_exact"], 1)
        self.assertEqual(cats["slug"], 1)
        self.assertEqual(score, 13.0)                        # 10 + 2 slug + 1 feedback


class MinCandidate(Base):
    def test_thresholds(self):
        z = {"strong_exact": 0, "synonym": 0, "path_rule": 0,
             "path_component": 0, "command_pkg": 0, "slug": 0}
        self.assertTrue(ms._meets_min_candidate({**z, "strong_exact": 1}))
        self.assertTrue(ms._meets_min_candidate({**z, "synonym": 1}))
        self.assertTrue(ms._meets_min_candidate({**z, "path_rule": 1}))
        self.assertFalse(ms._meets_min_candidate({**z, "command_pkg": 1}))           # 1 weak
        self.assertFalse(ms._meets_min_candidate({**z, "slug": 5}))                  # slug alone never
        self.assertTrue(ms._meets_min_candidate({**z, "command_pkg": 1, "path_component": 1}))  # 2 weak

    def test_single_weak_does_not_surface(self):
        r = self._search({"tool_name": "Bash", "tool_input": {"command": "kitty"}, "cwd": "/"})
        self.assertEqual(r["results"], [])               # 1 command match, opaque id => no slug


class QueryHash(Base):
    def test_deterministic_and_formula(self):
        h = ms.query_hash("WebSearch", ["kwin", "git"], ["kwin"])
        self.assertEqual(h, "sha256:" + hashlib.sha256("WebSearch\0git,kwin\0kwin".encode()).hexdigest())
        self.assertEqual(h, ms.query_hash("WebSearch", ["git", "kwin"], ["kwin"]))   # order-independent

    def test_queryid_stable_across_now(self):
        ev = {"tool_name": "WebSearch", "tool_input": {"query": "kwin"}}
        a = ms.search(self.store, ev, now=datetime.date(2020, 1, 1))["queryId"]
        b = ms.search(self.store, ev, now=datetime.date(2030, 1, 1))["queryId"]
        self.assertEqual(a, b)                           # hash excludes the date

    def test_different_events_differ(self):
        a = self._search({"tool_name": "WebSearch", "tool_input": {"query": "kwin"}})["queryId"]
        b = self._search({"tool_name": "WebSearch", "tool_input": {"query": "git"}})["queryId"]
        self.assertNotEqual(a, b)


class SearchResponse(Base):
    def test_schema_shape(self):
        r = self._search({"tool_name": "WebSearch", "tool_input": {"query": "kwin"}})
        for k in ("schemaVersion", "queryId", "mode", "confidence", "tokens",
                  "canonicalTags", "results", "surfaceText"):
            self.assertIn(k, r)
        self.assertTrue(r["queryId"].startswith("memq_"))
        self.assertEqual(r["mode"], "advisory")
        for k in ("id", "path", "file", "name", "description", "tags", "matchedTags",
                  "score", "mustRead"):
            self.assertIn(k, r["results"][0])

    def test_surface_text_escapes_and_wraps(self):
        r = self._search({"tool_name": "WebSearch", "tool_input": {"query": "kwin"}})
        self.assertIn("<memory-recall", r["surfaceText"])
        self.assertIn('mode="advisory"', r["surfaceText"])
        self.assertIn("rec-a.md", r["surfaceText"])

    def test_advisory_never_mustread(self):
        r = self._search({"tool_name": "WebSearch", "tool_input": {"query": "kwin"}})
        self.assertFalse(any(x["mustRead"] for x in r["results"]))


class BodiesNeverLoaded(Base):
    def test_search_reads_no_memory_bodies(self):
        opened, orig = [], Path.read_text

        def spy(self, *a, **k):
            opened.append(str(self))
            return orig(self, *a, **k)

        Path.read_text = spy
        try:
            ms.search(self.store, {"tool_name": "WebSearch", "tool_input": {"query": "kwin"}}, now=NOW)
        finally:
            Path.read_text = orig
        bodies = [o for o in opened if o.endswith(".md")
                  and Path(o).name != "MEMORY.md" and not Path(o).name.startswith("_")]
        self.assertEqual(bodies, [], f"search opened memory bodies: {bodies}")


class ConfigModes(unittest.TestCase):
    def _store(self, **cfg):
        p = Path(tempfile.mkdtemp())
        make_store(p, config=({**ms.DEFAULT_CONFIG, **cfg} if cfg else None))
        return p

    def test_disabled_returns_empty(self):
        p = self._store(mode="disabled")
        r = ms.search(p, {"tool_name": "WebSearch", "tool_input": {"query": "kwin"}}, now=NOW)
        self.assertEqual(r["results"], [])
        self.assertEqual(r["queryId"], "memq_00000000")

    def test_surface_disabled_killswitch(self):
        p = self._store()
        (p / ".surface-disabled").touch()
        r = ms.search(p, {"tool_name": "WebSearch", "tool_input": {"query": "kwin"}}, now=NOW)
        self.assertEqual(r["results"], [])


class Mutators(Base):
    def test_add_tag_ok(self):
        rc, _ = ms.add_tag(self.store, "newtool", "a new tool that handles several useful things", "tool")
        self.assertEqual(rc, 0)
        self.assertIn("newtool", ms.parse_tags_md(self.store / "_tags.md")["active"])
        self.assertEqual(ms.validate(self.store), [])

    def test_add_tag_denylisted_rejected(self):
        rc, msg = ms.add_tag(self.store, "config", "a long enough description to pass word count", "tool")
        self.assertEqual(rc, 2)
        self.assertIn("denylist", msg.lower())

    def test_add_tag_short_description_rejected(self):
        rc, msg = ms.add_tag(self.store, "newtool", "too short", "tool")
        self.assertEqual(rc, 2)
        self.assertIn("6-32 words", msg)

    def test_add_tag_malformed_rejected(self):
        rc, _ = ms.add_tag(self.store, "BadCaps", "x", "tool")
        self.assertEqual(rc, 2)

    def test_link_ok(self):
        rc, _ = ms.link(self.store, "kwin", "tailscale", "test")
        self.assertEqual(rc, 0)

    def test_link_fail_closed_rolls_back(self):
        before = (self.store / "_tag_links.md").read_text()
        rc, _ = ms.link(self.store, "ghosttag", "kwin")  # canonical 'ghosttag' not active
        self.assertEqual(rc, 2)
        self.assertEqual((self.store / "_tag_links.md").read_text(), before)


class Perf(Base):
    def test_warm_search_under_budget(self):
        ev = {"tool_name": "WebSearch", "tool_input": {"query": "kwin tailscale git"}}
        self._search(ev)                                 # warm
        t = time.perf_counter()
        for _ in range(5):
            self._search(ev)
        avg_ms = (time.perf_counter() - t) / 5 * 1000
        self.assertLess(avg_ms, 200, f"warm search {avg_ms:.1f}ms exceeds 200ms cap")


class ReviewRegressions(Base):
    """Pins for the bugs the Phase-2 adversarial review found (2026-06-02)."""

    def test_distinct_tag_per_category_no_stacking(self):
        # one canonical tag matched two ways must count in ONE category, not stack.
        r = self._search({"tool_name": "Bash", "tool_input": {"command": "kwin kwin"}, "cwd": "/"})
        self.assertEqual(self._by_id(r)["rec-a"]["score"], 11.0)          # not 14
        r2 = self._search({"tool_name": "WebSearch", "tool_input": {"query": "kwin plasma-compositor"}})
        self.assertEqual(self._by_id(r2)["rec-a"]["score"], 11.0)         # not 18

    def test_generic_command_first_arg_not_strong(self):
        r = self._search({"tool_name": "Bash",
                          "tool_input": {"command": "grep kwin file.txt"}, "cwd": "/"})
        self.assertEqual(r["results"], [])                               # §11: generic doesn't surface

    def test_sudo_prefix_does_not_change_extraction(self):
        a = self._search({"tool_name": "Bash", "tool_input": {"command": "pacman -S nvidia"}, "cwd": "/"})
        b = self._search({"tool_name": "Bash",
                          "tool_input": {"command": "sudo pacman -S nvidia"}, "cwd": "/"})
        norm = lambda r: sorted((t["value"], t["kind"]) for t in r["tokens"])
        self.assertEqual(norm(a), norm(b))
        self.assertIn(("nvidia", "package"), norm(a))                    # extracted, not lost

    def test_version_pinned_package(self):
        r = self._search({"tool_name": "Bash",
                          "tool_input": {"command": "pacman -S nvidia=550.1"}, "cwd": "/"})
        self.assertIn("nvidia", [t["value"] for t in r["tokens"]])      # version stripped

    def test_canonical_tags_include_path_rule(self):
        r = self._search({"tool_name": "Read", "tool_input": {"file_path": "~/.zshenv"}, "cwd": "/"})
        self.assertEqual(r["canonicalTags"], ["zsh"])                    # was [] before fix

    def test_min_candidate_one_tag_two_weak_does_not_surface(self):
        r = self._search({"tool_name": "Bash",
                          "tool_input": {"command": "kitty /home/u/kitty/x.conf"}, "cwd": "/"})
        self.assertEqual(r["results"], [])                              # one tag matched twice != 2 weak

    def test_response_mode_mapped_to_required(self):
        p = Path(tempfile.mkdtemp())
        make_store(p, config={**ms.DEFAULT_CONFIG, "mode": "strict-high-confidence"})
        r = ms.search(p, {"tool_name": "WebSearch", "tool_input": {"query": "kwin"}}, now=NOW)
        self.assertEqual(r["mode"], "required")                          # not raw config string

    def test_missing_catalog_fails_closed_no_body_read(self):
        (self.store / "_memory_catalog.json").unlink()
        opened, orig = [], Path.read_text
        Path.read_text = lambda self, *a, **k: (opened.append(str(self)) or orig(self, *a, **k))
        try:
            r = ms.search(self.store, {"tool_name": "WebSearch", "tool_input": {"query": "kwin"}}, now=NOW)
        finally:
            Path.read_text = orig
        self.assertEqual(r["results"], [])                              # fail closed
        bodies = [o for o in opened if o.endswith(".md")
                  and Path(o).name != "MEMORY.md" and not Path(o).name.startswith("_")]
        self.assertEqual(bodies, [])                                    # no rebuild -> no body reads

    def test_link_removes_existing_distinction(self):
        rc, _ = ms.link(self.store, "kde-wayland", "kde-x11", "now same")
        self.assertEqual(rc, 0)                                         # §7: link strips the distinction
        self.assertNotIn("!=", (self.store / "_tag_links.md").read_text())

    def test_unlink_distinguish_removes_existing_synonym(self):
        rc, _ = ms.unlink(self.store, "kwin", "plasma-compositor", distinguish=True, reason="diverge")
        self.assertEqual(rc, 0)                                         # §7: distinguishing strips synonym
        txt = (self.store / "_tag_links.md").read_text()
        self.assertIn("`kwin` != `plasma-compositor`", txt)
        self.assertNotIn("`kwin` = `plasma-compositor`", txt)

    def test_freetext_reason_cannot_inject_taxonomy(self):
        rc, _ = ms.link(self.store, "kwin", "tailscale",
                        "ok\n- `config` — sneaky injected active tag")
        self.assertEqual(rc, 0)
        links = (self.store / "_tag_links.md").read_text()
        # newline + backticks stripped -> payload is inert reason text, not a structural graph node
        self.assertNotIn("`config`", links)
        self.assertNotIn("config", ms.parse_tags_md(self.store / "_tags.md")["active"])
        self.assertEqual(ms.validate(self.store), [])

    def test_multiple_synonym_set_rejected(self):
        self.assertEqual(ms.link(self.store, "kwin", "tailscale")[0], 0)
        rc, _ = ms.link(self.store, "git", "tailscale")                 # tailscale alias of two canonicals
        self.assertEqual(rc, 3)                                         # §10 exit 3 = graph integrity
        self.assertEqual(ms.validate(self.store), [])                   # rolled back -> clean

    def test_mutator_ignores_preexisting_unrelated_error(self):
        # a pre-existing taxonomy issue must not block an unrelated, valid add-tag.
        (self.store / "_tag_links.md").write_text(
            "# tag links\n## Synonyms\n- `boguscanon` = `x` - bad\n## Distinctions\n## Path Tags\n")
        self.assertTrue(ms.validate(self.store))                        # store is already invalid
        rc, _ = ms.add_tag(self.store, "freshtag", "a perfectly fine six word description here", "tool")
        self.assertEqual(rc, 0)                                        # unrelated edit still allowed


if __name__ == "__main__":
    unittest.main(verbosity=2)
