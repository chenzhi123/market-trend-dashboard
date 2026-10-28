"""Substack 帖子同步：拉取帖子列表、把原文缓存为 Markdown、找出尚未录入 watchlist 的帖子。

单独运行：python -m pipeline.substack
"""
import json
import re
import time
from html import unescape
from html.parser import HTMLParser

import requests
import yaml

from .fetch import ROOT

PUB = "https://yiwei465.substack.com"
POSTS_DIR = ROOT / "data" / "substack"
INDEX = POSTS_DIR / "index.json"
WATCHLIST = ROOT / "config" / "watchlist.yaml"
HEADERS = {"User-Agent": "Mozilla/5.0 (market-trend-dashboard)"}


class _ToMarkdown(HTMLParser):
    BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "figure", "table"}

    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "svg", "button"):
            self.skip += 1
        elif tag in self.BLOCK or tag == "br":
            self.out.append("\n")
            if tag.startswith("h") and len(tag) == 2:
                self.out.append("#" * int(tag[1]) + " ")
            elif tag == "li":
                self.out.append("- ")
        elif tag in ("td", "th"):
            self.out.append(" | ")
        elif tag == "img" and a.get("src"):
            self.out.append(f"\n[图片 {a.get('alt') or ''}]({a['src']})\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg", "button"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_md(html: str) -> str:
    p = _ToMarkdown()
    p.feed(html or "")
    text = unescape("".join(p.out)).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def _get(url: str) -> requests.Response:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r
        except Exception:  # noqa: BLE001
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def list_posts() -> list[dict]:
    posts, offset = [], 0
    while True:
        page = _get(f"{PUB}/api/v1/archive?sort=new&limit=50&offset={offset}").json()
        posts += page
        if len(page) < 50:
            return posts
        offset += 50


def recorded_slugs() -> set[str]:
    if not WATCHLIST.exists():
        return set()
    cfg = yaml.safe_load(WATCHLIST.read_text(encoding="utf-8")) or {}
    slugs = set(cfg.get("ignored_posts") or [])
    for s in cfg.get("stocks") or []:
        slugs |= {p["slug"] for p in s.get("posts") or []}
        slugs |= {h["slug"] for h in s.get("history") or [] if h.get("slug")}
    return slugs


def sync() -> dict:
    """返回 {"posts": [...], "pending": [...], "ok": bool, "error": str|None}。网络失败时回退到本地索引。"""
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        raw = list_posts()
        posts = [{"slug": p["slug"], "title": p["title"], "subtitle": p.get("subtitle") or "",
                  "date": p["post_date"][:10], "url": p.get("canonical_url") or f"{PUB}/p/{p['slug']}",
                  "audience": p.get("audience")} for p in raw]
        for p in posts:
            path = POSTS_DIR / f"{p['slug']}.md"
            if path.exists():
                continue
            body = _get(f"{PUB}/api/v1/posts/{p['slug']}").json().get("body_html") or ""
            head = f"# {p['title']}\n\n> {p['subtitle']}\n\n日期：{p['date']}  链接：{p['url']}\n\n"
            path.write_text(head + html_to_md(body), encoding="utf-8")
            print(f"  缓存帖子 {p['date']} {p['title']}")
        INDEX.write_text(json.dumps(posts, ensure_ascii=False, indent=1), encoding="utf-8")
        ok, err = True, None
    except Exception as e:  # noqa: BLE001
        posts = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else []
        ok, err = False, f"{type(e).__name__}: {str(e)[:120]}"
    done = recorded_slugs()
    pending = [p for p in posts if p["slug"] not in done]
    return {"posts": posts, "pending": pending, "ok": ok, "error": err}


if __name__ == "__main__":
    res = sync()
    print(f"共 {len(res['posts'])} 篇，待录入 {len(res['pending'])} 篇" + ("" if res["ok"] else f"（离线：{res['error']}）"))
    for p in res["pending"]:
        print(f"  {p['date']}  {p['slug']}  {p['title']}")
