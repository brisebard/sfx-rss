#!/usr/bin/env python3
"""
Génère un flux RSS à partir du flux d'actualités Satellifacts.

Pour chaque nouvel article détecté sur /api/news-feed, va chercher les
métadonnées complètes (titre, description, date, image) sur la page de
l'article, puis reconstruit un fichier feed.xml complet.

Un cache (data/articles.json) évite de re-télécharger les pages déjà vues
à chaque exécution.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.satellifacts.com"
FEED_SOURCE_URL = f"{BASE_URL}/api/news-feed"
CACHE_PATH = Path("data/articles.json")
OUTPUT_PATH = Path("docs/feed.xml")
MAX_ITEMS = 100
REQUEST_TIMEOUT = 15
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SatellifactsRSSBot/1.0; usage personnel)"
}

# Décalages connus pour les abréviations de fuseau horaire françaises
TZ_OFFSETS = {
    "CET": "+0100",
    "CEST": "+0200",
}

# Exemple de format rencontré : "2026-07-05CEST19:24:46"
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})([A-Z]{2,5})(\d{2}:\d{2}:\d{2})")


def load_cache():
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fetch_feed_links():
    """Récupère la liste des articles (url + titre tronqué) depuis /api/news-feed."""
    resp = requests.get(FEED_SOURCE_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    items = []
    for link in soup.select("a[href^='/news/']"):
        href = link.get("href")
        title_tag = link.select_one("h5.feedArticle")
        if not href or not title_tag:
            continue
        items.append(
            {
                "url": BASE_URL + href,
                "fallback_title": title_tag.get_text(strip=True),
            }
        )
    return items


def parse_published_time(raw):
    """Convertit '2026-07-05CEST19:24:46' en objet datetime timezone-aware."""
    if not raw:
        return None
    match = DATE_RE.match(raw.strip())
    if not match:
        return None
    date_part, tz_abbr, time_part = match.groups()
    offset = TZ_OFFSETS.get(tz_abbr, "+0200")  # heure française par défaut
    try:
        return datetime.strptime(
            f"{date_part} {time_part} {offset}", "%Y-%m-%d %H:%M:%S %z"
        )
    except ValueError:
        return None


def fetch_article_metadata(url):
    """Va chercher og:title, description, article:published_time et og:image."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  ! Échec du téléchargement de {url}: {exc}", file=sys.stderr)
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")

    def meta(*names):
        for name in names:
            tag = soup.find("meta", property=name) or soup.find(
                "meta", attrs={"name": name}
            )
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None

    published_raw = meta("article:published_time")
    published_dt = parse_published_time(published_raw)

    return {
        "title": meta("og:title"),
        "description": meta("og:description", "description"),
        "image": meta("og:image"),
        "published_raw": published_raw,
        "published_iso": published_dt.isoformat() if published_dt else None,
    }


def build_rss(articles, self_url):
    """Construit le XML du flux RSS à partir de la liste d'articles."""
    now = format_datetime(datetime.now(timezone.utc))

    items_xml = []
    for art in articles:
        pub_dt = None
        if art.get("published_iso"):
            try:
                pub_dt = datetime.fromisoformat(art["published_iso"])
            except ValueError:
                pub_dt = None
        pub_date = format_datetime(pub_dt) if pub_dt else now

        title = escape(art.get("title") or art.get("fallback_title") or "Sans titre")
        description = escape(art.get("description") or "")
        link = escape(art["url"])
        image = art.get("image")

        enclosure = (
            f'<enclosure url="{escape(image)}" type="image/jpeg" />' if image else ""
        )

        items_xml.append(
            f"""
    <item>
      <title>{title}</title>
      <link>{link}</link>
      <guid isPermaLink="true">{link}</guid>
      <description>{description}</description>
      <pubDate>{pub_date}</pubDate>
      {enclosure}
    </item>"""
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Satellifacts - Actualités</title>
    <link>{BASE_URL}</link>
    <atom:link href="{escape(self_url)}" rel="self" type="application/rss+xml" />
    <description>Flux RSS non officiel généré à partir de {FEED_SOURCE_URL}</description>
    <language>fr-fr</language>
    <lastBuildDate>{now}</lastBuildDate>
{''.join(items_xml)}
  </channel>
</rss>
"""


def main():
    self_url = os.environ.get("FEED_SELF_URL", f"{BASE_URL}/feed.xml")

    cache = load_cache()

    print("Récupération de la liste des articles...")
    feed_items = fetch_feed_links()
    print(f"  {len(feed_items)} articles trouvés dans le flux.")

    new_count = 0
    for item in feed_items:
        url = item["url"]
        if url in cache:
            continue
        print(f"  Nouvel article : {url}")
        metadata = fetch_article_metadata(url)
        cache[url] = {
            **item,
            **metadata,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        new_count += 1
        time.sleep(1)  # limite le taux de requêtes vers le site

    print(f"  {new_count} nouveaux articles enrichis.")

    def sort_key(art):
        return art.get("published_iso") or ""

    all_articles = sorted(cache.values(), key=sort_key, reverse=True)[:MAX_ITEMS]

    # On ne garde en cache que ce qu'on republie, pour éviter une croissance infinie
    cache = {a["url"]: a for a in all_articles}
    save_cache(cache)

    rss_xml = build_rss(all_articles, self_url)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(rss_xml, encoding="utf-8")
    print(f"Flux RSS écrit dans {OUTPUT_PATH} ({len(all_articles)} articles).")


if __name__ == "__main__":
    main()
