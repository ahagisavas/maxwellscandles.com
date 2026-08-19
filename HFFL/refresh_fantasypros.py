#!/usr/bin/env python3
"""
refresh_fantasypros.py -- regenerate the draft tool's embedded skill-player projections from
FantasyPros' API, on demand (e.g. morning of draft day).

WHAT THIS DOES
  1. Pulls per-stat season projections for QB/RB/WR/TE/K/DST (6 calls) + player ECR/ADP
     metadata (1 call) from FantasyPros' API.
  2. Maps FantasyPros' stat field names onto this tool's own schema (Importer.FIELD_ALIASES /
     STAT_FIELDS in index.html).
  3. Merges those fresh values into the *existing* embedded player pool, matched by normalized
     name + position (same normalizeName() logic index.html itself uses for Sleeper matching) --
     it does NOT replace the pool wholesale. Fields FantasyPros doesn't project at all for a given
     position (Return Yds/TD, DEF Points-Allowed-season -- see NOTE below) are left exactly as
     they already are, not blanked out. Players already in the pool with no FantasyPros match are
     left untouched. New-to-FantasyPros players not already in the pool are NOT added (pool size
     changes affect VBD replacement baselines and deserve a deliberate look, not a silent refresh
     side effect) -- they're only reported.
  4. Rewrites the DEFAULT_PLAYER_ROWS block in index.html in place, byte-for-byte compatible with
     every other cell (only the mapped fields for matched players actually change).

NOTE on DST kicking/defense data: FantasyPros' DST projections do not include a points-allowed
figure in any form (the def_pa_* fields exist in their response but are always 0/unpopulated --
apparently not a stat they project per-team for a future season). This script deliberately does
NOT touch the "Points Allowed (season)" column for that reason -- overwriting real historical
data with an all-zero field would be a regression, not a refresh. Same reasoning for Return Yds /
Return TD, which FantasyPros' base projections don't carry at all (that data in the pool came from
a separate manual research pass on BettingPros/RotoWire/DraftSharks earlier in this project).

USAGE
  Live (calls the real API; needs a valid key):
      python refresh_fantasypros.py --key-file path/to/key.txt
    or set the FANTASYPROS_API_KEY environment variable and omit --key-file.

  From an already-fetched cache (skips the API entirely -- useful for re-running the merge/debug
  logic without spending API calls, or if the live endpoint is temporarily unreachable):
      python refresh_fantasypros.py --from-cache path/to/folder/containing/projections_*.json

  Dry run (report what WOULD change without writing the file):
      python refresh_fantasypros.py --from-cache <dir> --dry-run

KNOWN ISSUE (as of 2026-08-19): live --key-file / env-var mode currently gets HTTP 403
"Missing Authentication Token" from api.fantasypros.com regardless of the key used, both via a
direct HTTPS client and via a real browser fetch() (which additionally hit a CORS block) -- this
looks like a FantasyPros-side API Gateway/WAF change since this key last worked, not a problem
with this script's request shape (the URL path/params match FantasyPros' documented contract
exactly, and the same key + shape worked when the projections_*.json cache used by --from-cache
was captured on 2026-08-18). If --key-file/env-var mode still 403s for you, check the FantasyPros
account's API dashboard for the key's status before assuming this script is broken.
"""
import sys, os, re, json, argparse, urllib.request, urllib.error

HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')
API_BASE = 'https://api.fantasypros.com/public/v2/json'
SEASON = 2026
POSITIONS = ['QB', 'RB', 'WR', 'TE', 'K', 'DST']
POS_TO_TOOL = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'TE': 'TE', 'K': 'K', 'DST': 'DEF'}

# ---- name/team normalization, mirrored from index.html's own normalizeName()/normalizeTeam() ----
def normalize_name(name):
    name = str(name or '').lower()
    name = re.sub(r'\b(jr|sr|ii|iii|iv|v)\.?\b', '', name)
    name = re.sub(r'[^a-z0-9]+', '', name)
    return name.strip()

