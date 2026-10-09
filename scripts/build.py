#!/usr/bin/env python3
"""Builds the profile cards in assets/ from live GitHub data.

    python scripts/build.py        # needs fonttools, and GH_TOKEN or a logged-in gh

All text is drawn as outlines from the two fonts in scripts/fonts (Archivo and
JetBrains Mono, both OFL), because an SVG shown through <img> cannot load fonts
and would otherwise fall back to whatever the viewer has installed.
"""
import base64
import html
import http.client
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from datetime import date
from functools import lru_cache
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

# ---- Edit these, then re-run -------------------------------------------------
LOGIN = 'ArdenDiago'
NAME = 'Arden Diago'
ROLE = 'Cloud & DevOps Engineer'
TAGLINE = [
    'I run CI/CD pipelines, containers and AWS infrastructure',
    'in production, with security and observability built in.',
]
STATUS = 'Open to Cloud internships, Jan to May 2027'
PLACE = 'MCA, CHRIST University, Bengaluru'
# The real delivery pipeline of ardend.dev (.github/workflows/deploy.yml there)
PIPELINE = [
    ('Checkout', 'push to main'), ('Install', 'client + server'), ('Test', 'Vitest suites'),
    ('Bake data', 'MongoDB to HTML'), ('Build image', 'Docker, 2 stages'), ('Deploy', 'Fly.io, Mumbai'),
]
# Markup and styling, left off the languages card
SKIP = {'HTML', 'CSS', 'SCSS'}
# Folded into one Infrastructure row. GitHub reports these three as languages...
INFRA_LANGS = {'HCL': 'Terraform', 'Dockerfile': 'Docker', 'Shell': 'Shell'}
# ...and these are found by path, because GitHub's language stats ignore YAML
INFRA_PATHS = {
    'YAML': re.compile(r'\.ya?ml$'),
    'Terraform': re.compile(r'\.(tf|tfvars|hcl)$'),
    'Ansible': re.compile(r'(^|/)(ansible[^/]*|playbooks?|roles/[^/]+/tasks)/|(^|/)ansible\.cfg$', re.I),
}
VENDORED = re.compile(r'(^|/)(node_modules|vendor|\.?venv|dist|build)/|lock\.ya?ml$')
# ------------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'assets'
W = 840

# Tokens from the ardend.dev design system
PANEL, RAISED, INSET = '#11141D', '#1A1E2B', '#0D1018'
SEAM, SEAM_STRONG = '#222739', '#353C55'
INK, SOFT, MUTED = '#ECEEF6', '#B6BCCD', '#8D95AB'
KW, STR = '#7C93FF', '#4ADE9C'
HEAT = [RAISED, '#2A3466', '#3F4FA3', '#5A72D9', KW]

SANS, MONO = 'archivo-latin', 'jetbrains-mono-latin'


@lru_cache(maxsize=None)
def face(font, wght):
    f = TTFont(ROOT / 'scripts' / 'fonts' / f'{font}.ttf')
    loc = {'wght': wght, 'wdth': 88} if font == SANS else {'wght': wght}
    return f.getGlyphSet(location=loc), f.getBestCmap()


def outline(s, font, wght, track):
    glyphs, cmap = face(font, wght)
    pen, x = SVGPathPen(glyphs, ntos=lambda v: str(round(v))), 0
    for ch in s:
        g = glyphs[cmap.get(ord(ch), '.notdef')]
        g.draw(TransformPen(pen, (1, 0, 0, 1, x, 0)))
        x += g.width + track * 1000
    return pen.getCommands(), x


def measure(s, size, font=MONO, wght=400, track=0):
    return outline(s, font, wght, track)[1] * size / 1000


def text(x, y, s, size, fill=INK, font=MONO, wght=400, anchor='start', track=0):
    d, adv = outline(s, font, wght, track)
    k = size / 1000
    x -= adv * k * {'start': 0, 'middle': .5, 'end': 1}[anchor]
    return f'<path fill="{fill}" transform="translate({x:.1f} {y}) scale({k:.4f} -{k:.4f})" d="{d}"/>'


def card(h, label, body, defs=''):
    label = html.escape(label)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" role="img" aria-label="{label}">'
        f'<title>{label}</title><defs>{defs}</defs>'
        f'<rect x=".5" y=".5" width="{W - 1}" height="{h - 1}" rx="16" fill="{PANEL}" stroke="{SEAM}"/>'
        f'{body}</svg>\n'
    )


