# CLAUDE.md — WoW Forever Streamer Tracker

Read this first in any new chat about this project. **Keep it current: after every push, update "Current state" and add a line to "Change log".**

## What it is
A single-page site that shows WoW Forever streamers' characters as trading cards: live Twitch status on the front, and equipped gear (character-sheet style) on the back when you tap the card.

- Live: https://blaqkfyre.github.io/wow-forever-tracker/ (GitHub Pages, `main` branch, repo `BlaqkFyre/wow-forever-tracker`)
- Local: `C:\Users\Ruth\Documents\GitHub\wow-forever-tracker`
- Luke commits and pushes with **GitHub Desktop**. Every change needs a commit title and a short summary.
- Plain HTML, CSS and JS, with no build step. Luke is on Windows.

## Files
| File | Role |
|---|---|
| `index.html` | The whole app: styles, the `ROSTER` data and all the logic (about 720 lines) |
| `gear-data.js` | Generated data that sets `window.GEAR` = `{v, checked, fc, n, I, C, S}`. `I` = items by ID `[name, quality, ilvl, iconIndex, status s/c/n, forever tooltip lines, classic tooltip lines, source]`. `C` = gear per character slug `[level, ilvl, {slot: itemId}]`. `S` = which icons are in the showcase sprite. `v` = cache-busting version. |
| `sprite.webp` | Item icon sprite sheet, 12 per row, indexed by `iconIndex` |
| `showcase.webp` | Large icon sprite for each card's "SHOWCASE" item, 4 per row |
| `renders/<slug>.webp` | Character renders (EU characters are under `renders/eu/`). If one is missing, the page loads the Blizzard render URL, and failing that, a class glyph. |
| `previews/gear-style-previews.html` | Old mockups of the gear-back styles. The live page doesn't use it. |

`index.html` loads `gear-data.js?v=<GEAR.v>`. Bump `v` whenever the gear, sprites or renders change, so browsers don't serve stale copies.

## How it works
- **Roster** (`const ROSTER` in index.html): one entry per Twitch channel: `{ch, streamer, flavor, how, fixed, chars:[...]}`. Each character has `name, slug, render, bg, level, ilvl, race, cls, spec, faction, ruleset, guild, profs, rep, note?`. A streamer with more than one character gets a ⇄ swap button.
- Current streamers (10): Sodapoppin, Towelliee (main plus a Ghalon Carter alt), Esfand, imaqtpie, Nmplol, Hammerdance, Asmongold, Mitch Jones, Gingi (EU), Quin69.
- **Sorting**: level-60 characters first, ranked by ilvl, then by level. Ties put Alliance before Horde.
- **Live status**: DecAPI (`decapi.me/twitch/uptime|title|game/<ch>`), refreshed every 2 minutes. When outside data is blocked (for example in a sandboxed preview), a banner shows instead.
- **Gear back**: built from `GD.C[slug]` and `GD.I`. Items are colour-flagged as new in Forever, reworked from Classic, or unchanged. Each tooltip compares the Forever stats with Classic and shows where the item drops. Item data comes from foreverchanges.pro.
- **Character data** comes from the official WoW Forever Armory. A scheduled Claude task (`TRIGGER_ID` in index.html) is meant to re-check it every 6 hours, regenerate `gear-data.js`, the sprites and the renders, and update `ROSTER` and the "Armory checked" date.
- **Add a streamer box**: this only works when the page runs as a Claude-hosted artifact. There it saves a request through `claude.use("db")` and fires the refresh task through `claude.use("mcp")`. **On GitHub Pages it can't do either**, so it just tells you to ask Claude in chat.
- Extras: an animated spec "move" when you tap or hover a character, a raid unlock countdown (9 Dec 2026), and links to other trackers.

## Current state (as of 24 Nov 2026)
- Git: an initial commit plus one pull. Gear was last checked 20 Nov, 3:33 PM AEDT.
- **Not built yet:** adding cards from GitHub Pages (hooking Add up to GitHub), removing cards, and an alerts ticker. Luke wants these because the refresh task uses up his Claude usage limits.

## Ideas / backlog
- Make Add work on GitHub Pages (for example with a GitHub issue or Action), plus a remove-card option and an alerts ticker
- Keep gear and player details updating automatically
- A raid tab once raids open on 9 Dec
- A stream or desktop overlay version of a card
- Collectible rare or customisable cards
- Filters and leaderboards

## Conventions
- Keep everything in a single page: no frameworks and no build step.
- Escape any user or remote text with `esc()` before it goes into HTML.
- Respect `prefers-reduced-motion`, and keep tap-to-use behaviour on phones (`isPhone()`).
- Test locally by opening `index.html` in a browser. Live status only works outside sandboxed viewers.

## Change log
<!-- Newest first. One line per push: date — commit title — what changed. -->
- 2026-11-24 — Add CLAUDE.md — project notes for new chats
- 2026-11-20 — Initial commit — tracker page, gear data, sprites, renders
