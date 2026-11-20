# Where this skill comes from

- Source: https://github.com/DietrichGebert/ponytail, `skills/ponytail/SKILL.md` and `skills/ponytail-debt/SKILL.md`, commit `96608e078b2d5ea607c5c3b8b5a54d1c1fba6846` (2026-10-29), v5.3.3. MIT, licence in `references/LICENSE`. Author: DietrichGebert (repo owner). Found via a TikTok video (vm.tiktok.com/ZGdXC69qu), which is not the author.
- `references/ponytail.md` and `references/ponytail-debt.md` are the upstream files, byte for byte (sha256 `9badd22a32e19cb884e46dfa8d3aae82bb81dfa5484105b8b4f0262df823a509` and `b5ec2762f6ba8c4af9ea7173aa6c9f91b88655a25e43f9de0264f6ce8722b25f`). They sit under `references/` so only the wrapper is callable and its rules always load first. BrightLink Echo's own rules are in `SKILL.md`.
- Read through before adding (Hermes Cloud, 15 Nov 2026): markdown only, no scripts, no links that run anything, no hidden Unicode.
- Left out on purpose:
  - The plugin's hooks (Node scripts on session start, every prompt and every subagent start, a cost ledger in `~/.config/ponytail/band`, an optional webhook). They add code that runs on every prompt for a status band; the rules work without them.
  - `ponytail-review` and `ponytail-audit`: this repo already has `REVIEW.md`, the review agents on the laptop and the overnight audits.
  - `ponytail-gain` (benchmark scoreboard) and `ponytail-help` (plugin help card).
  - Fork `Facta-Dev/ponytail` (0 stars, made in October 2026): not used.
- To update: copy the newer upstream files over the ones in `references/`, update the commit and hashes above, and read the diff first.
