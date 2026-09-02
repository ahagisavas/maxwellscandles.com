#!/usr/bin/env python3
"""
build_ffballers_data.py -- build/refresh the embedded FFBALLERS_DATA block in index.html from
The Fantasy Footballers podcast's (Andy/Jason/Mike) position-only draft rankings CSVs.

WHY THIS EXISTS / WHY IT'S DIFFERENT FROM refresh_fantasypros.py's CONSENSUS_DATA:
FantasyPros ECR and Draft Sharks RK (CONSENSUS_DATA) are OVERALL cross-position ranks -- a WR
ranked #23 there really did place 23rd among every position combined, so they sort correctly in
a mixed "ALL positions" view with zero extra work. The Footballers' CSVs only rank within one
position at a time (their WR sheet is 1..132 among WRs only, RB sheet is 1..92 among RBs only,
etc.) -- there is no source of a cross-position number here at all. index.html's "Rank by
FFBallers ONLY" pure mode handles this by borrowing the tool's OWN VBD scale as the cross-position
currency (see UI.effectiveValue()/ffPosSlots in index.html): line up this tool's players at a
position by VBD, then substitute in whoever the Footballers rank Nth for whoever VBD ranks Nth,
at every N. This script's only job is producing the raw per-position rank data that trick runs on
-- it does NOT need to (and cannot) produce a cross-position number itself.

USAGE
    python build_ffballers_data.py \
        --wr "path/to/2026 WR Draft Rankings - Fantasy Footballers Podcast.csv" \
        --rb "path/to/2026 RB Draft Rankings - Fantasy Footballers Podcast.csv" \
        --te "path/to/2026 TE Draft Rankings - Fantasy Footballers Podcast.csv" \
        --qb "path/to/2026 QB Draft Rankings - Fantasy Footballers Podcast.csv" \
        [--host Rank|Andy|Jason|Mike]

    Add --dry-run to see the match report without writing index.html.

Expected CSV columns (exact header, one file per position): "Name","Team","Rank","Andy","Jason","Mike"
--host selects which column becomes FFBALLERS_DATA's rank value; default "Rank" is the Footballers'
own blended composite of the three hosts. As of 2026-09-01 this tool is run with --host Mike
specifically (explicit user choice -- "only use Mike's Rankings", moving off the blended default).
If reusing this for a future refresh, confirm which host is still wanted rather than assuming Mike.
"""
import sys, os, re, csv, json, argparse

HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')
POSITIONS = ['QB', 'RB', 'WR', 'TE']


def normalize_name(name):
    name = str(name or '').lower()
    name = re.sub(r'\b(jr|sr|ii|iii|iv|v)\.?\b', '', name)
    name = re.sub(r'[^a-z0-9]+', '', name)
    return name.strip()


def load_position_csv(path, pos, host):
    rows = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for r in reader:
            name = r.get('Name')
            rank = r.get(host)
            if not name or not rank:
                continue
            key = normalize_name(name) + '|' + pos
            rows[key] = {'name': name, 'rank': int(rank)}
    return rows


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
    ap.add_argument('--wr', required=True)
    ap.add_argument('--rb', required=True)
    ap.add_argument('--te', required=True)
    ap.add_argument('--qb', required=True)
    ap.add_argument('--host', default='Rank', choices=['Rank', 'Andy', 'Jason', 'Mike'])
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    print(f'Using host column: {args.host}')
    combined = {}
    for pos, path in [('WR', args.wr), ('RB', args.rb), ('TE', args.te), ('QB', args.qb)]:
        posrows = load_position_csv(path, pos, args.host)
        print(f'{pos}: {len(posrows)} players loaded from {os.path.basename(path)}')
        combined.update(posrows)

    html = open(HTML_PATH, encoding='utf-8').read()
    headers, rows = load_pool(html)
    idx = {h: i for i, h in enumerate(headers)}
    name_i, pos_i = idx['Player'], idx['Pos']

    matched, unmatched_pool = 0, []
    for row in rows:
        key = normalize_name(row[name_i]) + '|' + row[pos_i]
        if key in combined:
            matched += 1
        elif row[pos_i] in POSITIONS:
            unmatched_pool.append(f'{row[name_i]} ({row[pos_i]})')

    pool_keys = {normalize_name(r[name_i]) + '|' + r[pos_i] for r in rows}
    unmatched_ff = [v['name'] + f" ({k.split('|')[1]})" for k, v in combined.items() if k not in pool_keys]

    print()
    print(f'Matched {matched}/{len(rows)} pool players (QB/RB/WR/TE) to Footballers data.')
    print(f'{len(unmatched_pool)} pool players (QB/RB/WR/TE) had no Footballers match:')
    for n in unmatched_pool[:20]:
        print(f'  - {n}')
    if len(unmatched_pool) > 20:
        print(f'  ... and {len(unmatched_pool)-20} more')
    print(f'{len(unmatched_ff)} Footballers entries had no pool match (not added -- same policy as refresh_fantasypros.py):')
    for n in unmatched_ff[:20]:
        print(f'  - {n}')
    if len(unmatched_ff) > 20:
        print(f'  ... and {len(unmatched_ff)-20} more')

    if args.dry_run:
        print('\n--dry-run: not writing index.html.')
        return

    lines = ['const FFBALLERS_DATA = {']
    for key in sorted(combined):
        lines.append(f'  "{key}": {combined[key]["rank"]},')
    lines.append('};')
    block = '\n'.join(lines)

    marker_start = '/* ===== FFBALLERS_DATA ===== */'
    marker_end = '/* ===== END FFBALLERS_DATA ===== */'
    full_block = f'{marker_start}\n{block}\n{marker_end}'

    if marker_start in html:
        new_html = re.sub(re.escape(marker_start) + r'.*?' + re.escape(marker_end), lambda m: full_block, html, count=1, flags=re.S)
    else:
        # First run: insert right after CONSENSUS_WEIGHTS' declaration line.
        anchor = re.search(r'const CONSENSUS_WEIGHTS = \{[^\n]*\};\n', html).group(0)
        new_html = html.replace(anchor, anchor + '\n' + full_block + '\n', 1)

    with open(HTML_PATH, 'w', encoding='utf-8', newline='\n') as f:
        f.write(new_html)
    print(f'\nWrote {HTML_PATH} ({len(combined)} FFBALLERS_DATA entries).')


if __name__ == '__main__':
    main()
