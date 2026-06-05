---
name: method-pnpm-migration-electron-verify
description: Migrating an npm project (esp. Electron + native deps) to pnpm — the failures that local "build+test pass" misses, and how to actually verify
metadata:
  type: feedback
  tags:
    - node-tooling
    - pnpm
    - pacman
    - verify-live
---

When migrating an npm project to pnpm (especially Electron + native deps like sharp / esbuild / electron-builder), a green local `pnpm install && pnpm test && pnpm build` is necessary but NOT sufficient. The migration-specific failures live where local runs don't look.

**Why:** the local green only proves the CURRENT platform's strict-linker resolution. The real risk classes are:
- **Cross-platform CI under `--frozen-lockfile`.** Release matrices build on macOS/Windows runners. `pnpm-lock.yaml` must already contain the native optional packages for every target OS/arch (`@img/sharp-darwin-arm64`, `@esbuild/win32-x64`, `@rollup/rollup-win32-x64-msvc`, `@tailwindcss/oxide-win32-x64-msvc`, …) or those jobs fail or build without the binary. `pnpm import` from `package-lock.json` DOES preserve the full set — but grep the lockfile to confirm before trusting mac/win CI.
- **pnpm 11 build-script approval uses `allowBuilds` (a name→bool map in `pnpm-workspace.yaml`), NOT the v10 `onlyBuiltDependencies` array.** pnpm 11.3.0 silently ignores the old key and rewrites the file with an `allowBuilds:` scaffold (placeholder strings you must turn into `true`/`false`). Only deps with install/postinstall scripts need it. Also: since v11, pnpm no longer reads settings from the `package.json` `pnpm` field — they go in `pnpm-workspace.yaml`.
- **electron-builder is pnpm-aware via the `packageManager` field** (`"packageManager": "pnpm@x"`): it logs `pm=pnpm` and walks the symlinked `node_modules` correctly. If `electron-builder.yml` `files:` ships only `out/**` (Vite-bundled), pnpm's default isolated/strict linker is safe — no `nodeLinker: hoisted` needed, so you keep phantom-dependency protection.

**How to apply:**
1. Install pnpm via **pacman** (`pacman -S pnpm`), not `npm i -g` (global prefix is `/usr` → needs sudo + pollutes the system). Add the `packageManager` field.
2. `pnpm import` → swap lockfiles (`rm package-lock.json node_modules`) → `pnpm install`; set `allowBuilds` for the script-bearing deps that the install warns about.
3. **Verify the PACKAGED artifact actually boots, not just that it builds.** Launch the unpacked binary in the background and check liveness: `bin & pid=$!; sleep 4; kill -0 $pid` and confirm renderer/zygote children exist and the log has no `MODULE_NOT_FOUND`. Use `--no-sandbox --disable-gpu` on headless-ish boxes (a GPU-process FATAL / `error_code=1002` is environmental, not a packaging defect). Do NOT judge by `timeout`+exit-code (ambiguous: 124 vs 0 vs SIGTERM), and never clean up with `pkill -f <substr>` whose substring is in your own script — it self-kills the tool shell ([[fumble-rustdesk-execstop-pkill-self-kill]]); kill by PID excluding `$$`.
4. Migrate ALL live npm references (CI workflows, README, CONTRIBUTING, PR template, script comments + error strings) but leave CHANGELOG history and the app's own runtime `npx` (domain logic) untouched. Dependabot's `package-ecosystem: npm` is already correct for pnpm (it auto-detects `pnpm-lock.yaml`; there is no `pnpm` ecosystem).

Related: [[fumble-rustdesk-execstop-pkill-self-kill]].
