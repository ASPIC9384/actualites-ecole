
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
        self.articles = []
        self.current = None
        self.capture = False
        self.heading = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
            return

        if self.skip:
            return

        if tag == "a" and attrs.get("href"):
            self.links.add(urljoin(BASE, attrs["href"]))

        if tag == "h2":
            self.finish_article()
            self.current = {
                "titre": "",
                "texte": [],
                "image": None
            }
            self.capture = True
            self.heading = []

        if tag == "img" and self.current:
            src = attrs.get("data-src") or attrs.get("src")
            if src and not self.current["image"]:
                self.current["image"] = urljoin(BASE, src)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip = max(0, self.skip - 1)
            return

        if tag == "h2" and self.capture:
            if self.current:
                self.current["titre"] = " ".join(self.heading)
            self.capture = False

    def handle_data(self, data):
        if self.skip or not self.current:
            return

        data = " ".join(data.split())
        if not data:
            return

        if self.capture:
            self.heading.append(data)
        else:
            self.current["texte"].append(data)

    def finish_article(self):
        if self.current and self.current["titre"]:
            self.articles.append(self.current)
        self.current = None

    def close(self):
        super().close()
        self.finish_article()


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
    from urllib.parse import quote

safe_url = quote(url, safe=":/?=&%")

request = Request(
    safe_url,
    headers={"User-Agent": "Mozilla/5.0"}
)
    )
    with urlopen(request, timeout=25) as response:
        html = response.read().decode(
            "utf-8", errors="replace"
        )

    parser = PageParser()
    parser.feed(html)
    parser.close()
    return parser


def internal(url):
    parsed = urlparse(url)
    return (
        parsed.netloc == DOMAIN
        and parsed.path.endswith("/")
        and not parsed.query
        and not parsed.fragment
    )


def article_id(url, title):
    normalized = re.sub(
        r"\s+", " ", title.strip().lower()
    )
    return hashlib.sha256(
        (url + "|" + normalized).encode("utf-8")
    ).hexdigest()


known = load("articles-connus.json", None)
first_run = known is None

if first_run:
    known = {}

history = load("historique-articles.json", [])
queue = [BASE]
visited = set()
new_articles = []
now = datetime.now(timezone.utc).isoformat()

while queue and len(visited) < MAX_PAGES:
    url = queue.pop(0).split("#")[0].split("?")[0]

    if url in visited or not internal(url):
        continue

    visited.add(url)

    try:
        page = fetch(url)
    except Exception as error:
        print(f"Erreur sur {url}: {error}")
        continue

    for article in page.articles:
        title = article["titre"].strip()
        content = " ".join(article["texte"]).strip()

        if not title or len(content) < 40:
            continue

        identifier = article_id(url, title)

        if identifier not in known:
            known[identifier] = {
                "titre": title,
                "lien": url
            }

            if not first_run:
                new_articles.append({
                    "id": identifier,
                    "titre": title,
                    "resume": (
                        content[:180]
                        + ("..." if len(content) > 180 else "")
                    ),
                    "image": article["image"],
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

# Les nouvelles publications détectées lors
# d'une même exécution sont conservées ensemble.
history = new_articles + history

unique = []
seen = set()

for article in history:
    if article["id"] not in seen:
        unique.append(article)
        seen.add(article["id"])

save("articles-connus.json", known)
save("historique-articles.json", unique[:50])
save("actualites.json", unique[:3])

print(f"Pages visitées : {len(visited)}")
print(f"Articles connus : {len(known)}")
print(f"Nouveaux articles : {len(new_articles)}")
print(f"Actualités affichables : {len(unique[:3])}")

if first_run:
    print("Référence initiale créée.")