# ---- field mapping: FantasyPros stats key -> this tool's canonical STAT_FIELDS name ----
# Deliberately excludes: rush_yds_100/200, rec_yds_100/200, scrimage_yards_*, ret_tds, 2pt_tds,
# def_pa_* (see module docstring) -- either milestone-bonus counters this league doesn't score,
# or fields FantasyPros always returns empty for.
OFFENSE_MAP = {
    'pass_yds': 'passYds', 'pass_tds': 'passTd', 'pass_ints': 'passInt',
    'rush_yds': 'rushYds', 'rush_tds': 'rushTd',
    'rec_yds': 'recYds', 'rec_tds': 'recTd', 'rec_rec': 'receptions',
    'fumbles': 'fumblesLost',  # confirmed fumbles-LOST (not total) via points reconciliation earlier this project
}
KICKING_MAP = {'fg': 'fgMade', 'fga': 'fgAttempted', 'xpt': 'patMade'}
DEFENSE_MAP = {
    'def_sack': 'sacks', 'def_int': 'defInt', 'def_fr': 'fumbleRecovery',
    'def_td': 'defTd', 'def_safety': 'safety',
}

# Canonical STAT_FIELDS name -> the exact column header string in DEFAULT_PLAYER_HEADERS.
FIELD_TO_HEADER = {
    'passYds': 'Pass Yds', 'passTd': 'Pass TD', 'passInt': 'INT',
    'rushYds': 'Rush Yds', 'rushTd': 'Rush TD',
    'recYds': 'Rec Yds', 'recTd': 'Rec TD', 'receptions': 'Rec',
    'fumblesLost': 'Fum Lost',
    'fgMade': 'FG Made', 'fgAttempted': 'FG Attempted', 'patMade': 'PAT Made',
    'sacks': 'Sacks', 'defInt': 'DEF INT', 'fumbleRecovery': 'Fumble Recovery',
    'defTd': 'DEF TD', 'safety': 'Safety',
}


