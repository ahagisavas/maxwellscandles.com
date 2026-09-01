# Handoff Document — Fantasy Draft Assistant

**As of:** 2026-08-24, commit `ca0d41c` on `main`.
**Purpose of this file:** if you're picking this project up on a different machine, in a hurry,
or with a fresh Claude session that has none of this project's history — start here. This is the
only copy of this context that isn't trapped in one machine's local session/memory: it lives in
the git repo, so `git clone` (or just reading it on GitHub) gets you everything below from anywhere.

---

## 1. What this is

A live fantasy-football draft assistant. Ranks the full draftable player pool in real time as
picks come off the board, blending several ranking sources, and can sync live picks automatically
from a real Sleeper draft room.

**It's hardcoded to one league at a time** — currently **ABFFL** (Yahoo, league ID 539375,
12-team snake, half-PPR). This is the *second* league this tool has been configured for: it was
originally built for **HFFL** (Haraki Fantasy Football League), whose draft happened and is done
(2026-08-22). When HFFL drafts again, its config will need rebuilding from git history (see §7 and
§9) — reformatting in place, rather than keeping both leagues side by side, was a deliberate choice
made when this switch happened.

**Live URL:** https://maxwellscandles.com/HFFL/ (yes, still `/HFFL/` in the path even though the
tool now targets ABFFL — renaming the URL wasn't part of the reformat, don't read anything into it).
**ABFFL status:** drafts **offline** (not through Yahoo's own draft room) — draft order/slot not
yet assigned as of this writing. `userSlot` in the settings is a placeholder; see §4.

## 2. Where everything lives

- **Repo:** https://github.com/ahagisavas/maxwellscandles.com (this tool is one folder in a larger
  personal-sites repo — Maxwell's Candles and other projects live in sibling folders, unrelated to
  this one).
