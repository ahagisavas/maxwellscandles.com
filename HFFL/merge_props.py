#!/usr/bin/env python3
"""
One-time merge of hand-verified BettingPros consensus lines (pulled live, player-by-player, from
bettingpros.com/nfl/odds/player-futures/ -- see qb_props_pull.md for the full trail) into the
PROPS_DATA block in index.html. Unlike refresh_fantasypros.py this isn't a repeatable/re-runnable
pipeline against an API -- it's a manual verification pass, run in stages (QB first, then RB/WR/TE).

Text-surgical, not JSON round-tripped: PROPS_DATA's inner field names (rushYds, recTd, ...) are
bare JS identifiers, not quoted JSON keys, so json.loads() can't parse the block at all. Instead
this finds each "key|POS": {...} line directly by regex and edits just that line in place --
existing untouched entries keep their exact original formatting.

MERGE POLICY: for each (name, pos) key below, only the fields actually present in the dict get
written -- an existing field not mentioned here is left untouched (e.g. Josh Allen's already-good
rushYds/rushTd aren't blanked out just because this pass also added passYds/passTd). A field is
only ever included below when a real consensus value was confirmed live -- no invented zeros.
"""
import re, json, os

HTML_PATH = r'C:\Users\Hagisavas\Documents\GitHub\maxwellscandles.com\HFFL\index.html'

# QB pass -- see qb_props_pull.md for the full source trail (consensus column, 3rd O/U pair,
# averaged when open/under split slightly).
QB_UPDATES = {
    ('Josh Allen', 'QB'):       {'passYds': 3600.5, 'rushYds': 500.5, 'passTd': 24.5, 'rushTd': 10.75},
    ('Jordan Love', 'QB'):      {'passYds': 3521.75},
    ('Baker Mayfield', 'QB'):   {'passYds': 3539.5},
    ('Matthew Stafford', 'QB'): {'passYds': 3850.5},
    ('Jared Goff', 'QB'):       {'passYds': 4050.5, 'passTd': 29.5},
    ('Brock Purdy', 'QB'):      {'passYds': 3775.5, 'rushTd': 2.5},
    ('Bo Nix', 'QB'):           {'passYds': 3477.75},
    ('Lamar Jackson', 'QB'):    {'passYds': 3247.0, 'rushTd': 3.5},
    ('Jayden Daniels', 'QB'):   {'passYds': 3250.5},
    ('Daniel Jones', 'QB'):     {'passTd': 18.5},
    ('Bryce Young', 'QB'):      {'passTd': 20.5, 'rushTd': 1.5},
    ('C.J. Stroud', 'QB'):      {'passTd': 22.5},
    ('Tyler Shough', 'QB'):     {'passTd': 20.5},
    ('Geno Smith', 'QB'):       {'passTd': 14.5},
    ('Aaron Rodgers', 'QB'):    {'passTd': 20.5},
    ('Justin Herbert', 'QB'):   {'passTd': 25.25},
    ('Joe Burrow', 'QB'):       {'passTd': 32.5},
    ('Cam Ward', 'QB'):         {'passTd': 20.0},
    ('Caleb Williams', 'QB'):   {'rushYds': 374.5},
    # RB/WR picked up incidentally while pulling the QB-shared Total Rushing Yards/TD markets --
    # real, verified the same way; kept now rather than re-fetched during the RB/WR pass.
    ('Jaylen Warren', 'RB'):        {'rushYds': 606.5},
    ('J.K. Dobbins', 'RB'):         {'rushYds': 675.5},
    ('RJ Harvey', 'RB'):            {'rushYds': 749.5},
    ('Bucky Irving', 'RB'):         {'rushYds': 800.5},
    ('Jonathan Taylor', 'RB'):      {'rushYds': 1250.5},
    ('Kenneth Walker III', 'RB'):   {'rushYds': 925.5},
    ('Quinshon Judkins', 'RB'):     {'rushYds': 900.5},
    ("De'Von Achane", 'RB'):        {'rushYds': 975.5},
    ('Javonte Williams', 'RB'):     {'rushTd': 9.5},
    ('Josh Jacobs', 'RB'):          {'rushTd': 7.5},
    ('Rhamondre Stevenson', 'RB'):  {'rushTd': 5.5},
    ('Zay Flowers', 'WR'):          {'rushTd': 0.5},
    ('Puka Nacua', 'WR'):           {'rushTd': 0.5},
}

