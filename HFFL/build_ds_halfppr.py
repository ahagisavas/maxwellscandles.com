#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rebuilds DS_TIER_DATA in index.html from Draft Sharks' PUBLIC half-PPR rankings pages
(draftsharks.com/rankings/{pos}/half-ppr and /rankings/half-ppr for the All-Positions view),
hand-pulled live this session -- not the login-walled "Draft War Room" export the original
HFFL-era DS_TIER_DATA came from.

WHAT THIS DOES:
  - posTier: from each position-specific page's TIER groups (confirmed live: filtering to one
    position turns the TIER column into a position-specific tier, distinct from the all-positions
    view's overall tier).
  - overallTier: from the All-Positions page's TIER groups (covers rank 1-250, the full realistic
    draft-relevant pool for a 12-team league; beyond that the public page doesn't render further,
    so deeper bench players fall back to using their posTier as overallTier too -- a documented
    approximation, not a fabricated number).
  - flag: NOT available on this public page (no Value/Sleeper/Bust/Handcuff Flyer column here,
    unlike the original subscriber-only Draft War Room export). Existing flags are LEFT AS-IS
    (stale, HFFL/non-PPR era) rather than deleted -- better a labeled-stale signal than none, but
    this should be refreshed from a fresh Draft War Room export if the qualitative flags matter
    going forward.

