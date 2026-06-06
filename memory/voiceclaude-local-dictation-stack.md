---
name: voiceclaude-local-dictation-stack
description: The working local voice-dictation stack on this box — hyprwhspr (Vulkan whisper, large-v3-turbo) + SoloCast gain-lock + RNNoise + per-user ydotool. How it's wired.
metadata:
  type: reference
  tags:
    - audio
    - pipewire
    - kde-plasma
---

Local, private, GPU voice dictation built on this box (KDE Wayland), complementing Claude Code's cloud `/voice` (see [[kde-wayland-text-injection-and-claude-voice]]). Two voice paths coexist.

**hyprwhspr (AUR, Python service)** — `SUPER+ALT+D` to dictate into any focused window:
- Backend: `pywhispercpp` **built with `GGML_VULKAN=1`** (chose Vulkan to use the RTX 4090 WITHOUT the 2 GB CUDA toolkit — only `vulkan-headers` was missing; `shaderc`/`glslang` were present). Model `large-v3-turbo` (~1.6 GB) resident in VRAM (~1.8 GB). hyprwhspr **mislabels** it "CUDA (NVIDIA)" — cosmetic; no CUDA toolkit exists so it can only be Vulkan. Confirm GPU use via `nvidia-smi --query-compute-apps` showing the venv python, not the label.
- Install (non-interactive): `hyprwhspr setup auto --backend vulkan --model large-v3-turbo --no-waybar`. **Arg order matters** — `setup` must be `$1` (see [[fumble-cli-wrapper-dispatches-on-first-arg]]). Venv at `~/.local/share/hyprwhspr/venv`; models at `~/.local/share/pywhispercpp/models/`; config `~/.config/hyprwhspr/config.json`.
- Hotkey via **evdev** (reads `/dev/input`, needs `input` group — already a member), NOT KDE global shortcuts — so `recording_mode: auto` gives BOTH tap-toggle and hold-push-to-talk (the KDE "no key-release to global shortcuts" limit doesn't apply). Pastes via Ctrl+Shift+V (terminal-safe). Service: `systemctl --user {status,restart} hyprwhspr.service`. Free VRAM with `hyprwhspr model unload`.
- Depends on per-user `ydotoold` (root system daemon was disabled, `systemctl --user enable --now ydotool.service`; socket `/run/user/1000/.ydotool_socket`).

**Mic chain (SoloCast 2):** gain-locked at boot by `~/.config/systemd/user/solocast-gain.service` → `~/.local/bin/solocast-gain.sh` (resolves card by name each run — index churns, was 1→0 across one restart). RNNoise `NoiseCanceledMic` virtual source via `~/.config/pipewire/pipewire.conf.d/99-rnnoise.conf` (on-demand, not default). hyprwhspr uses the system-default source, so switching default to NoiseCanceledMic makes it use that. See [[solocast2-linux-audio-gain]].