@lru_cache(maxsize=None)
def token():
    return os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN') \
        or subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, check=True).stdout.strip()


def api(path, body=None):
    req = urllib.request.Request(
        f'https://api.github.com/{path}',
        body and json.dumps(body).encode(),
        {'Authorization': f'Bearer {token()}', 'User-Agent': LOGIN},
    )
    for attempt in range(3):
        try:
            return json.load(urllib.request.urlopen(req, timeout=30))
        except http.client.IncompleteRead:  # a very large file tree can be cut off mid-read
            if attempt == 2:
                raise


def fetch():
    query = '''query($login: String!) { user(login: $login) {
      followers { totalCount }
      repositories(ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false, first: 100) {
        totalCount nodes { stargazerCount } }
      # Private repositories too, when the token can read them
      code: repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
        totalCount nodes { name languages(first: 20) { edges { node { name color } } } } }
      contributionsCollection { contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } } }
    } }'''
    res = api('graphql', {'query': query, 'variables': {'login': LOGIN}})
    if res.get('errors'):
        raise SystemExit(res['errors'])
    return res['data']['user']


def streak(counts):
    """Consecutive active days ending today, or yesterday if today is still empty."""
    days = counts[:-1] if counts and counts[-1] == 0 else counts
    n = 0
    for c in reversed(days):
        if c == 0:
            break
        n += 1
    return n


assert streak([0, 2, 1, 0]) == 2 and streak([1, 1, 1]) == 3 and streak([3, 0, 0]) == 0 and streak([]) == 0


def hero():
    photo = base64.b64encode((ROOT / 'scripts' / 'photo.jpg').read_bytes()).decode()
    cx, cy, r = 686, 177, 108
    b = [
        # Dot grid behind the portrait, as on the site's diagrams
        f'<rect x="1" y="45" width="{W - 2}" height="265" fill="url(#dots)" mask="url(#fade)"/>',
        f'<circle cx="{cx}" cy="{cy}" r="190" fill="url(#glow)"/>',
        text(28, 28, f'github.com/{LOGIN}', 12, MUTED),
        f'<circle cx="{W - 36 - measure(STATUS, 12)}" cy="24" r="3.5" fill="{STR}" class="p"/>',
        text(W - 28, 28, STATUS, 12, SOFT, anchor='end'),
        f'<path d="M1 44.5H{W - 1}" stroke="{SEAM}"/>',
        text(38, 142, NAME, 70, INK, SANS, 700, track=-.03),
        text(40, 184, ROLE, 23, KW, SANS, 600, track=-.01),
        *[text(40, 222 + i * 24, line, 15.5, SOFT, SANS, 400) for i, line in enumerate(TAGLINE)],
        text(40, 286, PLACE, 12, MUTED),
        f'<image href="data:image/jpeg;base64,{photo}" x="{cx - r}" y="{cy - r}" width="{r * 2}" height="{r * 2}" clip-path="url(#face)"/>',
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{SEAM_STRONG}"/>',
        f'<circle class="o" cx="{cx}" cy="{cy}" r="{r + 9}" fill="none" stroke="{KW}" stroke-opacity=".7" stroke-linecap="round" stroke-dasharray="70 120 22 168" style="transform-origin:{cx}px {cy}px"/>',
        f'<path d="M1 310.5H{W - 1}" stroke="{SEAM}"/>',
        f'<path d="M1 311H{W - 1}V383.5a15.5 15.5 0 0 1-15.5 15.5H16.5A15.5 15.5 0 0 1 1 383.5Z" fill="{INSET}"/>',
        text(28, 336, 'How ardend.dev ships', 11, MUTED),
    ]
    step = (W - 56) / len(PIPELINE)
    for i, (name, detail) in enumerate(PIPELINE):
        x = 28 + i * step
        b += [
            f'<circle cx="{x + 7}" cy="361" r="6.5" fill="none" stroke="{SEAM_STRONG}"/>',
            f'<g class="s" style="animation-delay:{.5 + i * .38:.2f}s"><circle cx="{x + 7}" cy="361" r="6.5" fill="{STR}" fill-opacity=".16" stroke="{STR}"/>'
            f'<path d="M{x + 4} 361.2l2.2 2.2 3.9-4.4" fill="none" stroke="{STR}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></g>',
            text(x + 21, 365, name, 12, INK, wght=500),
            text(x + 21, 381, detail, 10, MUTED),
        ]
    defs = (
        f'<pattern id="dots" width="16" height="16" patternUnits="userSpaceOnUse"><circle cx="8" cy="8" r=".9" fill="{SEAM_STRONG}"/></pattern>'
        f'<radialGradient id="g" cx="{cx}" cy="{cy}" r="330" gradientUnits="userSpaceOnUse"><stop offset=".2" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>'
        f'<mask id="fade"><rect width="{W}" height="400" fill="url(#g)"/></mask>'
        f'<radialGradient id="glow"><stop stop-color="{KW}" stop-opacity=".16"/><stop offset="1" stop-color="{KW}" stop-opacity="0"/></radialGradient>'
        f'<clipPath id="face"><circle cx="{cx}" cy="{cy}" r="{r}"/></clipPath>'
        # The pipeline runs once; with reduced motion it is simply shown finished
        '<style>.s{opacity:0;animation:on .5s cubic-bezier(.16,1,.3,1) forwards}@keyframes on{to{opacity:1}}'
        '.p{animation:pulse 2.4s ease-in-out infinite}@keyframes pulse{50%{opacity:.35}}'
        '.o{animation:orbit 40s linear infinite}@keyframes orbit{to{transform:rotate(360deg)}}'
        '@media (prefers-reduced-motion:reduce){.s,.p,.o{animation:none;opacity:1}}</style>'
    )
    return card(400, f'{NAME}, {ROLE}. {STATUS}.', ''.join(b), defs)