def fetch_json(path, api_key):
    req = urllib.request.Request(API_BASE + path, headers={'x-api-key': api_key, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode('utf-8'))


def load_live(api_key):
    print('Fetching live from FantasyPros API...')
    proj = {}
    for pos in POSITIONS:
        print(f'  GET projections position={pos} ...', end=' ')
        d = fetch_json(f'/nfl/{SEASON}/projections?position={pos}&week=0', api_key)
        print(f"tier={d.get('tier')} count={d.get('count')}")
        proj[pos] = d
    print('  GET players (ECR/ADP) ...', end=' ')
    players_adp = fetch_json(f'/nfl/players?ecr=included&show=pos_rank', api_key)
    print(f"tier={players_adp.get('tier')} count={players_adp.get('count')}")
    return proj, players_adp


def load_from_cache(cache_dir):
    print(f'Loading cached FantasyPros pull from {cache_dir} ...')
    proj = {}
    for pos in POSITIONS:
        path = os.path.join(cache_dir, f'projections_{pos}.json')
        d = json.load(open(path, encoding='utf-8'))
        print(f'  {pos}: tier={d.get("tier")} count={d.get("count")} (file: {os.path.basename(path)})')
        proj[pos] = d
    adp_path = os.path.join(cache_dir, 'players_adp.json')
    players_adp = json.load(open(adp_path, encoding='utf-8'))
    print(f'  players/ADP: tier={players_adp.get("tier")} count={players_adp.get("count")}')
    return proj, players_adp


def build_new_stats(proj):
    """(normalized_name, tool_position) -> {canonical_field: value, ...}, plus a raw team_id per key."""
    new_stats = {}
    new_team = {}
    for fp_pos, tool_pos in POS_TO_TOOL.items():
        field_map = OFFENSE_MAP if tool_pos in ('QB', 'RB', 'WR', 'TE') else (KICKING_MAP if tool_pos == 'K' else DEFENSE_MAP)
        for p in proj[fp_pos]['players']:
            s = p.get('stats') or {}
            key = (normalize_name(p['name']), tool_pos)
            stat = {}
            for fp_field, canon in field_map.items():
                if fp_field in s and s[fp_field] is not None:
                    stat[canon] = s[fp_field]
            new_stats[key] = stat
            new_team[key] = p.get('team_id') or ''
    return new_stats, new_team


def load_pool(html):
    headers_src = re.search(r'const DEFAULT_PLAYER_HEADERS = (\[.*?\]);', html).group(1)
    try:
        headers = json.loads(headers_src)
    except json.JSONDecodeError:
        headers = json.loads(headers_src.replace("'", '"'))
    rows_src = re.search(r'const DEFAULT_PLAYER_ROWS = (\[\n.*?\n\]);', html, re.S).group(1)
    rows_src = re.sub(r',(\s*\])$', r'\1', rows_src)  # JS allows a trailing comma before ']'; JSON doesn't
    rows = json.loads(rows_src)
    return headers, rows


def render_rows(rows):
    lines = ['const DEFAULT_PLAYER_ROWS = [']
    for row in rows:
        lines.append(json.dumps(row, ensure_ascii=False) + ',')
    lines.append('];')
    return '\n'.join(lines)


def fmt(v):
    return f'{v:.1f}'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--key-file', help='Path to a file containing just the FantasyPros API key (git-ignored; never commit this).')
    ap.add_argument('--from-cache', help='Folder containing projections_QB.json..projections_DST.json + players_adp.json -- skips live API calls entirely.')
    ap.add_argument('--dry-run', action='store_true', help='Report what would change without writing index.html.')
    args = ap.parse_args()

    if args.from_cache:
        proj, players_adp = load_from_cache(args.from_cache)
    else:
        api_key = None
        if args.key_file:
            api_key = open(args.key_file, encoding='utf-8').read().strip()
        elif os.environ.get('FANTASYPROS_API_KEY'):
            api_key = os.environ['FANTASYPROS_API_KEY']
        else:
            print('No --from-cache, no --key-file, and FANTASYPROS_API_KEY is not set. Nothing to do.', file=sys.stderr)
            sys.exit(1)
        proj, players_adp = load_live(api_key)

    new_stats, new_team = build_new_stats(proj)

    html = open(HTML_PATH, encoding='utf-8').read()
    headers, rows = load_pool(html)
    idx = {h: i for i, h in enumerate(headers)}
    name_i, team_i, pos_i = idx['Player'], idx['Team'], idx['Pos']

    matched, unmatched_old, changed_players = 0, [], []
    for row in rows:
        name, pos = row[name_i], row[pos_i]
        key = (normalize_name(name), pos)
        if key not in new_stats:
            unmatched_old.append(f'{name} ({pos})')
            continue
        matched += 1
        stat = new_stats[key]
        row_deltas = []
        for field, new_val in stat.items():
            header = FIELD_TO_HEADER.get(field)
            if not header:
                continue
            col = idx[header]
            old_str = row[col]
            new_str = fmt(new_val)
            if old_str != new_str:
                row_deltas.append(f'{header}: {old_str or "(blank)"} -> {new_str}')
                row[col] = new_str
        new_team_code = new_team.get(key)
        if new_team_code and new_team_code != row[team_i]:
            row_deltas.append(f'Team: {row[team_i]} -> {new_team_code}')
            row[team_i] = new_team_code
        if row_deltas:
            changed_players.append((name, pos, row_deltas))

    new_in_fp_not_in_pool = 0
    pool_keys = {(normalize_name(r[name_i]), r[pos_i]) for r in rows}
    for key in new_stats:
        if key not in pool_keys:
            new_in_fp_not_in_pool += 1

    print()
    print(f'Matched {matched}/{len(rows)} pool players to fresh FantasyPros data.')
    print(f'{len(changed_players)} players had at least one field actually change value.')
    print(f'{len(unmatched_old)} pool players had no FantasyPros match (left untouched).')
    print(f'{new_in_fp_not_in_pool} FantasyPros players not already in the pool were seen (not added -- pool size changes need a deliberate look).')
    print()
    print('Biggest changes (by number of fields changed), sample:')
    changed_players.sort(key=lambda x: -len(x[2]))
    for name, pos, deltas in changed_players[:15]:
        print(f'  {name} ({pos}): ' + '; '.join(deltas))

    if args.dry_run:
        print('\n--dry-run: not writing index.html.')
        return

    new_rows_block = render_rows(rows)
    new_html = re.sub(r'const DEFAULT_PLAYER_ROWS = \[\n.*?\n\];', lambda m: new_rows_block, html, count=1, flags=re.S)
    with open(HTML_PATH, 'w', encoding='utf-8', newline='\n') as f:
        f.write(new_html)
    print(f'\nWrote {HTML_PATH}')


if __name__ == '__main__':
    main()
