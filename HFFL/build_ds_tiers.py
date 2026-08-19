#!/usr/bin/env python3
"""
build_ds_tiers.py -- build/refresh the embedded DS_TIER_DATA block in index.html from a Draft
Sharks "Draft War Room" export for the user's specific league (already tuned to its exact roster
settings and scoring, unlike a generic Draft Sharks rankings pull).

WHAT THIS ADDS (separate from, and additive to, the existing CONSENSUS_DATA Draft Sharks rank):
  - Draft Sharks' own OVERALL TIER and POSITION TIER per player -- used only when "Rank by Draft
    Sharks ONLY" is checked (see UI.retierForDisplay()), so the Tier column shows Draft Sharks'
    actual tier boundaries in that mode instead of this tool's own algorithmic gap-clustering.
    More faithful to what Draft Sharks means by "tier" than re-deriving one from their rank order.
  - Draft Sharks' column-A qualitative flag (Value / Sleeper / Bust / Handcuff Flyer / etc.) as a
    new badge -- deliberately EXCLUDING "Injured" (the tool already tracks injury status from its
    own, more authoritative source: Sleeper sync / the embedded default data's Injury Status
    field -- a second, possibly-stale "Injured" tag from a static CSV export would just be
    redundant/conflicting, not additive).

Expected CSV columns (exact header): "","Rank","Player","Overall Tier","Pos. Tier","Pos","Team",
"Bye","ADP","Floor","Consensus","DS Proj","Ceiling","3D Proj","3d Value" -- only the unlabeled
first column (classification), Player, Overall Tier, Pos. Tier, and Pos are used here.

USAGE
    python build_ds_tiers.py --csv "path/to/Haraki Fantasy Football League.csv"
    Add --dry-run to see the match report without writing index.html.
"""
import sys, os, re, csv, json, argparse

HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')


def normalize_name(name):
    name = str(name or '').lower()
    name = re.sub(r'\b(jr|sr|ii|iii|iv|v)\.?\b', '', name)
    name = re.sub(r'[^a-z0-9]+', '', name)
    return name.strip()


def name_key_candidates(name):
    """Draft Sharks writes nicknamed players as e.g. `Cameron 'Cam' Ward` -- this tool's own pool
    uses just the common form (`Cam Ward`). A plain normalize_name() on the quoted form garbles
    into one run-on string matching neither. Returns every plausible normalized key: the name as
    given, and -- when a quoted nickname is present -- the nickname substituted for the first name
    instead of run alongside it."""
    keys = [normalize_name(name)]
    m = re.match(r"^(\S+)\s+['‘’](\w[\w.]*)['‘’]\s+(.+)$", name)
    if m:
        first, nickname, rest = m.groups()
        keys.append(normalize_name(f'{nickname} {rest}'))  # e.g. "Cam Ward"
        keys.append(normalize_name(f'{first} {rest}'))     # e.g. "Cameron Ward" (nickname dropped, not substituted)
    return keys


def load_pool(html):
    headers_src = re.search(r'const DEFAULT_PLAYER_HEADERS = (\[.*?\]);', html).group(1)
    try:
        headers = json.loads(headers_src)
    except json.JSONDecodeError:
        headers = json.loads(headers_src.replace("'", '"'))
    rows_src = re.search(r'const DEFAULT_PLAYER_ROWS = (\[\n.*?\n\]);', html, re.S).group(1)
    rows_src = re.sub(r',(\s*\])$', r'\1', rows_src)
    rows = json.loads(rows_src)
    return headers, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--csv', required=True)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    combined = {}
    flag_counts = {}
    with open(args.csv, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        first_col = reader.fieldnames[0]  # unlabeled classification column
        for r in reader:
            name = r.get('Player')
            pos = r.get('Pos')
            if not name or not pos:
                continue
            try:
                overall_tier = float(r['Overall Tier'])
                pos_tier = float(r['Pos. Tier'])
            except (KeyError, ValueError, TypeError):
                continue
            flag = (r.get(first_col) or '').strip()
            if flag.lower() == 'injured':
                flag = ''  # tool already tracks injury status from a more authoritative source
            if flag:
                flag_counts[flag] = flag_counts.get(flag, 0) + 1
            entry = {'name': name, 'overallTier': int(overall_tier), 'posTier': int(pos_tier), 'flag': flag}
            for base_key in name_key_candidates(name):
                combined[base_key + '|' + pos] = entry

    print(f'Loaded {len(combined)} players from {os.path.basename(args.csv)}')
    print('Column-A classification counts (excl. Injured):', flag_counts)

    html = open(HTML_PATH, encoding='utf-8').read()
    headers, rows = load_pool(html)
    idx = {h: i for i, h in enumerate(headers)}
    name_i, pos_i = idx['Player'], idx['Pos']

    matched = sum(1 for row in rows if (normalize_name(row[name_i]) + '|' + row[pos_i]) in combined)
    unmatched_pool = [f'{row[name_i]} ({row[pos_i]})' for row in rows
                       if (normalize_name(row[name_i]) + '|' + row[pos_i]) not in combined]

    print()
    print(f'Matched {matched}/{len(rows)} pool players to Draft Sharks tier data.')
    print(f'{len(unmatched_pool)} pool players had no match:')
    for n in unmatched_pool[:20]:
        print(f'  - {n}')
    if len(unmatched_pool) > 20:
        print(f'  ... and {len(unmatched_pool)-20} more')

    if args.dry_run:
        print('\n--dry-run: not writing index.html.')
        return

    lines = ['const DS_TIER_DATA = {']
    for key in sorted(combined):
        v = combined[key]
        lines.append(f'  "{key}": {{overallTier:{v["overallTier"]}, posTier:{v["posTier"]}, flag:{json.dumps(v["flag"]) if v["flag"] else "null"}}},')
    lines.append('};')
    block = '\n'.join(lines)

    marker_start = '/* ===== DS_TIER_DATA ===== */'
    marker_end = '/* ===== END DS_TIER_DATA ===== */'
    full_block = f'{marker_start}\n{block}\n{marker_end}'

    if marker_start in html:
        new_html = re.sub(re.escape(marker_start) + r'.*?' + re.escape(marker_end), lambda m: full_block, html, count=1, flags=re.S)
    else:
        anchor = re.search(r'/\* ===== END FFBALLERS_DATA ===== \*/\n', html).group(0)
        new_html = html.replace(anchor, anchor + '\n' + full_block + '\n', 1)

    with open(HTML_PATH, 'w', encoding='utf-8', newline='\n') as f:
        f.write(new_html)
    print(f'\nWrote {HTML_PATH} ({len(combined)} DS_TIER_DATA entries).')


if __name__ == '__main__':
    main()
