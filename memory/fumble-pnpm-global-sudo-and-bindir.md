---
name: fumble-pnpm-global-sudo-and-bindir
description: pnpm global installs need NO sudo on this box (unlike npm), and the global bin dir is $PNPM_HOME/bin, not $PNPM_HOME
metadata:
  type: feedback
  tags:
    - node-tooling
    - pnpm
    - verify-live
---

On this box npm and pnpm are OPPOSITE on sudo and on where global bins live — don't transfer npm habits to pnpm.

**What happens by default:** npm's global prefix here is `/usr` (root-owned — `sudo npm i -g` IS the sanctioned path for ctx7/pyright/playwright/etc.). So the reflex is to `sudo pnpm add -g …` too. But pnpm is **user-scoped**: under sudo, `HOME=/root`, so pnpm writes the package + store + cache into `/root/.local/share/pnpm`, `/root/.cache/pnpm`, `/root/.npm` — useless to the user, pure cruft. Separately, I assumed pnpm's global bin dir equals `$PNPM_HOME` and put that on PATH; pnpm 11 actually links global bins into **`$PNPM_HOME/bin`**, so `pnpm add -g` still errored "global bin directory … is not in PATH."

**Better path:**
- **Never `sudo pnpm`.** `pnpm add -g <pkg>` as the user installs to `$PNPM_HOME` (= `~/.local/share/pnpm`), bins linked into `$PNPM_HOME/bin`.
- Put **`$PNPM_HOME/bin`** (not `$PNPM_HOME`) on PATH, with `PNPM_HOME` exported. Either run `pnpm setup` (authoritative), or add to the rc: `export PNPM_HOME="$HOME/.local/share/pnpm"; path=("$PNPM_HOME/bin" $path)`.
- `pnpm config get global-bin-dir` returns `undefined` (computed, not stored) — don't rely on it; the install's own error message states the real dir. Verify by actually running `pnpm add -g <pkg>` and checking `$PNPM_HOME/bin`.
- Cleanup after a stray `sudo pnpm`/`sudo npm`: `sudo rm -rf /root/.local/share/pnpm /root/.cache/pnpm /root/.npm` (caches/cruft that regenerate on demand; global npm packages live in /usr, not /root, so this is safe), then `chown -R $USER` any root-owned files left in `~` (e.g. an app's `~/.cache/<App>` written once under sudo).

**How to spot it ahead of time:** a `/root/...` path in a pnpm/npm message you ran as your own user = it ran under sudo. And don't assume pnpm mirrors npm's prefix/sudo model — here they're inverted (npm = system/root, pnpm = user).

Related: [[method-pnpm-migration-electron-verify]].