def stats(user, total):
    repos = user['repositories']
    tiles = [
        ('Contributions', total, 'last 12 months'),
        ('Repositories', repos['totalCount'], 'public, own work'),
        ('Stars', sum(r['stargazerCount'] for r in repos['nodes']), 'on those repositories'),
        ('Followers', user['followers']['totalCount'], 'on GitHub'),
    ]
    step = (W - 2) / len(tiles)
    b = []
    for i, (label, value, note) in enumerate(tiles):
        x = 1 + i * step
        if i:
            b.append(f'<path d="M{x:.1f} 24V116" stroke="{SEAM}"/>')
        b += [
            text(x + 27, 42, label, 12, MUTED),
            text(x + 26, 88, f'{value:,}', 40, KW if i == 0 else INK, wght=600, track=-.02),
            text(x + 27, 112, note, 11, MUTED),
        ]
    return card(140, ', '.join(f'{v:,} {l.lower()}' for l, v, _ in tiles), ''.join(b))


def heatmap(weeks, total):
    counts = [d['contributionCount'] for w in weeks for d in w['contributionDays']]
    top = max(counts) or 1
    x0, y0 = 58, 84
    pitch = (W - 28 - x0) / len(weeks)
    cell = pitch - 3.2
    b = [
        text(28, 43, 'Contribution activity', 19, INK, SANS, 600, track=-.015),
        text(W - 28, 42, f'{total:,} in the last 12 months', 12, MUTED, anchor='end'),
    ]
    b += [text(28, y0 + row * pitch + cell - 1.5, day, 10, MUTED) for row, day in ((1, 'Mon'), (3, 'Wed'), (5, 'Fri'))]
    last_label = -9
    for col, week in enumerate(weeks):
        first = date.fromisoformat(week['contributionDays'][0]['date'])
        if first.day <= 7 and col - last_label > 3 and col < len(weeks) - 1:
            b.append(text(x0 + col * pitch, y0 - 10, first.strftime('%b'), 10, MUTED))
            last_label = col
        for day in week['contributionDays']:
            n = day['contributionCount']
            level = 0 if n == 0 else min(4, 1 + int(n / top * 3.999))
            row = date.fromisoformat(day['date']).isoweekday() % 7
            b.append(f'<rect x="{x0 + col * pitch:.1f}" y="{y0 + row * pitch:.1f}" width="{cell:.1f}" height="{cell:.1f}" rx="2.5" fill="{HEAT[level]}"/>')
    foot = y0 + 7 * pitch + 22
    active = sum(1 for c in counts if c)
    b.append(text(28, foot, f'{streak(counts)} day streak, {active} active days', 12, SOFT))
    x = W - 28 - measure('More', 11)
    b.append(text(x, foot, 'More', 11, MUTED))
    for colour in reversed(HEAT):
        x -= 15
        b.append(f'<rect x="{x - 4:.1f}" y="{foot - 10}" width="11" height="11" rx="2.5" fill="{colour}"/>')
    b.append(text(x - 12, foot, 'Less', 11, MUTED, anchor='end'))
    return card(round(foot + 24), f'{total:,} contributions in the last 12 months, {active} active days', ''.join(b))


