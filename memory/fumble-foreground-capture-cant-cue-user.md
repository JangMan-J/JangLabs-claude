---
name: fumble-foreground-capture-cant-cue-user
description: A foreground capture that asks the user to act in real time (speak/click/plug-in) fires before they can read the prompt — detach it to background so it overlaps their action.
metadata:
  type: fumble
  tags:
    - claude-harness
    - audio
    - detach-to-outlive-turn
---

**What happens by default:** to calibrate the mic I ran `timeout N pw-record …` in the **foreground** with a "👉 speak now" line just above it. It failed three times — the captured clips were just room tone, quieter than a no-speech baseline. Cause: a foreground tool call **executes the instant the turn emits it**, while the assistant message (the "speak now" cue) only reaches the user *after* the turn completes. So the recording window elapses before the user ever sees the prompt. Any "have the user do X in real time while I capture/observe" step has this race — speaking, clicking, plugging in a device, triggering an event.

**Better path:** run the capture with **`run_in_background: true`** and a generous window (~20–30 s). The turn ends immediately, the message (with the cue) reaches the user, and the detached capture is *still running* — so the user's action overlaps it. The completion notification re-invokes you to analyze. (Confirmed: the very next background take captured real speech, RMS peak jumped ~+6 dB.) Alternatively hand the user a self-paced one-liner they run themselves so they control the timing.

**How to spot it ahead of time:** whenever a plan is "tell the user to do something, AND capture/measure it in the same turn," stop — a foreground tool can't span the user's reaction. Detach to background (or delegate the command to the user) any time the data depends on a human action happening *during* the tool's execution. See the mic context in [[solocast2-linux-audio-gain]].
