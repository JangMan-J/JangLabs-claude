---
name: solocast2-linux-audio-gain
description: HyperX SoloCast 2 mic on Linux DOES expose a hardware ALSA gain (the "NGENUITY/software-only" claim is wrong); it's low-output — analog maxed + PipeWire unity ≈ -12 dBFS dictation.
metadata:
  type: reference
  tags:
    - audio
    - pipewire
---

The **HyperX SoloCast 2** USB mic (USB ID `03f0:0fbf`, branded HP/HyperX) on this box, tuned for `/voice` dictation:

- **It DOES expose a hardware capture-gain control on Linux** — `amixer -c <card> sget 'Mic'`, range **0–444 ≈ up to 19.87 dB**. This **refutes** the research-workflow claim that "SoloCast gain is software-only / only settable via NGENUITY (Windows-only)." That's true for NGENUITY's *DSP profile*, but a plain UAC feature-unit gain is exposed to ALSA. Verify the live mixer before repeating vendor-marketing claims about gain (`verify-live`).
- **It's a genuinely low-output mic.** Even with the analog `Mic` maxed (444/19.87 dB), close normal dictation peaks only ~**-25 dBFS at PipeWire unity** in early tests — but the *representative* level when actually dictating close was higher. Empirically: hardware `Mic` maxed + PipeWire source volume at **unity (1.0)** lands normal dictation at **≈ -12 dBFS peaks** (textbook). So: put ALL gain in the analog stage, keep software at 1.0 → cleanest signal, no digital-noise amplification. Do NOT stack big `wpctl` software boost (3.0×/+9.5 dB drove peaks to a too-hot -2.6 dBFS).
- **Default-source gotcha:** WirePlumber had the persistent default source pointing at the mic's `iec958-stereo` (digital) profile instead of the working `analog-stereo` — risks a silent mic on reboot. Pin it: `wpctl set-default <analog-source-node>`.
- **Sample rate:** runs s24le / 48 kHz / stereo (one capsule duplicated L/R — feed mono ch0). Don't force 96 kHz (no ASR benefit; Whisper wants 16 kHz and resamples) and don't force 16 kHz at the PipeWire layer.
- **Persistence caveat:** `wpctl` volume + default-source choice persist via WirePlumber state; the `amixer 'Mic'` value may drift back to WirePlumber's managed default on reboot/replug — re-run `amixer -c <card> sset 'Mic' 100%` or add a persistent WirePlumber rule. **Node id / card index churn** across reboots — re-find with `wpctl status` / `arecord -l`, never hardcode.
- Background music ~6 ft off-axis measured ~25+ dB below close speech → cardioid rejection + hold-to-talk make noise suppression unnecessary for that; RNNoise (`noise-suppression-for-voice` + PipeWire filter-chain) only for louder constant noise.

Self-check level anytime: `timeout 6 pw-record --channels 1 /tmp/lvl.wav` (speak during it) then `ffmpeg -i /tmp/lvl.wav -af volumedetect -f null -` → want `max_volume` ~ -8 to -14 dB. See [[hardware-profile-jangsjail]], [[kde-wayland-text-injection-and-claude-voice]], and the calibration-timing lesson [[fumble-foreground-capture-cant-cue-user]].