def path_kinds(paths):
    """Infrastructure kinds among a repository's file paths, ignoring vendored code."""
    paths = [p for p in paths if not VENDORED.search(p)]
    return {kind for kind, rx in INFRA_PATHS.items() if any(rx.search(p) for p in paths)}


assert path_kinds(['node_modules/x/.travis.yml', 'pnpm-lock.yaml', 'src/app.py']) == set()
assert path_kinds(['.github/workflows/ci.yml', 'infra/main.tf', 'roles/web/tasks/main.yml']) == {'YAML', 'Terraform', 'Ansible'}


def infra(repo):
    kinds = {INFRA_LANGS[e['node']['name']] for e in repo['languages']['edges'] if e['node']['name'] in INFRA_LANGS}
    try:
        tree = api(f'repos/{LOGIN}/{repo["name"]}/git/trees/HEAD?recursive=1')['tree']
    except urllib.error.HTTPError:  # an empty repository has no tree
        tree = []
    return kinds | path_kinds(f['path'] for f in tree if f['type'] == 'blob')


def languages(repos):
    count, colour, kinds = {}, {'Infrastructure': STR}, set()
    for repo in repos['nodes']:
        found = infra(repo)
        kinds |= found
        names = {'Infrastructure'} if found else set()
        for e in repo['languages']['edges']:
            names.add(e['node']['name'])
            colour.setdefault(e['node']['name'], e['node']['color'] or MUTED)
        for name in names - SKIP - INFRA_LANGS.keys():
            count[name] = count.get(name, 0) + 1
    rows = sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))[:6]
    shown = sum(v for _, v in rows) or 1
    b = [
        text(28, 43, 'Languages', 19, INK, SANS, 600, track=-.015),
        text(W - 28, 42, f'by repositories using each, out of {repos["totalCount"]}', 12, MUTED, anchor='end'),
    ]
    # One stacked bar; each segment is a share of the rows shown, so it needs no empty track
    x, bar_w = 28, W - 56
    segments = []
    for name, v in rows:
        w = v / shown * bar_w
        segments.append(f'<rect x="{x:.1f}" y="66" width="{max(w - 2, 1):.1f}" height="12" fill="{colour[name]}"/>')
        x += w
    b.append(f'<g clip-path="url(#bar)">{"".join(segments)}</g>')
    col = bar_w / 3
    for i, (name, v) in enumerate(rows):
        x, y = 28 + (i % 3) * col, 112 + (i // 3) * 30
        b += [
            f'<circle cx="{x + 5}" cy="{y - 5}" r="5" fill="{colour[name]}"/>',
            text(x + 20, y, name, 14.5, INK, SANS, 500),
            text(x + col - 28, y, f'{v} repos', 12, MUTED, anchor='end'),
        ]
    made_of = 'Infrastructure: ' + ', '.join(k for k in ('YAML', 'Terraform', 'Ansible', 'Docker', 'Shell') if k in kinds)
    b.append(text(28, 172, made_of, 11, MUTED))
    defs = f'<clipPath id="bar"><rect x="28" y="66" width="{bar_w}" height="12" rx="6"/></clipPath>'
    label = 'Languages by repositories: ' + ', '.join(f'{n} {v}' for n, v in rows) + '. ' + made_of
    return card(196, label, ''.join(b), defs)


if __name__ == '__main__':
    user = fetch()
    calendar = user['contributionsCollection']['contributionCalendar']
    OUT.mkdir(exist_ok=True)
    for name, svg in {
        'hero': hero(),
        'stats': stats(user, calendar['totalContributions']),
        'heatmap': heatmap(calendar['weeks'], calendar['totalContributions']),
        'languages': languages(user['code']),
    }.items():
        (OUT / f'{name}.svg').write_text(svg)
        print(f'assets/{name}.svg  {len(svg) / 1024:.0f} KB')
