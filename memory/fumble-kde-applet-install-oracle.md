---
name: fumble-kde-applet-install-oracle
description: To check if a Plasma 6 applet is installed, kpackagetool6 --list and the plasmoids dir both MISS compiled-in core applets; use the running journal or the compiled .so dir
metadata:
  type: feedback
  tags:
    - kde-plasma
    - verify-live
---

On Plasma 6 (this box, 6.6.x), the obvious ways to ask "is applet `org.kde.plasma.X` installed?" are **wrong for core applets**, which silently false-positives "missing" on kickoff / systemtray / digitalclock / panelspacer / appmenu / etc.

**What happens by default:** you reach for `kpackagetool6 --type Plasma/Applet --list` (returns only the handful of *user-scoped* KPackage applets — 7 here) or `ls /usr/share/plasma/plasmoids/` (only directory-packaged applets — 22 here, mostly third-party). Core applets appear in **neither** — in Plasma 6 they're compiled C++/QML plugins shipped as `/usr/lib/qt6/plugins/plasma/applets/*.so` (~56 here) with **no on-disk `metadata.json`/package**. So a naive "referenced id ∉ installed-list ⇒ missing" check flags every core applet a layout uses.

**Better path:** the authoritative oracle for "does plasmashell actually have this applet" is the **running shell's journal** — `journalctl --user -b 0 | grep 'error when loading applet'` logs `"<id> ... package does not exist"` for the genuinely-absent ones only (here just `splitdigitalclock` + `win7showdesktop`, both third-party). For a static check, test membership in **(dir plasmoids ∪ compiled `.so` basenames under `/usr/lib/qt6/plugins/plasma/applets/`)** plus a curated core allowlist — and note `marginsseparator` IS still a real `.so` in 6.6 (don't flag it). Same shape applies to other "is it installed" KDE questions: the package-tool list ≠ what the compositor can load.

**How to spot it ahead of time:** if a registry/list query returns a suspiciously *small* set (7, 22) versus a working desktop that clearly has dozens of applets in its panels, the list is scoped/partial — corroborate against the live system (journal, the actual plugin dir) before asserting absence. Instance of [[method-deweight-own-language-proficiency-prior]]'s cousin: trust the running artifact over the convenient catalog. Related: the vinceliuice theme-compat scanner in `~/JangJunk/themes/vinceliuice/.work/compat_scan.py` encodes this oracle.
