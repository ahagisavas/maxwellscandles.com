#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Refreshes the FantasyPros-ECR half of CONSENSUS_DATA ("name|POS": [ecr, ds_rk]) from a real
half-PPR export the user downloaded directly from FantasyPros -- confirmed via screenshot to be
scoped to Half-PPR / ABFFL / Tasi's Team specifically, not a generic/wrong-format pull.

Only touches the first array element (FantasyPros ECR). The second element (Draft Sharks RK, a
different source) is preserved exactly as-is -- not part of this refresh.

Gotcha hit and fixed here: the CSV labels team defenses "DST1".."DST32" in its POS column, but
this tool's own pool uses "DEF" as the position code everywhere else -- a first pass without the
POS_FIX mapping silently created dead "|DST"-keyed entries that would never match anything.

Re-running for a future refresh needs a fresh CSV at CSV_PATH -- this one won't still be in
Downloads/ later, and even if it were, it'd be stale. Re-download from FantasyPros with the same
scoring/league scoping confirmed (Half-PPR, and ideally "My Leagues: ABFFL" so it reflects any
league-specific settings) before pointing this at it again.
"""
import re, csv, json

HTML_PATH = r'C:\Users\Hagisavas\Documents\GitHub\maxwellscandles.com\HFFL\index.html'
CSV_PATH = r'C:\Users\Hagisavas\Downloads\FantasyPros_2026_Draft_ALL_Rankings.csv'  # re-download for future refreshes, see docstring


POS_FIX = {'DST': 'DEF'}  # CSV uses "DST1" for team defenses; the pool's own Pos code is "DEF"


def normalize_name_js(name):
    name = str(name or '').lower()
    name = re.sub(r'\b(jr|sr|ii|iii|iv|v)\.?\b', '', name)
    name = re.sub(r'[^a-z0-9]+', '', name)
    return name.strip()


def main():
    html = open(HTML_PATH, encoding='utf-8').read()
    m = re.search(r'const CONSENSUS_DATA = \{.*?\n\};', html, re.S)
    block = m.group(0)

    ecr_by_key = {}
    with open(CSV_PATH, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rk = row.get('RK', '').strip().strip('"')
            name = row.get('PLAYER NAME', '').strip().strip('"')
            pos_raw = row.get('POS', '').strip().strip('"')
            pos_match = re.match(r'^([A-Z]+)\d+$', pos_raw)
            pos = pos_match.group(1) if pos_match else None
            pos = POS_FIX.get(pos, pos)
            if not rk.isdigit() or not name or not pos:
                continue
            key = normalize_name_js(name) + '|' + pos
            ecr_by_key[key] = int(rk)

    print(f'Parsed {len(ecr_by_key)} players from CSV')

    updated, not_found = 0, []
    for key, ecr in ecr_by_key.items():
        line_re = re.compile(r'^  "' + re.escape(key) + r'": \[([^,]+), ([^\]]+)\],$', re.M)
        existing = line_re.search(block)
        if existing:
            ds_rk = existing.group(2)
            new_line = f'  "{key}": [{ecr}, {ds_rk}],'
            block = block[:existing.start()] + new_line + block[existing.end():]
            updated += 1
        else:
            new_line = f'  "{key}": [{ecr}, null],'
            block = block.replace('\n};', '\n' + new_line + '\n};')
            not_found.append(key)

    print(f'{updated} existing CONSENSUS_DATA entries updated with fresh half-PPR ECR')
    print(f'{len(not_found)} new entries added (were not in CONSENSUS_DATA before):')
    for nf in not_found[:30]:
        print(f'  {nf}')

    new_html = html[:m.start()] + block + html[m.end():]
    with open(HTML_PATH, 'w', encoding='utf-8', newline='\n') as f:
        f.write(new_html)
    print(f'\nWrote {HTML_PATH}')


if __name__ == '__main__':
    main()
