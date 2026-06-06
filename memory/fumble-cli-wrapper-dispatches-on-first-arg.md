---
name: fumble-cli-wrapper-dispatches-on-first-arg
description: A CLI launcher that dispatches on $1 silently misroutes when you put a global flag before the subcommand — exits 0 having run the wrong thing. Verify the effect, not the exit code.
metadata:
  type: fumble
  tags:
    - shell
    - verify-live
---

**What happens by default:** I ran `hyprwhspr --no-progress setup auto --backend vulkan …`, it exited 0, and I assumed the backend installed. It hadn't — it launched the app *daemon* instead, which created a stub config and failed on a missing backend. The exit 0 was meaningless.

**Root cause:** `/usr/bin/hyprwhspr` is a bash wrapper that routes to the real CLI only when **`$1`** exactly matches a subcommand (`[[ "$1" =~ ^(setup|install|config|…)$ ]]`); otherwise it falls through to `exec python main.py "$@"` (the daemon). My global flag `--no-progress` made `$1` the flag, not `setup`, so dispatch missed and the installer never ran. Many launcher/wrapper scripts (and some busybox-style multitools) gate on `$1` like this — **global flags must come AFTER the subcommand, or the subcommand must be the first arg.**

**Better path:** put the subcommand first (`hyprwhspr setup auto --backend …`); drop pre-subcommand global flags. More generally: a 0 exit code is not proof the work happened — **verify the actual effect** (did the venv/model/file appear? does `status` show it?). When a "setup succeeded but nothing was installed" smell appears, **read the launcher/wrapper script** to see how it dispatches before re-running.

**How to spot it ahead of time:** before trusting a wrapped CLI, `Read` the `/usr/bin/<tool>` shim — if it branches on `$1`/`$2`, treat argument ORDER as load-bearing. Watch for output that looks like the *app running* (init/monitor logs) when you expected *installer* banners — that mismatch is the tell. Context: the working result is [[voiceclaude-local-dictation-stack]].