# RB/WR/TE pass -- Total Receiving Yards / Total Receiving Touchdowns / Total Receptions, pulled
# live the same way (consensus column, 3rd O/U button-pair). Single-initial site names (e.g.
# "D. Kincaid") were cross-checked against DEFAULT_PLAYER_ROWS below before merge -- see
# qb_props_pull.md "FULL PLAYER-KEY MAP" section for the resolution notes. G. Holani (SEA-RB,
# Total Receiving TDs) was dropped -- only 1 book quoting a +1000 longshot line, not a real
# consensus. Kenneth Walker III already has rushYds from the QB-phase pass (picked up incidentally
# on the same Total Rushing Yards page); this pass only adds recYds, existing rushYds untouched.
RBWRTE_UPDATES = {
    ('Stefon Diggs', 'WR'):        {'recYds': 774.5},
    ('Pat Freiermuth', 'TE'):      {'recYds': 425.5},
    ('Brenton Strange', 'TE'):     {'recYds': 475.5, 'receptions': 44.5},
    ('Kyle Pitts Sr.', 'TE'):      {'recYds': 756.5},
    ('Gunnar Helm', 'TE'):         {'recYds': 350.5, 'recTd': 2.5},
    ('Jaylen Waddle', 'WR'):       {'recYds': 910.0},
    ('Trey McBride', 'TE'):        {'recYds': 950.5},
    ('Kenneth Walker III', 'RB'):  {'recYds': 299.5},
    ('DJ Moore', 'WR'):            {'recYds': 800.5, 'recTd': 6.5, 'receptions': 59.5},
    ('Josh Downs', 'WR'):          {'recYds': 800.0},
    ('Luther Burden III', 'WR'):   {'recTd': 4.5},
    ('Tre Tucker', 'WR'):          {'recTd': 3.0},
    ('Cam Skattebo', 'RB'):        {'recTd': 1.5},
    ('Jahmyr Gibbs', 'RB'):        {'recTd': 3.5, 'receptions': 60.5},
    ('Malik Nabers', 'WR'):        {'recTd': 5.5},
    ('Jakobi Meyers', 'WR'):       {'recTd': 5.5},
    ('Travis Kelce', 'TE'):        {'recTd': 4.5},
    ('Dalton Kincaid', 'TE'):      {'receptions': 48.5},
    ('Romeo Doubs', 'WR'):         {'receptions': 56.5},
    ('Derrick Henry', 'RB'):       {'receptions': 17.5},
    ('Justin Jefferson', 'WR'):    {'receptions': 92.5},
    ('Davante Adams', 'WR'):       {'receptions': 60.5},
    ('Jake Ferguson', 'TE'):       {'receptions': 66.5},
    ('Garrett Wilson', 'WR'):      {'receptions': 84.5},
}


def normalize_name(name):
    name = str(name or '').lower()
    name = re.sub(r'\b(jr|sr|ii|iii|iv|v)\.?\b', '', name)
    name = re.sub(r'[^a-z0-9]+', '', name)
    return name.strip()


def parse_fields(body):
    """'rushYds: 483.5, rushTd: 8.5' -> {'rushYds': 483.5, 'rushTd': 8.5}, preserving field order."""
    fields = {}
    for part in body.split(','):
        part = part.strip()
        if not part:
            continue
        k, v = part.split(':', 1)
        fields[k.strip()] = float(v.strip())
    return fields


def render_fields(fields):
    return ', '.join(f'{k}: {v}' for k, v in fields.items())


def load_pool(html):
    headers_src = re.search(r'const DEFAULT_PLAYER_HEADERS = (\[.*?\]);', html).group(1)
    headers = json.loads(headers_src)
    rows_src = re.search(r'const DEFAULT_PLAYER_ROWS = (\[\n.*?\n\]);', html, re.S).group(1)
    rows_src = re.sub(r',(\s*\])$', r'\1', rows_src)
    rows = json.loads(rows_src)
    return headers, rows


def main():
    html = open(HTML_PATH, encoding='utf-8').read()

    m = re.search(r'const PROPS_DATA = \{.*?\n\};', html, re.S)
    block = m.group(0)

    headers, rows = load_pool(html)
    idx = {h: i for i, h in enumerate(headers)}
    name_i, pos_i = idx['Player'], idx['Pos']
    pool_names = {(normalize_name(r[name_i]), r[pos_i]) for r in rows}

    updated, added, not_in_pool = [], [], []
    new_lines_to_append = []

    # Two sequential passes (not a merged dict) -- a name can appear in both stages with
    # different fields (e.g. Kenneth Walker III: rushYds from the QB-phase pass, recYds from
    # this one), and each pass must layer onto whatever the line already has, not replace it.
    for updates in (QB_UPDATES, RBWRTE_UPDATES):
        for (name, pos), new_fields in updates.items():
            pool_key = (normalize_name(name), pos)
            if pool_key not in pool_names:
                not_in_pool.append(f'{name} ({pos})')
                continue
            key = normalize_name(name) + '|' + pos
            line_re = re.compile(r'^  "' + re.escape(key) + r'": \{([^}]*)\},$', re.M)
            existing = line_re.search(block)
            if existing:
                fields = parse_fields(existing.group(1))
                fields.update(new_fields)
                new_line = f'  "{key}": {{{render_fields(fields)}}},'
                block = block[:existing.start()] + new_line + block[existing.end():]
                updated.append(f'{name} ({pos}): now {fields}')
            else:
                new_lines_to_append.append(f'  "{key}": {{{render_fields(new_fields)}}},')
                added.append(f'{name} ({pos}): {new_fields}')

    if new_lines_to_append:
        block = block.replace('\n};', '\n' + '\n'.join(new_lines_to_append) + '\n};')

    print(f'{len(updated)} existing PROPS_DATA entries updated:')
    for u in updated:
        print(f'  {u}')
    print(f'{len(added)} new PROPS_DATA entries added:')
    for a in added:
        print(f'  {a}')
    if not_in_pool:
        print(f'{len(not_in_pool)} names not found in the pool at all (skipped):')
        for n in not_in_pool:
            print(f'  {n}')

    new_html = html[:m.start()] + block + html[m.end():]
    with open(HTML_PATH, 'w', encoding='utf-8', newline='\n') as f:
        f.write(new_html)
    print(f'\nWrote {HTML_PATH}')


if __name__ == '__main__':
    main()
