
import json
import hashlib
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, quote
from urllib.request import Request, urlopen

BASE = "https://ecoleleslauriersroses-millau.jimdofree.com/"
DOMAIN = urlparse(BASE).netloc


class JimdoParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = set()
        self.modules = []
        self.stack = []
        self.active = None
        self.heading_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()

        if tag == "a" and attrs.get("href"):
            self.links.add(urljoin(BASE, attrs["href"]))

        module = None
        if tag == "div" and "j-module" in classes:
            
kind = next(
    (
        c for c in classes
        if c.startswith("j-") and c != "j-module"
    ),
    ""
)

            module = {
                "kind": kind,
                "title": "",
                "text": [],
                "images": []
            }
            self.modules.append(module)

        self.stack.append((tag, module))

        if module is not None:
            self.active = module

        if tag in ("h1", "h2", "h3") and self.active:
            self.heading_depth += 1

        if tag == "img" and self.active:
            src = (
                attrs.get("data-src")
                or attrs.get("src")
            )
            if src:
                image = urljoin(BASE, src)
                if image not in self.active["images"]:
                    self.active["images"].append(image)

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3"):
            self.heading_depth = max(
                0, self.heading_depth - 1
            )

        while self.stack:
            opened, module = self.stack.pop()
            if opened == tag:
                break

        self.active = next(
            (
                module
                for _, module in reversed(self.stack)
                if module is not None
            ),
            None
        )

    def handle_data(self, data):
        if not self.active:
            return

        value = " ".join(data.split())
        if not value:
            return

        if self.heading_depth:
            self.active["title"] += value + " "
        else:
            self.active["text"].append(value)


def load(filename, default):
    try:
        with open(filename, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch(url):
    safe_url = quote(url, safe=":/?=&%")
    request = Request(
        safe_url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urlopen(request, timeout=25) as response:
        html = response.read().decode(
            "utf-8", errors="replace"
        )

    parser = JimdoParser()
    parser.feed(html)
    parser.close()
    return parser


def internal(url):
    parsed = urlparse(url)
    return (
        parsed.netloc == DOMAIN
        and parsed.path.endswith("/")
        and not parsed.query
    )


def clean(value):
    return re.sub(r"\s+", " ", value).strip()


def extract_articles(modules, url):
    articles = []
    current = None

    for module in modules:
        kind = module["kind"]
        title = clean(module["title"])
        content = clean(" ".join(module["text"]))

        if kind == "j-header" and title:
            if current:
                articles.append(current)

            current = {
                "titre": title,
                "texte": [],
                "images": [],
                "lien": url
            }

        elif current:
            if kind in (
                "j-text",
                "j-imageSubtitle",
                "j-gallery"
            ):
                if content:
                    current["texte"].append(content)

                for img in module["images"]:
                    if img not in current["images"]:
                        current["images"].append(img)

    if current:
        articles.append(current)

    results = []

    for article in articles:
        content = clean(" ".join(article["texte"]))

        if len(content) < 40:
            continue

        title = article["titre"]
        identifier = hashlib.sha256(
            (url + "|" + title.lower()).encode("utf-8")
        ).hexdigest()

        images = [
            img for img in article["images"]
            if not any(
                word in img.lower()
                for word in ("logo", "favicon", "icon")
            )
        ]

        results.append({
            "id": identifier,
            "titre": title,
            "resume": content[:180] + (
                "..." if len(content) > 180 else ""
            ),
            "image": images[0] if images else None,
            "lien": url
        })

    return results


# Nouveau fichier de référence pour cette version.
known = load("articles-jimdo-v2.json", None)
initial = known is None

if initial:
    known = {}

history = load("historique-articles-v2.json", [])
queue = [BASE]
visited = set()
new_articles = []
detected = 0

now = datetime.now(timezone.utc).isoformat()

while queue and len(visited) < 150:
    url = queue.pop(0).split("#")[0].split("?")[0]

    if url in visited or not internal(url):
        continue

    visited.add(url)

    try:
        page = fetch(url)
    except Exception as error:
        print(f"Erreur : {url} : {error}")
        continue

    articles = extract_articles(page.modules, url)
    detected += len(articles)

    for article in articles:
        identifier = article["id"]

        if identifier not in known:
            known[identifier] = {
                "titre": article["titre"],
                "lien": url
            }

            if not initial:
                article["date"] = now
                new_articles.append(article)

    for link in sorted(page.links):
        link = link.split("#")[0].split("?")[0]

        if (
            internal(link)
            and link not in visited
            and link not in queue
        ):
            queue.append(link)

# Conserver les nouveautés sans doublons.
history = new_articles + history
unique = []
seen = set()

for article in history:
    if article["id"] not in seen:
        unique.append(article)
        seen.add(article["id"])

save("articles-jimdo-v2.json", known)
save("historique-articles-v2.json", unique[:50])

# Ne pas remplacer le fichier public tant que
# cette nouvelle détection n'est pas validée.
save("actualites-test.json", unique[:3])

print(f"Pages visitées : {len(visited)}")
print(f"Articles candidats détectés : {detected}")
print(f"Articles mémorisés : {len(known)}")
print(f"Nouveaux articles : {len(new_articles)}")

if initial:
    print("Nouvelle référence initiale créée.")
