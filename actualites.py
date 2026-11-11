
import json
import hashlib
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

BASE = "https://ecoleleslauriersroses-millau.jimdofree.com/"
DOMAIN = urlparse(BASE).netloc
MAX_PAGES = 150


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = set()
        self.images = []
        self.content = []
        self.title = ""
        self.heading = ""
        self.skip = 0
        self.in_title = False
        self.in_heading = False
        self.in_main = False
        self.main_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
            return

        if self.skip:
            return

        if tag == "title":
            self.in_title = True

        if tag == "main" or (
            tag in ("div", "section")
            and (
                "jtpl-content" in attrs.get("class", "")
                or "j-module" in attrs.get("class", "")
            )
        ):
            self.in_main = True

        if tag in ("h1", "h2") and self.in_main:
            self.in_heading = True

        if tag == "a" and attrs.get("href"):
            self.links.add(urljoin(BASE, attrs["href"]))

        if tag == "img":
            src = (
                attrs.get("data-src")
                or attrs.get("src")
                or ""
            )
            if src:
                self.images.append(urljoin(BASE, src))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip = max(0, self.skip - 1)
            return

        if tag == "title":
            self.in_title = False

        if tag in ("h1", "h2"):
            self.in_heading = False

    def handle_data(self, data):
        if self.skip:
            return

        data = " ".join(data.split())
        if not data:
            return

        if self.in_title:
            self.title += data
        elif self.in_main:
            self.content.append(data)
            if self.in_heading and not self.heading:
                self.heading = data


def read_json(filename, default):
    try:
        with open(filename, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def fetch(url):
    request = Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    with urlopen(request, timeout=25) as response:
        html = response.read().decode(
            "utf-8", errors="replace"
        )

    parser = PageParser()
    parser.feed(html)
    return parser


def internal(url):
    parsed = urlparse(url)
    return (
        parsed.netloc == DOMAIN
        and parsed.path.endswith("/")
        and not parsed.query
    )


previous = read_json("etat-pages.json", {})
history = read_json("historique.json", [])

current = {}
queue = [BASE]
visited = set()
now = datetime.now(timezone.utc).isoformat()

while queue and len(visited) < MAX_PAGES:
    url = queue.pop(0).split("#")[0].split("?")[0]

    if url in visited or not internal(url):
        continue

    visited.add(url)

    try:
        page = fetch(url)
    except Exception as error:
        print(f"Erreur : {url} : {error}")
        continue

    content = " ".join(page.content)
    if not content:
        print(f"Contenu introuvable : {url}")
        continue

    fingerprint = hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()

    current[url] = fingerprint

    changed = (
        url in previous
        and previous[url] != fingerprint
    )
    new_page = url not in previous

    if changed or new_page:
        title = (
            page.heading
            or page.title.split("|")[0].strip()
            or "Actualité de l'école"
        )

        image = next(
            (
                img for img in page.images
                if not any(
                    word in img.lower()
                    for word in (
                        "logo", "icon", "favicon",
                        "avatar", "button"
                    )
                )
            ),
            None
        )

        history.insert(0, {
            "titre": title,
            "resume": (
                content[:180]
                + ("..." if len(content) > 180 else "")
            ),
            "image": image,
            "lien": url,
            "date": now
        })

    for link in sorted(page.links):
        link = link.split("#")[0].split("?")[0]
        if (
            internal(link)
            and link not in visited
            and link not in queue
        ):
            queue.append(link)

# Conserver uniquement la dernière modification
# détectée pour chaque page.
unique = []
seen = set()

for item in history:
    if item["lien"] not in seen:
        unique.append(item)
        seen.add(item["lien"])

# Ne pas perdre les empreintes des pages
# temporairement inaccessibles.
current = {**previous, **current}

with open("etat-pages.json", "w", encoding="utf-8") as f:
    json.dump(current, f, ensure_ascii=False, indent=2)

with open("historique.json", "w", encoding="utf-8") as f:
    json.dump(unique[:30], f, ensure_ascii=False, indent=2)

with open("actualites.json", "w", encoding="utf-8") as f:
    json.dump(unique[:3], f, ensure_ascii=False, indent=2)

print(f"Pages examinées : {len(visited)}")
print(f"Actualités disponibles : {len(unique[:3])}")
