"""ANRE Telegram publisher — runs inside GitHub Actions.

Modes:
  check            — only checks access to Telegram + Telegraph, posts nothing.
  essay <folder>   — tg/essays/<folder>/: article.md -> Telegraph page,
                     slides 01.jpg..10.jpg + caption.txt -> album in channel.
  telegraph <folder> — only creates the Telegraph page (no channel post), prints URL.

Secrets (env): TG_TOKEN (required for channel), TELEGRAPH_TOKEN (optional;
if empty a Telegraph account "ANRE" is created and its token printed masked).
"""
import json, os, re, sys, glob, urllib.request, urllib.parse

CH = os.environ.get('TG_CHANNEL', '@anrechannel')
REPO_RAW = 'https://raw.githubusercontent.com/anredesign818/anremedia/main/'
IG = os.environ.get('IG_URL', 'https://www.instagram.com/anre_design/')


def call(url, data=None, timeout=120):
    body = None
    headers = {}
    if data is not None:
        body = json.dumps(data).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b'{}')


def tg(method, data=None):
    tok = os.environ.get('TG_TOKEN', '').strip()
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{30,}', tok):
        sys.exit('TG_TOKEN secret looks wrong (must be like 123456:ABC..., full token, no spaces/dots). '
                 f'Length now: {len(tok)}')
    os.environ['TG_TOKEN'] = tok
    return call(f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/{method}", data)


def tph(method, data=None):
    return call(f'https://api.telegra.ph/{method}', data)


def telegraph_token():
    t = os.environ.get('TELEGRAPH_TOKEN', '').strip()
    if t:
        return t
    r = tph('createAccount', {'short_name': 'ANRE', 'author_name': 'ANRE Architects', 'author_url': IG})
    if not r.get('ok'):
        sys.exit(f'Telegraph createAccount failed: {r}')
    t = r['result']['access_token']
    print(f'::add-mask::{t}')
    print('NOTE: new Telegraph account created. Save its token as secret TELEGRAPH_TOKEN '
          '(see the "telegraph_token" artifact of this run).')
    with open('telegraph_token.txt', 'w') as f:
        f.write(t)
    return t


# --- tiny markdown -> Telegraph nodes -------------------------------------
def inline(text):
    nodes, pos = [], 0
    for m in re.finditer(r'\*\*(.+?)\*\*|\*(.+?)\*|\[(.+?)\]\((.+?)\)', text):
        if m.start() > pos:
            nodes.append(text[pos:m.start()])
        if m.group(1):
            nodes.append({'tag': 'strong', 'children': [m.group(1)]})
        elif m.group(2):
            nodes.append({'tag': 'em', 'children': [m.group(2)]})
        else:
            nodes.append({'tag': 'a', 'attrs': {'href': m.group(4)}, 'children': [m.group(3)]})
        pos = m.end()
    if pos < len(text):
        nodes.append(text[pos:])
    return nodes


def md_to_nodes(md, base_url):
    out = []
    for block in re.split(r'\n\s*\n', md.strip()):
        b = block.strip()
        img = re.fullmatch(r'!\[(.*?)\]\((.+?)\)', b)
        if img:
            src = img.group(2) if img.group(2).startswith('http') else base_url + img.group(2)
            fig = [{'tag': 'img', 'attrs': {'src': src}}]
            if img.group(1):
                fig.append({'tag': 'figcaption', 'children': [img.group(1)]})
            out.append({'tag': 'figure', 'children': fig})
        elif b.startswith('## '):
            out.append({'tag': 'h4', 'children': inline(b[3:])})
        elif b.startswith('# '):
            out.append({'tag': 'h3', 'children': inline(b[2:])})
        elif b.startswith('> '):
            out.append({'tag': 'blockquote', 'children': inline(re.sub(r'^> ?', '', b, flags=re.M))})
        elif b == '---':
            out.append({'tag': 'hr'})
        else:
            kids = []
            for i, line in enumerate(b.split('\n')):
                if i:
                    kids.append({'tag': 'br'})
                kids += inline(line)
            out.append({'tag': 'p', 'children': kids})
    return out


def make_page(folder):
    path = f'tg/essays/{folder}'
    md = open(f'{path}/article.md', encoding='utf-8').read()
    title = md.splitlines()[0].lstrip('# ').strip()
    body = '\n'.join(md.splitlines()[1:])
    nodes = md_to_nodes(body, REPO_RAW + path + '/')
    nodes += [{'tag': 'hr'}, {'tag': 'p', 'children': [
        'Больше — в Инстаграме ', {'tag': 'a', 'attrs': {'href': IG}, 'children': ['@anre_design']},
        ' и в Телеграме ', {'tag': 'a', 'attrs': {'href': 'https://t.me/anrechannel'}, 'children': ['@anrechannel']}]}]
    r = tph('createPage', {'access_token': telegraph_token(), 'title': title,
                           'author_name': 'ANRE Architects', 'author_url': IG,
                           'content': nodes, 'return_content': False})
    if not r.get('ok'):
        sys.exit(f'Telegraph createPage failed: {r}')
    url = r['result']['url']
    print('TELEGRAPH_URL', url)
    return url


def post_essay(folder):
    path = f'tg/essays/{folder}'
    url = make_page(folder)
    caption = open(f'{path}/caption.txt', encoding='utf-8').read().strip()
    caption_html = (caption.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    + f'\n\n<a href="{url}">Читать эссе целиком →</a>')
    slides = sorted(glob.glob(f'{path}/[0-9][0-9].jpg') + glob.glob(f'{path}/[0-9][0-9].png'))[:10]
    if not slides:
        sys.exit('no slides found')
    media = [{'type': 'photo', 'media': REPO_RAW + s} for s in slides]
    media[0].update(caption=caption_html, parse_mode='HTML')
    r = tg('sendMediaGroup', {'chat_id': CH, 'media': media})
    print('album ok:', r.get('ok'), r.get('description', ''))
    if not r.get('ok'):
        sys.exit(1)


def check():
    try:
        me = tg('getMe') if os.environ.get('TG_TOKEN') else {'ok': False, 'description': 'TG_TOKEN secret missing'}
    except SystemExit as e:
        me = {'ok': False, 'description': str(e)}
    print('telegram getMe:', me.get('ok'), me.get('result', {}).get('username', me.get('description')))
    r = tph('getAccountInfo', {'access_token': os.environ.get('TELEGRAPH_TOKEN') or 'x'})
    # any JSON answer (even ACCESS_TOKEN_INVALID) means Telegraph is reachable
    print('telegraph reachable: yes, answer:', r.get('ok'), r.get('error', ''))


def post_reel(n):
    """Upload tg/reels/reel_<n>.mp4 straight from the checkout (multipart, no URL fetch)."""
    import subprocess
    n = str(n).zfill(2)
    video = f'tg/reels/reel_{n}.mp4'
    if not os.path.exists(video):
        sys.exit(f'{video} not found')
    cap = json.load(open('tg/reels/captions.json', encoding='utf-8'))[n]
    tg('getMe')  # validates token format
    out = subprocess.run(
        ['curl', '-sS', '--max-time', '300', '--retry', '3', '--retry-all-errors',
         '--form-string', f'chat_id={CH}', '-F', f'video=@{video};type=video/mp4',
         '--form-string', f'caption={cap}', '-F', 'supports_streaming=true',
         '-F', 'width=720', '-F', 'height=1280',
         f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendVideo"],
        capture_output=True, text=True)
    try:
        r = json.loads(out.stdout)
    except ValueError:
        r = {'ok': False, 'description': (out.stderr or out.stdout)[:300]}
    print('reel', n, 'ok:', r.get('ok'), r.get('description', ''))
    if not r.get('ok'):
        sys.exit(1)


# --- schedule: tg/queue.json (Dubai time) + tg/posted.json (log) --------------
QUEUE, POSTED = 'tg/queue.json', 'tg/posted.json'
GRACE_HOURS = 3  # GitHub cron can be ~1 h late; older misses are reported, not posted (no night posts)


def run_item(item):
    kind, ref = item['type'], item['ref']
    if kind == 'reel':
        post_reel(ref)
    elif kind == 'essay':
        post_essay(ref)
    else:
        sys.exit(f'unknown type {kind}')


def mark_posted(key, posted):
    import subprocess, datetime
    posted[key] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(POSTED, 'w', encoding='utf-8') as f:
        json.dump(posted, f, ensure_ascii=False, indent=1)
    sh = lambda *a: subprocess.run(list(a), check=False)
    sh('git', 'config', 'user.name', 'anre-poster')
    sh('git', 'config', 'user.email', 'actions@users.noreply.github.com')
    sh('git', 'add', POSTED)
    sh('git', 'commit', '-q', '-m', f'posted {key}')
    for _ in range(5):
        if sh('git', 'push', '-q').returncode == 0:
            return
        sh('git', 'pull', '-q', '--rebase')
    print(f'::warning::could not push {POSTED} — check for a duplicate next run')


def due():
    import datetime
    dubai = datetime.timezone(datetime.timedelta(hours=4))
    now = datetime.datetime.now(dubai)
    queue = json.load(open(QUEUE, encoding='utf-8'))
    posted = json.load(open(POSTED, encoding='utf-8')) if os.path.exists(POSTED) else {}
    failed = False
    for item in sorted(queue, key=lambda i: i['at']):
        key = f"{item['type']}:{item['ref']}"
        if key in posted:
            continue
        at = datetime.datetime.fromisoformat(item['at']).replace(tzinfo=dubai)
        if at > now:
            continue
        if now - at > datetime.timedelta(hours=GRACE_HOURS):
            print(f'::warning::MISSED {key} (planned {item["at"]} Dubai) — not posted automatically')
            continue
        print(f'posting {key} (planned {item["at"]} Dubai)')
        try:
            run_item(item)
        except SystemExit as e:
            if e.code not in (None, 0):
                print(f'::error::{key} failed: {e.code}')
                failed = True
                continue
        mark_posted(key, posted)
    upcoming = [f"{i['at']} {i['type']}:{i['ref']}" for i in sorted(queue, key=lambda i: i['at'])
                if f"{i['type']}:{i['ref']}" not in posted
                and datetime.datetime.fromisoformat(i['at']).replace(tzinfo=dubai) > now]
    print('next:', upcoming[:3] or 'queue empty')
    cleanup(posted)
    if failed:
        sys.exit(1)


CLEANUP_DAYS = 3  # media stays in the repo 3 days after posting (time to re-check / re-post), then goes


def cleanup(posted):
    """Delete media of items posted > CLEANUP_DAYS ago. Telegram keeps its own copies.
    Essay photos p_*.jpg and article.md stay: the Telegraph article shows them from this repo."""
    import subprocess, datetime
    cutoff = datetime.date.today() - datetime.timedelta(days=CLEANUP_DAYS)
    gone = []
    for key, when in posted.items():
        try:
            day = datetime.date.fromisoformat(str(when)[:10])
        except ValueError:
            continue
        if day > cutoff:
            continue
        kind, ref = key.split(':', 1)
        if kind == 'reel':
            files = [f'tg/reels/reel_{ref}.mp4']
        elif kind == 'essay':
            files = glob.glob(f'tg/essays/{ref}/[0-9][0-9].jpg') + glob.glob(f'tg/essays/{ref}/[0-9][0-9].png')
        else:
            files = []
        gone += [f for f in files if os.path.exists(f)]
    if not gone:
        return
    sh = lambda *a: subprocess.run(list(a), check=False)
    sh('git', 'config', 'user.name', 'anre-poster')
    sh('git', 'config', 'user.email', 'actions@users.noreply.github.com')
    sh('git', 'rm', '-q', *gone)
    sh('git', 'commit', '-q', '-m', f'cleanup: media posted {CLEANUP_DAYS}+ days ago ({len(gone)} files)')
    for _ in range(5):
        if sh('git', 'push', '-q').returncode == 0:
            print('cleanup:', gone)
            return
        sh('git', 'pull', '-q', '--rebase')


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'check':
        check()
    elif mode == 'essay':
        posted = json.load(open(POSTED)) if os.path.exists(POSTED) else {}
        if f'essay:{sys.argv[2]}' in posted:
            sys.exit(print(f'essay {sys.argv[2]} already posted {posted[f"essay:{sys.argv[2]}"]} — skipped') or 0)
        post_essay(sys.argv[2])
        mark_posted(f'essay:{sys.argv[2]}', posted)
    elif mode == 'telegraph':
        make_page(sys.argv[2])
    elif mode == 'reel':
        n = str(sys.argv[2]).zfill(2)
        posted = json.load(open(POSTED)) if os.path.exists(POSTED) else {}
        if f'reel:{n}' in posted:
            sys.exit(print(f'reel {n} already posted {posted[f"reel:{n}"]} — skipped') or 0)
        post_reel(n)
        mark_posted(f'reel:{n}', posted)
    elif mode == 'due':
        due()
    else:
        sys.exit('unknown mode')