MATCHING: these pages use abbreviated first names ("J Gibbs"), so matching is last-name + team +
position, falling back to last-name + position alone (only when that's unambiguous) if the pool's
team code doesn't match -- e.g. a stale team after an offseason move. The fallback MUST be scoped
by position, not just bare last name -- a shared surname across two different position files (e.g.
Tyreek Hill in the WR pull, Justice Hill in the RB pull) will otherwise silently collide their
tiers into one candidate set. (Caught live once via a spot-check that disagreed between two runs;
verify determinism -- same input should hash-match output -- before trusting a similar rewrite.)

NOT A CLICK-AND-RUN PIPELINE: SCRATCH below points at this session's temp scratchpad, which does
NOT persist -- the ds_{qb,rb,wr,te,all}.txt files it reads are raw text dumps from manually
scrolling each draftsharks.com page and saving the visible rows, not something this script fetches
itself. Re-running this later means redoing that manual pull first (same live-scroll-and-save
process, see the session that produced this file) and pointing SCRATCH at wherever those land.
This script is committed as a record of the matching logic and its hard-won gotchas, not a
standalone tool -- same spirit as merge_props.py's own one-time-pass, not-an-API-pull disclaimer.
"""
import re, json
from collections import defaultdict

HTML_PATH = r'C:\Users\Hagisavas\Documents\GitHub\maxwellscandles.com\HFFL\index.html'
SCRATCH = r'C:\Users\Hagisavas\AppData\Local\Temp\claude\C--Users-Hagisavas\32bc1d49-65e4-4aa8-a00d-9fd772b69ef7\scratchpad'  # session-local, will not exist later -- see docstring

TEAM_FIX = {'LVR': 'LV', 'JAC': 'JAX'}


def normalize_lastname(name):
    parts = name.strip().split(' ', 1)
    last = parts[1] if len(parts) > 1 else parts[0]
    return re.sub(r'[^a-z0-9\- ]', '', last.lower()).strip()


def parse_position_file(path, pos):
    """Returns {(lastname, team): tier}, plus a {(lastname, pos): [tiers]} view for the no-team
    fallback -- MUST be position-scoped: a bare lastname alone collides across position files
    (e.g. Tyreek Hill in the WR file and Justice Hill in the RB file both reduce to "hill", and
    with no position key their tiers would silently merge into one candidate set)."""
    text = open(path, encoding='utf-8').read()
    by_team, by_last = {}, defaultdict(list)
    tier = None
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^TIER (\d+)$', line)
        if m:
            tier = int(m.group(1))
            continue
        parts = line.split('\t')
        if len(parts) >= 4 and parts[0].isdigit():
            name, team = parts[1], parts[2]
            team = TEAM_FIX.get(team, team)
            last = normalize_lastname(name)
            # UNS ("unsigned"/roster-limbo per Draft Sharks, e.g. Tyreek Hill, Brandon Aiyuk --
            # doesn't mean not on an NFL roster) can never match the pool's real team code, but
            # should still be reachable via the last-name-only fallback rather than dropped
            # entirely. RK (rookie-pool placeholder) has no real identity to fall back on.
            if team == 'RK':
                continue
            if team != 'UNS':
                by_team[(last, team, pos)] = tier
            by_last[(last, pos)].append(tier)
    return by_team, by_last


def parse_all_positions_file(path):
    """Returns {(lastname, team, pos): tier} plus a {(lastname,pos): [tiers]} fallback view."""
    text = open(path, encoding='utf-8').read()
    by_team, by_last = {}, defaultdict(list)
    tier = None
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^TIER (\d+)$', line)
        if m:
            tier = int(m.group(1))
            continue
        parts = line.split('\t')
        if len(parts) == 4 and parts[0].isdigit():
            rk, name, team, posrk = parts
            team = TEAM_FIX.get(team, team)
            pos_match = re.match(r'^([A-Z]+)\d+$', posrk)
            pos = pos_match.group(1) if pos_match else None
            if pos == 'DEF' or not pos or team == 'RK':
                continue
            last = normalize_lastname(name)
            if team != 'UNS':
                by_team[(last, team, pos)] = tier
            by_last[(last, pos)].append(tier)
    return by_team, by_last


def load_pool_and_ds_block():
    html = open(HTML_PATH, encoding='utf-8').read()
    headers = json.loads(re.search(r'const DEFAULT_PLAYER_HEADERS = (\[.*?\]);', html).group(1))
    rows_src = re.search(r'const DEFAULT_PLAYER_ROWS = (\[\n.*?\n\]);', html, re.S).group(1)
    rows_src = re.sub(r',(\s*\])$', r'\1', rows_src)
    rows = json.loads(rows_src)
    idx = {h: i for i, h in enumerate(headers)}
    m = re.search(r'const DS_TIER_DATA = \{.*?\n\};', html, re.S)
    return html, headers, rows, idx, m


def pool_lastnames(full_name):
    """Returns candidate last-name keys to try, in priority order. Draft Sharks is inconsistent
    about showing suffixes (e.g. keeps "Walker III" but drops "Mahomes II" / "Pitts Sr." / "Cook
    III" entirely) -- so try WITH the suffix first (handles real same-family-name disambiguation
    like multiple "Williams"), then WITHOUT, rather than committing to one form."""
    parts = full_name.strip().split(' ')
    suffix = parts[-1] if parts[-1] in ('Jr.', 'Sr.', 'II', 'III', 'IV', 'V') and len(parts) > 2 else None
    bare_last = parts[-2] if suffix else parts[-1]
    candidates = []
    if suffix:
        candidates.append(re.sub(r'[^a-z0-9\- ]', '', f'{bare_last} {suffix}'.lower()).strip())
    candidates.append(re.sub(r'[^a-z0-9\- ]', '', bare_last.lower()).strip())
    return candidates


def normalize_name_js(name):
    name = str(name or '').lower()
    name = re.sub(r'\b(jr|sr|ii|iii|iv|v)\.?\b', '', name)
    name = re.sub(r'[^a-z0-9]+', '', name)
    return name.strip()


def main():
    html, headers, rows, idx, ds_match = load_pool_and_ds_block()
    name_i, team_i, pos_i = idx['Player'], idx['Team'], idx['Pos']

    pos_by_team, pos_by_last = {}, {}
    for pos, fname in [('QB', 'ds_qb.txt'), ('RB', 'ds_rb.txt'), ('WR', 'ds_wr.txt'), ('TE', 'ds_te.txt')]:
        bt, bl = parse_position_file(f'{SCRATCH}\\{fname}', pos)
        pos_by_team.update(bt)
        pos_by_last.update(bl)

    all_by_team, all_by_last = parse_all_positions_file(f'{SCRATCH}\\ds_all.txt')

    updated, not_found, ambiguous = [], [], []
    for r in rows:
        full_name, team, pos = r[name_i], r[team_i], r[pos_i]
        if pos not in ('QB', 'RB', 'WR', 'TE'):
            continue
        lastnames = pool_lastnames(full_name)

        pt = None
        for last in lastnames:
            pt = pos_by_team.get((last, team, pos))
            if pt is not None:
                break
        if pt is None:
            for last in lastnames:
                cands = set(pos_by_last.get((last, pos), []))
                if len(cands) == 1:
                    pt = next(iter(cands))
                    break
                elif len(cands) > 1:
                    ambiguous.append(f'{full_name} ({pos}, {team}) -- posTier candidates {cands}')

        ot = None
        for last in lastnames:
            ot = all_by_team.get((last, team, pos))
            if ot is not None:
                break
        if ot is None:
            for last in lastnames:
                cands = set(all_by_last.get((last, pos), []))
                if len(cands) == 1:
                    ot = next(iter(cands))
                    break
                elif len(cands) > 1:
                    ambiguous.append(f'{full_name} ({pos}, {team}) -- overallTier candidates {cands}')

        if pt is None and ot is None:
            not_found.append(f'{full_name} ({pos}, {team})')
            continue
        final_pt = pt if pt is not None else ot
        final_ot = ot if ot is not None else pt
        key = normalize_name_js(full_name) + '|' + pos
        updated.append((key, final_ot, final_pt))

    block = ds_match.group(0)
    n_updated, n_added, n_flag_kept = 0, 0, 0
    for key, ot, pt in updated:
        line_re = re.compile(r'^  "' + re.escape(key) + r'": \{overallTier:(\d+), posTier:(\d+), flag:([^}]*)\},$', re.M)
        existing = line_re.search(block)
        if existing:
            flag = existing.group(3)
            new_line = f'  "{key}": {{overallTier:{ot}, posTier:{pt}, flag:{flag}}},'
            block = block[:existing.start()] + new_line + block[existing.end():]
            n_updated += 1
            if flag.strip() != 'null':
                n_flag_kept += 1
        else:
            new_line = f'  "{key}": {{overallTier:{ot}, posTier:{pt}, flag:null}},'
            block = block.replace('\n};', '\n' + new_line + '\n};')
            n_added += 1

    print(f'{n_updated} existing DS_TIER_DATA entries updated ({n_flag_kept} kept a pre-existing flag, now stale/HFFL-era)')
    print(f'{n_added} new entries added')
    print(f'{len(ambiguous)} ambiguous last-name-only fallback matches skipped that field:')
    for a in ambiguous[:20]:
        print(f'  {a}')
    print(f'{len(not_found)} pool players not matched in any half-PPR pull (left untouched):')
    for nf in not_found:
        print(f'  {nf}')

    new_html = html[:ds_match.start()] + block + html[ds_match.end():]
    with open(HTML_PATH, 'w', encoding='utf-8', newline='\n') as f:
        f.write(new_html)
    print(f'\nWrote {HTML_PATH}')


if __name__ == '__main__':
    main()