- **Local clone (this machine):** `C:\Users\Hagisavas\Documents\GitHub\maxwellscandles.com\HFFL\`
- **Hosting:** GitHub Pages, custom domain via the repo-root `CNAME` file (`maxwellscandles.com`).
  **Deploy = `git push` to `main`, nothing else.** No build step, no CI, no secrets to configure.
  Takes roughly 1-3 minutes to actually go live after pushing (GitHub Pages build + CDN) — don't
  panic if `curl`ing the live URL right after a push still shows the old content for a minute or two.

## 3. The single most important architectural fact

**`index.html` is the entire application.** One self-contained file, ~5,300 lines: HTML + CSS +
JS + all player/projection/odds data, baked in as literal JS constants. No backend, no build step,
no npm, no external JS/CSS dependencies at all (verified — no CDN scripts, no external fonts). The
only network call anywhere in the file is the Sleeper live-sync `fetch()`, and even that's optional
(manual pick entry always works as a fallback).

This means: **editing this project is just editing one HTML file with a text editor**, and
**deploying is `git add`, `git commit`, `git push`.** Nothing else exists to break.

### Module map (search for these section-divider comments in `index.html` — line numbers as of
this commit; they drift a little with every edit, treat them as approximate)
| Section | Line (approx) | What it does |
|---|---|---|
| Hard-coded league config | 316 | `defaultSettings()` — team names/slots, roster, scoring rules. See §4. |
| Default player data | 381 | FantasyPros baseline projections, `DEFAULT_PLAYER_HEADERS`/`ROWS` |
| Small helpers | 988 | Misc utility functions |
| Scoring engine | 1033 | Turns raw stats into fantasy points per `settings.scoring` |
| Value engine (VBD) | 1121 | Replacement-baseline Value Based Drafting + tiering |
| Snake draft math | 1236 | Pick-number ↔ round/slot conversion for any `numTeams`/`userSlot` |
| Draft state | 1270 | Picks log is the single source of truth; everything else derives from it |
| Recommendation engine | 1560 | Staged, explainable pick suggestions |
| Importer | 1862 | Paste/CSV import with fuzzy column mapping (for one-off manual data adds) |
| `CONSENSUS_DATA` | 2004 | FantasyPros ECR (half-PPR as of `ca0d41c`) + Draft Sharks RK (still non-PPR) |
| `PROPS_DATA` | 2956 | BettingPros market prop lines — **see §5, this one has a parsing gotcha** |
| `FFBALLERS_DATA` | 3138 | The Fantasy Footballers' blended ranks (still non-PPR, not yet refreshed) |
| `DS_TIER_DATA` | 3456 | Draft Sharks tier/flag data (half-PPR as of `6bf144f`) |
| Sleeper live draft sync | 4626 | Polls the real Sleeper API, auto-applies matched picks |
| Persistence | 4756 | localStorage autosave + JSON export/import |
| UI | 4803 | Rendering, event wiring |
| Main | 5831 | Bootstraps everything on load |

## 4. League configuration (all hardcoded in `defaultSettings()`, ~line 324)

Current (ABFFL):
- 12 teams, snake draft. **`userSlot: 1` is a placeholder** — ABFFL drafts offline and hasn't set a
  draft order yet. It's deliberately paired with `teams[0] = "Tasi's Team"` (your real team) so
  roster-tracking attribution is at least right even before the real numeric slot is known. Update
  both the moment the real order is assigned.
- Roster: 1 QB / 2 RB / 2 WR / 1 TE / 1 FLEX(RB/WR/TE) / 1 K / 1 DEF / 6 BN — **no IR slot**, so
  `totalRounds: 15` is the full sum of every slot (nothing is waiver-only/excluded, unlike HFFL).
- **Half-PPR** (`reception: 0.5`) — passing 25 yds/pt + 4/TD + -1/INT (no pick-six penalty),
  rushing 10 yds/pt + 6/TD, receiving 10 yds/pt + 6/TD, **no missed-field-goal penalty**, **no
  return-yardage scoring** (`returns.yardsPerPoint: Infinity` — deliberate, makes that term divide
  to a clean 0 without a special case in the scoring engine). Defense/kicking tiers otherwise close
  to standard Yahoo defaults.
- Every value here was read directly off Yahoo's own scoring settings page
  (`football.fantasysports.yahoo.com/f1/539375/editstatcategories`) via the accessibility tree, not
  screenshotted or guessed — plain visual/text scraping of that page can't reliably tell which
  radio option is *selected* vs. just *available*, so don't trust a quick look at it for a future
  refresh; read the actual form state.
- Team slot → manager name mapping is in the `teams:` array — **currently just Yahoo's League
  Members list order, not real draft slots** (see `userSlot` note above). Fix this once the real
  order exists.

To reuse this tool for a different league/season: this whole block is meant to be edited directly
(there's no settings UI by design — see the comment right above it in the source). That's exactly
what happened going HFFL → ABFFL; see §7 for what that reformat touched vs. left alone.

## 5. Data pipeline — how the player pool gets built/refreshed

**Most of this data is NFL-wide, not tied to any one league** — the raw stat projections
(`DEFAULT_PLAYER_ROWS`, `PROPS_DATA`) didn't need to change when the tool switched from HFFL to
ABFFL. **The consensus RANKING sources are different: they're scoring-format-specific**, and this
bit HFFL→ABFFL hard — `CONSENSUS_DATA` and `DS_TIER_DATA` both originally came from HFFL's
non-PPR setup, and stayed non-PPR (silently wrong for ABFFL's half-PPR) until refreshed on
2026-08-24 (commits `af722ba`→`6bf144f`→`ca0d41c`). If this tool is ever reformatted for a *third*
league with yet another scoring format, re-check these two blocks specifically, even though
nothing else about "the pool" needs to change.

Six independent sources feed the pool; each has its own one-time or repeatable script, all living
next to `index.html`:

- **`refresh_fantasypros.py`** — pulls the FantasyPros API (premium/HOF-tier key required, kept in
  a git-ignored local config, never committed) and regenerates `DEFAULT_PLAYER_HEADERS`/`ROWS`.
  Repeatable — safe to re-run for a fresh season. Does NOT touch `CONSENSUS_DATA`'s ECR (see
  `refresh_consensus_ecr.py` below) — despite the similar name, this script's job is raw stat
  projections only.
- **`refresh_consensus_ecr.py`** — refreshes just the FantasyPros-ECR half of `CONSENSUS_DATA`
  (`[ecr, ds_rk]` — only the first element) from a CSV the user downloads directly from
  FantasyPros' own rankings page. **Not click-and-run**: needs a fresh CSV re-confirmed to be the
  right scoring format before every use (screenshot the FantasyPros page's own Scoring/My
  Leagues selectors and cross-check a few rows against the CSV — don't trust the filename or
  column headers to declare format on their own, they don't). Gotcha already hit once: the CSV
  labels defenses `DST`, the pool uses `DEF` — `POS_FIX` handles it, but watch for the same class
  of mismatch if FantasyPros changes their export format later.
- **`build_ds_tiers.py`** — Draft Sharks tier/flag data from a login-walled, subscriber-only
  "Draft War Room" export tuned to one league's exact settings. This is the ORIGINAL, HFFL-only
  version of this data (non-PPR) — superseded for ABFFL by `build_ds_halfppr.py` below, but kept
  as-is since it's still the right tool if a future league needs that deeper subscriber-only
  export (tiers/flags together) rather than the public-page version.
- **`build_ds_halfppr.py`** — the ABFFL-era replacement, sourced from Draft Sharks' PUBLIC
  half-PPR rankings pages instead (no login wall, no row cap — confirmed by reaching the true page
  footer on every position). Gets `overallTier`/`posTier` but NOT the qualitative flag (Value/
  Sleeper/Bust/Handcuff Flyer — not on the public page); existing flags were left as-is rather
  than deleted, so they're stale non-PPR-era judgment calls until a fresh Draft War Room export
  refreshes them properly. **Not click-and-run** — see its own docstring; it reads from
  session-local scratchpad files that don't persist, so a future refresh means redoing the live
  page-scroll-and-save pull first, same method, not just re-running this script directly.
- **`build_ffballers_data.py`** — The Fantasy Footballers blended ranks → `FFBALLERS_DATA`. Not
  yet refreshed for half-PPR as of this writing — same risk as `CONSENSUS_DATA`/`DS_TIER_DATA` had
  before their refresh, just not yet addressed.
- **`merge_props.py`** — **not repeatable, not an API pull.** BettingPros has no public API, and an
  AI-sourced (Gemini) export of their odds was tried and found to be **wrong** (e.g. showed Josh
  Allen's rushing-TD line as 4.5 when the real live consensus was ~11.0, and missed his passing-yards
  market entirely). Current policy: **BettingPros data only ever gets into this tool by a human (or
  Claude, browsing live) manually reading bettingpros.com/nfl/odds/player-futures/ and hand-entering
  the consensus line into this script's `*_UPDATES` dicts**, which then text-surgically patches the
  `PROPS_DATA` block. Re-running it is safe (it's idempotent per-field), but *adding new data* means
  going back to the live site, not trusting any bulk export, however convenient.
  - **Gotcha:** `PROPS_DATA`'s inner keys (`rushYds`, `recTd`, …) are **bare JS identifiers, not
    quoted strings** — the block is *not valid JSON* and `json.loads()` cannot parse it. That's why
    `merge_props.py` is text-surgical (regex-finds one `"name|POS": {...}` line at a time) instead
    of round-tripping through a JSON parser. Don't "fix" this into JSON without also updating every
    place in `index.html` that reads `PROPS_DATA` as a plain JS object literal.
  - BettingPros' player-futures pages cap at **~10 rendered players per market** regardless of the
    count shown in the market-type dropdown label — confirmed repeatedly by scrolling to the actual
    page footer. This is a free-tier limit, not a loading bug. Budget for it when pulling more data.

## 6. Conventions that aren't obvious from the code alone

- **"Don't invent 0, use blank/dash."** Anywhere a stat/projection isn't actually known for a
  player, the UI shows `—`, never a fabricated `0`. Applies to both the data layer (don't write a
  `PROPS_DATA` field that wasn't actually confirmed) and display (`fmt1(x)==null ? '—' : ...`).
- **Badge polarity:** for the four "our ranking vs. external source" badges (FP/DS/FFB/market),
  **green/▲ means *we* rate the player higher than the source** — i.e. if you trust this tool's own
  ranking, green is good. This was deliberately flipped from the more naive "source rates them
  higher" convention partway through the project; all four badges were kept consistent on purpose.
- **When reading a live web page's form state (settings pages, scoring configs, etc.), don't trust
  plain text extraction alone.** It'll show you every available option but not reliably which one
  is *selected* — read the accessibility tree (or equivalent) for real input/radio values instead.
  This is exactly how ABFFL's scoring got captured correctly (see §4) after an initial screenshot
  pass proved ambiguous.
- **Windows text encoding:** if doing bulk text edits with PowerShell (`Get-Content`/
  `[IO.File]::WriteAllText` etc.) instead of Claude's own Edit/Write tools, special characters can get
  silently mangled. Prefer Python with explicit `encoding='utf-8'` for any bulk text surgery, same as
  the `merge_props.py`/`build_*.py` scripts already do.

## 7. Status: what's done vs. deferred

**Done:** core VBD/ranking engine, mock draft mode, manual pick tracking, CSV/paste import, live
Sleeper draft sync (auto-applies matched picks, surfaces unmatched ones for manual resolution),
FantasyPros + Draft Sharks + Fantasy Footballers + BettingPros props all integrated, Mkt Yds/Mkt TD
columns, badge system, favicon + web manifest (installable as a desktop/mobile app). **HFFL's
draft happened 2026-08-22** and was manually cross-checked post-draft (roster value analysis,
league-wide draft grading) — that was this tool's first real, complete use. The league config was
then reformatted for ABFFL on 2026-08-24 (see §4) — HFFL's specific settings (Haraki Fantasy
Football League, slot #11, non-PPR, real Sleeper draft_id `1387098256592367616`) no longer exist
in `index.html` itself, only in git history (`git log -- HFFL/index.html`, look before commit
`0419354`) and in the offline snapshot files listed in §9. The reformat initially left the
consensus RANKING sources (`CONSENSUS_DATA`, `DS_TIER_DATA`) on HFFL's old non-PPR data — this was
caught and fixed on the same day (see §5), except **`FFBALLERS_DATA` is still non-PPR/HFFL-era as
of this writing** — same class of staleness, just not yet addressed.

**Explicitly deferred, not started:**
- **Draft Sharks CSV/table import** for Jody Smith's RB rankings specifically — no public API exists;
  needs a real sample of what a subscriber's export/page actually contains before building field
  mapping. (Draft Sharks *tier* data is already integrated via `build_ds_tiers.py` — this is a
  separate, not-yet-started ask for a different Draft Sharks ranking source.)
- **In-page AI chat box** for live Q&A during the draft — needs a backend to hold an Anthropic API
  key server-side (serverless proxy vs. local script undecided). No chat code exists yet.

## 8. Emergency quick-reference: making a change and deploying it

1. Edit `C:\Users\Hagisavas\Documents\GitHub\maxwellscandles.com\HFFL\index.html` directly (or use
   Claude Code / any editor).
2. From `C:\Users\Hagisavas\Documents\GitHub\maxwellscandles.com`:
   ```bash
   git add HFFL/index.html
   git commit -m "describe the change"
   git push
   ```
   (If the commit message is long/multi-line and `git commit -m "..."` errors out on quoting, write
   it to a temp file and use `git commit -F path/to/file.txt` instead.)
3. Wait 1-3 minutes, then hard-check (not just a browser reload, which can serve a cached copy):
   ```bash
   curl -s "https://maxwellscandles.com/HFFL/index.html?nocache=1" | grep "whatever you changed"
   ```
4. If a different machine/Claude session doesn't have this repo cloned yet:
   ```bash
   git clone https://github.com/ahagisavas/maxwellscandles.com.git
   ```
   (needs GitHub access/credentials configured on that machine — this repo is not public-write, so
   pushing needs your GitHub auth either way.)

## 9. Offline / no-internet contingencies that already exist

- **`HFFLDraft.url`** (Desktop) — shortcut to the live URL. Always current (loads whatever's
  actually deployed), needs internet.
- **`HFFLDraft (Offline Backup).html`** (Desktop) and **`HFFL_BEST.html`** (Desktop) — frozen,
  fully self-contained snapshots of `index.html`. **Both predate the ABFFL reformat — they still
  contain HFFL's old settings (non-PPR, slot #11, Haraki teams), not ABFFL's.** Treat them as
  historical HFFL snapshots, not current backups, until re-copied from the live repo.
- **`HFFLDraft (Offline Backup).html` in `OneDrive\Documents\`** — same file, same staleness caveat.
- **`Desktop\HFFL\` folder** — a full copy of every file in the repo's `HFFL/` folder (`index.html`,
  `manifest.json`, all four `*.py` scripts, this `HANDOFF.md`, and a `HFFL Handoff Instructions.docx`
  Word version) as of 2026-08-20. Same staleness caveat as above for `index.html` specifically; the
  scripts/docs are less time-sensitive but still worth re-copying if this repo has moved on.

None of the above auto-update — that's the tradeoff for working with zero internet. If you're ever
unsure how stale one is, compare its top-of-file `PROPS_DATA`/`defaultSettings()` content (or, for
the Word doc, its content) against this handoff doc's "As of" commit.
