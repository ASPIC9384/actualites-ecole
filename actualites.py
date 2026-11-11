
import json
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from html.parser import HTMLParser

BASE = "https://ecoleleslauriersroses-millau.jimdofree.com/"
DOMAIN = urlparse(BASE).netloc


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = set()
        self.text = []
        self.title = ""
        self.in_title = False
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if tag == "a" and attrs.get("href"):
            self.links.add(urljoin(BASE, attrs["href"]))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.skip:
            return
        data = " ".join(data.split())
        if data:
            if self.in_title:
                self.title += data
            else:
                self.text.append(data)


def read_json(filename, default):
    try:
        with open(filename, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def fetch(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=20) as response:
        html = response.read().decode("utf-8", errors="replace")
    parser = PageParser()
    parser.feed(html)
    return parser


def internal(url):
    parsed = urlparse(url)
    return (
        parsed.netloc == DOMAIN
        and parsed.path.endswith("/")
        and not parsed.query
        and not parsed.fragment
    )


previous = read_json("etat-pages.json", {})
history = read_json("historique.json", [])
current = {}
queue = [BASE]
visited = set()

while queue and len(visited) < 150:
    url = queue.pop(0).split("#")[0].split("?")[0]
    if url in visited or not internal(url):
        continue

    visited.add(url)

    try:
        page = fetch(url)
    except Exception as error:
        print(f"Erreur sur {url}: {error}")
        continue

    content = " ".join(page.text)
    fingerprint = hashlib.sha256(content.encode()).hexdigest()

    current[url] = fingerprint

    if url in previous and previous[url] != fingerprint:
        history.insert(0, {
            "titre": page.title or "Actualité de l'école",
            "resume": content[:180] + ("..." if len(content) > 180 else ""),
            "lien": url,
            "date": datetime.now(timezone.utc).isoformat()
        })

    for link in sorted(page.links):
        if internal(link) and link not in visited and link not in queue:
            queue.append(link)

# Éviter plusieurs entrées pour une même page.
unique = []
seen = set()
for item in history:
    if item["lien"] not in seen:
        unique.append(item)
        seen.add(item["lien"])

with open("etat-pages.json", "w", encoding="utf-8") as f:
    json.dump(current, f, ensure_ascii=False, indent=2)

with open("historique.json", "w", encoding="utf-8") as f:
    json.dump(unique[:30], f, ensure_ascii=False, indent=2)

with open("actualites.json", "w", encoding="utf-8") as f:
    json.dump(unique[:3], f, ensure_ascii=False, indent=2)

print(f"{len(visited)} pages examinées.")
print(f"{len(unique[:3])} actualités disponibles.")
