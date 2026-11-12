import hashlib
import json
import re
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlparse, urldefrag
from urllib.request import Request, urlopen

BASE = 'https://ecoleleslauriersroses-millau.jimdofree.com/'
DOMAIN = urlparse(BASE).netloc
KNOWN_FILE = 'articles-jimdo-v3.json'
HISTORY_FILE = 'historique-articles-v3.json'
OUTPUT_FILE = 'actualites-test.json'
MAX_PAGES = 150


def clean(text):
    return re.sub(r'\s+', ' ', text).strip()


class JimdoParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = set()
        self.modules = []
        self.stack = []
        self.script_depth = 0
        self.style_depth = 0
        self.heading_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get('class', '').split()
        if tag == 'a' and attrs.get('href'):
            self.links.add(urljoin(BASE, attrs['href']))
        if tag == 'script':
            self.script_depth += 1
        if tag == 'style':
            self.style_depth += 1
        module = None
        if tag == 'div' and 'j-module' in classes:
            kind = next((c for c in classes if c.startswith('j-') and c != 'j-module'), '')
            module = {'kind': kind, 'title': [], 'text': [], 'images': []}
            self.modules.append(module)
        self.stack.append((tag, module))
        active = self.active_module()
        if tag in ('h1', 'h2', 'h3', 'h4') and active:
            self.heading_depth += 1
        if tag == 'img' and active:
            src = attrs.get('data-src') or attrs.get('src')
            if src and not src.startswith('data:'):
                image = urljoin(BASE, src)
                if image not in active['images']:
                    active['images'].append(image)

    def active_module(self):
        return next((m for _, m in reversed(self.stack) if m is not None), None)

    def handle_endtag(self, tag):
        if tag == 'script':
            self.script_depth = max(0, self.script_depth - 1)
        if tag == 'style':
            self.style_depth = max(0, self.style_depth - 1)
        if tag in ('h1', 'h2', 'h3', 'h4'):
            self.heading_depth = max(0, self.heading_depth - 1)
        # HTML from Jimdo normally has well-formed module divs.
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.script_depth or self.style_depth:
            return
        active = self.active_module()
        if not active:
            return
        value = clean(data)
        if not value or '<![CDATA[' in value or 'window.regModule' in value:
            return
        if self.heading_depth:
            active['title'].append(value)
        else:
            active['text'].append(value)


def fetch(url):
    safe_url = quote(url, safe=':/?=&%')
    req = Request(safe_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urlopen(req, timeout=25) as response:
        html = response.read().decode('utf-8', errors='replace')
    parser = JimdoParser()
    parser.feed(html)
    parser.close()
    return parser


def internal(url):
    parsed = urlparse(url)
    return parsed.netloc == DOMAIN and parsed.path.endswith('/') and not parsed.query


def extract_articles(modules, url):
    # Heuristic: a heading followed by content modules is a candidate article.
    # Some candidates may be section headings; review before publishing.
    candidates = []
    current = None
    for module in modules:
        kind = module['kind']
        title = clean(' '.join(module['title']))
        content = clean(' '.join(module['text']))
        if kind == 'j-header' and title:
            if current:
                candidates.append(current)
            current = {'titre': title, 'parts': [], 'images': [], 'lien': url}
        elif current and kind in ('j-text', 'j-imageSubtitle', 'j-gallery'):
            if content:
                current['parts'].append(content)
            for img in module['images']:
                if img not in current['images']:
                    current['images'].append(img)
    if current:
        candidates.append(current)
    results = []
    for item in candidates:
        summary = clean(' '.join(item['parts']))
        if len(summary) < 40:
            continue
        title = item['titre']
        identifier = hashlib.sha256((url + '|' + title.casefold()).encode('utf-8')).hexdigest()
        images = [im for im in item['images'] if not any(w in im.lower() for w in ('logo', 'favicon', 'icon'))]
        results.append({'id': identifier, 'titre': title, 'resume': summary[:180] + ('...' if len(summary) > 180 else ''), 'image': images[0] if images else None, 'lien': url})
    return results


def load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, value):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def main():
    known = load(KNOWN_FILE, None)
    initial = known is None
    if initial:
        known = {}
    history = load(HISTORY_FILE, [])
    queue = deque([BASE])
    visited = set()
    discovered = []
    active_ids = set()
    detected = 0
    failures = 0
    now = datetime.now(timezone.utc).isoformat()
    while queue and len(visited) < MAX_PAGES:
        url = urldefrag(queue.popleft())[0].split('?')[0]
        if url in visited or not internal(url):
            continue
        visited.add(url)
        try:
            page = fetch(url)
        except Exception as exc:
            failures += 1
            print(f'Erreur sur {url}: {exc}')
            continue
        articles = extract_articles(page.modules, url)
        detected += len(articles)
        for article in articles:
            active_ids.add(article['id'])
            if article['id'] not in known:
                known[article['id']] = {'titre': article['titre'], 'lien': url, 'premiere_detection': now}
                if not initial:
                    article['date'] = now
                    discovered.append(article)
        for link in sorted(page.links):
            link = urldefrag(link)[0].split('?')[0]
            if internal(link) and link not in visited and link not in queue:
                queue.append(link)
    # Preserve already published test history, without claiming initial content is new.
    merged = discovered + [
    article for article in history
    if article['id'] in active_ids
    or article['lien'] not in visited
]
    unique, seen = [], set()
    for article in merged:
        if article['id'] not in seen:
            unique.append(article)
            seen.add(article['id'])
    save(KNOWN_FILE, known)
    save(HISTORY_FILE, unique[:50])
    save(OUTPUT_FILE, unique[:3])
    print(f'Pages visitées : {len(visited)}')
    print(f'Pages en erreur : {failures}')
    print(f'Articles candidats détectés : {detected}')
    print(f'Articles mémorisés : {len(known)}')
    print(f'Nouveaux articles : {len(discovered)}')
    if initial:
        print('Référence initiale v3 créée : anciens contenus non publiés comme nouveautés.')
    print('Attention : titres de rubriques et ordre chronologique à valider avant mise en ligne.')


if __name__ == '__main__':
    main()
