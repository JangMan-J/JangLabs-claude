---
name: method-long-job-foreground-batches
description: Multi-minute background Bash jobs get suspended while the session idles; finish them in bounded foreground batches instead
metadata:
  type: feedback
  tags:
    - claude-harness
    - long-job-foreground-batches
---

A long-running (multi-minute) Bash job on this box only reliably makes progress **during active assistant turns**. Launched via `run_in_background`/`nohup &`/auto-backgrounded, it advances while the session is busy but **stalls when the session idles between turns** (report mtime freezes for tens of minutes). Observed across a ~199-file throttled download: every background launch froze partway; a tight foreground `while+sleep` poll-loop *also* starved the detached worker (the sandbox time-slices CPU between the foreground call and the background job).

**Why:** background/detached processes don't get scheduled CPU once the foreground turn ends, so any job that must run across idle gaps silently hangs — and you waste turns rediscovering it. This is the long-compute complement to [[detach-to-outlive-turn]] (which is right for a *short* capture that must overlap a user action).

**How to apply:** make the worker **resumable** (load prior state, skip done), **idempotent** (re-run is safe; md5-verify + checkpoint each item), and **bounded** per invocation (process K items then exit in ~40–60s). Then drive it from a **foreground shell loop** that runs each batch synchronously and echoes progress:
`for i in $(seq 1 N); do MAX_NEW=4 worker.py; echo "batch $i -> $(progress)"; [ done ] && break; done`
The loop stays foreground (keeps getting CPU), each child runs to completion, echoes stream to the output file. Don't "launch in background and poll" for a multi-minute job here. Also recall the Bash tool is zsh — pass batch/family lists as literal argv or via `subprocess`, not unquoted `$vars` ([[fumble-bash-tool-shell-is-zsh-no-unquoted-word-split]]).
