"""
Aqara AU 社媒监控脚本 v2
==========================
改动：
  - Reddit 不再需要 API Key，使用公开 JSON 接口
  - 新增 Google News AU（RSS，免费，覆盖澳洲媒体报道）
  - 新增 Homeone.com.au（澳洲最大建房论坛，Smart Home版块）
  - 新增 Google Alerts RSS（全网关键词监控）

抓取来源：
  Reddit    — r/Aqara, r/homeassistant, r/smarthome, r/homeautomation, r/AusPropertyChat
  Whirlpool — Smart Home 版块 + aqara 关键词搜索
  Homeone   — Home Automation 版块
  Google    — News AU + Alerts RSS

输出：
  docs/index.html          GitHub Pages 报告页面（自动更新）
  docs/data/YYYY-WW.json   每周数据存档，累积历史关键词趋势
"""

import os
import json
import datetime
import pathlib
import time
import re
import xml.etree.ElementTree as ET
from collections import Counter

import requests

# ── 配置 ─────────────────────────────────────────────────────────────────────

SUBREDDITS = [
    "Aqara",
    "homeassistant",
    "smarthome",
    "homeautomation",
    "AusPropertyChat",
]

KEYWORDS = [
    "aqara", "zigbee", "matter", "thread", "homekit", "home assistant",
    "hub m2", "hub m3", "hub e1", "fp2", "fp1e",
    "d100", "a100", "n100", "u100", "p100",
    "australia", "australian", "au version",
    "setup", "install", "not working", "firmware", "update", "review",
    "smart lock", "smart home", "automation",
    "xiaomi", "opple",
]

# 用户代理（模拟浏览器，避免被拒绝）
HEADERS_REDDIT = {
    "User-Agent": "AqaraAU-Monitor/2.0 (personal research tool; +https://github.com)",
}
HEADERS_WEB = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-AU,en;q=0.9",
}

# Google News AU — 搜索词列表（每个词生成一个 RSS URL）
GOOGLE_NEWS_QUERIES = [
    "aqara australia",
    "aqara smart home",
    "aqara review australia",
]

# Homeone.com.au Smart Home 版块
HOMEONE_URL = "https://forum.homeone.com.au/viewforum.php?f=8"


# ── Reddit（无需 API Key）────────────────────────────────────────────────────

def fetch_reddit_new(subreddit: str, limit: int = 5) -> list[dict]:
    """抓取 subreddit 最新帖，非 r/Aqara 的过滤含 aqara 的帖子"""
    url = f"https://www.reddit.com/r/{subreddit}/new.json"
    time.sleep(2)  # 公开接口限速：2秒/请求
    try:
        r = requests.get(url, headers=HEADERS_REDDIT,
                         params={"limit": limit * 4}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  ⚠️  Reddit new r/{subreddit}: {e}")
        return []

    posts = []
    for child in data.get("data", {}).get("children", []):
        p = child["data"]
        text = (p.get("title", "") + " " + p.get("selftext", "")).lower()
        if subreddit.lower() != "aqara" and "aqara" not in text:
            continue
        posts.append(_fmt_reddit(p, subreddit))
        if len(posts) >= limit:
            break
    return posts


def fetch_reddit_top(subreddit: str, time_filter: str = "week",
                     limit: int = 5) -> list[dict]:
    """抓取 subreddit 本周热门帖"""
    url = f"https://www.reddit.com/r/{subreddit}/top.json"
    time.sleep(2)
    try:
        r = requests.get(url, headers=HEADERS_REDDIT,
                         params={"t": time_filter, "limit": limit * 4},
                         timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  ⚠️  Reddit top r/{subreddit}: {e}")
        return []

    posts = []
    for child in data.get("data", {}).get("children", []):
        p = child["data"]
        text = (p.get("title", "") + " " + p.get("selftext", "")).lower()
        if subreddit.lower() != "aqara" and "aqara" not in text:
            continue
        posts.append(_fmt_reddit(p, subreddit))
        if len(posts) >= limit:
            break
    return posts


def fetch_reddit_keyword_counts(subreddit: str, months: int = 3) -> Counter:
    """统计最近 N 个月帖子中各关键词出现次数"""
    url = f"https://www.reddit.com/r/{subreddit}/new.json"
    time.sleep(2)
    counts = Counter()
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=30 * months
    )
    try:
        r = requests.get(url, headers=HEADERS_REDDIT,
                         params={"limit": 100}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  ⚠️  Reddit kw r/{subreddit}: {e}")
        return counts

    for child in data.get("data", {}).get("children", []):
        p = child["data"]
        created = datetime.datetime.fromtimestamp(
            p["created_utc"], datetime.timezone.utc
        )
        if created < cutoff:
            continue
        text = (p.get("title", "") + " " + p.get("selftext", "")).lower()
        for kw in KEYWORDS:
            if kw in text:
                counts[kw] += 1
    return counts


def _fmt_reddit(p: dict, subreddit: str) -> dict:
    created = datetime.datetime.fromtimestamp(
        p["created_utc"], datetime.timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")
    preview = re.sub(r"\s+", " ", p.get("selftext", ""))[:180].strip()
    return {
        "title":     p.get("title", ""),
        "url":       f"https://reddit.com{p.get('permalink', '')}",
        "score":     p.get("score", 0),
        "comments":  p.get("num_comments", 0),
        "author":    p.get("author", "[deleted]"),
        "created":   created,
        "subreddit": subreddit,
        "flair":     p.get("link_flair_text") or "",
        "preview":   preview,
        "source":    "reddit",
    }


# ── Whirlpool ─────────────────────────────────────────────────────────────────

def fetch_whirlpool_search(query: str = "aqara", limit: int = 8) -> list[dict]:
    """搜索 Whirlpool，返回含关键词的帖子"""
    time.sleep(2)
    try:
        r = requests.get(
            "https://forums.whirlpool.net.au/search",
            params={"q": query, "section": "forums"},
            headers=HEADERS_WEB, timeout=20,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"  ⚠️  Whirlpool search: {e}")
        return []

    return _parse_whirlpool_threads(r.text, limit, require_keyword="aqara")


def fetch_whirlpool_forum(limit: int = 8) -> list[dict]:
    """抓取 Whirlpool Smart Home 版块最新帖"""
    time.sleep(2)
    try:
        r = requests.get(
            "https://forums.whirlpool.net.au/forum/136",
            headers=HEADERS_WEB, timeout=20,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"  ⚠️  Whirlpool forum: {e}")
        return []

    return _parse_whirlpool_threads(r.text, limit)


def _parse_whirlpool_threads(html: str, limit: int,
                              require_keyword: str = "") -> list[dict]:
    pattern = re.compile(
        r'href="(/(?:thread|archive)/([a-z0-9]+)[^"]*)"[^>]*>\s*([^<]{10,200})',
        re.IGNORECASE,
    )
    seen, posts = set(), []
    for m in pattern.finditer(html):
        path, tid, title = m.group(1), m.group(2), m.group(3).strip()
        title = re.sub(r"\s+", " ", title)
        if tid in seen or len(title) < 10:
            continue
        if require_keyword and require_keyword not in title.lower():
            continue
        seen.add(tid)
        posts.append({
            "title":    title,
            "url":      f"https://forums.whirlpool.net.au{path.split('?')[0]}",
            "platform": "Whirlpool",
            "source":   "whirlpool",
        })
        if len(posts) >= limit:
            break
    return posts


# ── Homeone.com.au ────────────────────────────────────────────────────────────

def fetch_homeone(limit: int = 8) -> list[dict]:
    """抓取 Homeone.com.au Home Automation 版块最新帖"""
    time.sleep(2)
    try:
        r = requests.get(HOMEONE_URL, headers=HEADERS_WEB, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"  ⚠️  Homeone: {e}")
        return []

    # Homeone 帖子链接格式：/viewtopic.php?f=8&t=XXXXX
    pattern = re.compile(
        r'href="(viewtopic\.php\?[^"]*t=(\d+)[^"]*)"[^>]*>\s*([^<]{10,200})',
        re.IGNORECASE,
    )
    seen, posts = set(), []
    for m in pattern.finditer(r.text):
        path, tid, title = m.group(1), m.group(2), m.group(3).strip()
        title = re.sub(r"\s+", " ", title)
        if tid in seen or len(title) < 10:
            continue
        seen.add(tid)
        posts.append({
            "title":    title,
            "url":      f"https://forum.homeone.com.au/{path}",
            "platform": "Homeone",
            "source":   "homeone",
        })
        if len(posts) >= limit:
            break
    return posts


# ── Google News AU ────────────────────────────────────────────────────────────

def fetch_google_news(query: str, limit: int = 5) -> list[dict]:
    """通过 Google News RSS 抓取澳洲新闻"""
    url = (
        f"https://news.google.com/rss/search"
        f"?q={requests.utils.quote(query)}&hl=en-AU&gl=AU&ceid=AU:en"
    )
    time.sleep(1)
    try:
        r = requests.get(url, headers=HEADERS_WEB, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"  ⚠️  Google News ({query}): {e}")
        return []

    posts = []
    try:
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        for item in items[:limit]:
            title   = (item.findtext("title") or "").strip()
            link    = (item.findtext("link") or "").strip()
            pubdate = (item.findtext("pubDate") or "").strip()
            source  = (item.findtext("source") or "").strip()
            if not title or not link:
                continue
            posts.append({
                "title":    title,
                "url":      link,
                "platform": f"Google News · {source}" if source else "Google News AU",
                "created":  pubdate[:16],
                "source":   "google_news",
            })
    except Exception as e:
        print(f"  ⚠️  Google News XML parse ({query}): {e}")

    return posts


def fetch_all_google_news(limit_per_query: int = 4) -> list[dict]:
    """抓取所有配置的 Google News 查询词"""
    all_posts = []
    seen_urls = set()
    for q in GOOGLE_NEWS_QUERIES:
        for p in fetch_google_news(q, limit=limit_per_query):
            if p["url"] not in seen_urls:
                seen_urls.add(p["url"])
                all_posts.append(p)
    return all_posts


# ── Google Alerts RSS（可选）────────────────────────────────────────────────

def fetch_google_alerts_rss(rss_url: str, limit: int = 5) -> list[dict]:
    """
    抓取 Google Alerts RSS feed。
    使用方法：
      1. 去 google.com/alerts
      2. 搜索词填 "aqara australia"
      3. 选项里把交付方式改为 RSS feed
      4. 复制生成的 RSS URL
      5. 把 URL 设置为 GitHub Secret: GOOGLE_ALERTS_RSS
    """
    time.sleep(1)
    try:
        r = requests.get(rss_url, headers=HEADERS_WEB, timeout=15)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        posts = []
        for item in items[:limit]:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            date  = (item.findtext("pubDate") or "").strip()
            if title and link:
                posts.append({
                    "title":    re.sub(r"<[^>]+>", "", title),
                    "url":      link,
                    "platform": "Google Alerts",
                    "created":  date[:16],
                    "source":   "google_alerts",
                })
        return posts
    except Exception as e:
        print(f"  ⚠️  Google Alerts RSS: {e}")
        return []


# ── HTML 报告生成 ─────────────────────────────────────────────────────────────

def _post_card_reddit(p: dict) -> str:
    score_col = "#00c8a0" if p.get("score", 0) > 15 else "#8b8fa8"
    flair = (f'<span style="display:inline-block;font-size:10px;padding:2px 8px;'
             f'border-radius:4px;background:rgba(0,200,160,.12);color:#00c8a0;'
             f'margin-bottom:4px">{p["flair"]}</span>') if p.get("flair") else ""
    preview = (f'<div style="font-size:11px;color:#8b8fa8;margin:6px 0 0;'
               f'line-height:1.5;font-style:italic">{p["preview"][:160]}…</div>'
               ) if p.get("preview") else ""
    return f"""
    <div class="card">
      <a href="{p['url']}" target="_blank" class="card-title">{p['title']}</a>
      {flair}{preview}
      <div class="card-meta">
        <span style="color:{score_col}">▲ {p['score']}</span>
        <span>💬 {p['comments']}</span>
        <span>r/{p['subreddit']}</span>
        <span>{p['created'][:10]}</span>
        <span>u/{p['author']}</span>
      </div>
    </div>"""


def _post_card_generic(p: dict) -> str:
    return f"""
    <div class="card">
      <a href="{p['url']}" target="_blank" class="card-title">{p['title']}</a>
      <div class="card-meta">
        <span>{p.get('platform','')}</span>
        {f"<span>{p['created'][:10]}</span>" if p.get('created') else ''}
      </div>
    </div>"""


def _section_html(posts: list, kind: str = "reddit") -> str:
    if not posts:
        return '<div class="empty">本期暂无内容</div>'
    fn = _post_card_reddit if kind == "reddit" else _post_card_generic
    return "".join(fn(p) for p in posts)


def build_html_report(
    run_date, run_week,
    reddit_new, reddit_top,
    wp_aqara, wp_forum,
    homeone_posts,
    google_news_posts,
    google_alerts_posts,
    keyword_stats, history,
):
    # 关键词统计
    total_kw: Counter = Counter()
    for v in keyword_stats.values():
        total_kw.update(v)
    top_kw = [(kw, cnt) for kw, cnt in total_kw.most_common(15) if cnt > 0]
    max_cnt = top_kw[0][1] if top_kw else 1
    kw_rows = "".join(
        f'<div class="kw-row">'
        f'<span class="kw-name">{kw}</span>'
        f'<div class="kw-bar-wrap"><div class="kw-bar" style="width:{int(cnt/max_cnt*100)}%"></div></div>'
        f'<span class="kw-count">{cnt}</span></div>'
        for kw, cnt in top_kw
    ) or '<div class="empty">暂无数据</div>'

    # Reddit 各 subreddit 分组
    def reddit_group(posts, sub):
        sub_posts = [p for p in posts if p.get("subreddit") == sub]
        if not sub_posts:
            return ""
        return (f'<div class="sub-group">'
                f'<div class="sub-label">r/{sub}</div>'
                f'{_section_html(sub_posts, "reddit")}</div>')

    reddit_new_html = "".join(reddit_group(reddit_new, s) for s in SUBREDDITS)
    reddit_top_html = "".join(reddit_group(reddit_top, s) for s in SUBREDDITS)

    # 统计数字
    total_new = len(reddit_new) + len(wp_aqara) + len(homeone_posts) + len(google_news_posts)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aqara AU 社媒情报 · {run_date[:10]}</title>
<style>
:root{{--bg:#0d0f14;--bg2:#13161e;--bg3:#1a1e28;
  --border:rgba(255,255,255,0.08);
  --text:#e8eaf0;--text2:#8b8fa8;--text3:#555a70;
  --green:#00c8a0;--orange:#f5a623;--red:#ff6b6b;--blue:#0090ff;
  --font:-apple-system,"PingFang SC","Noto Sans SC",sans-serif;}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:var(--bg);color:var(--text);font-family:var(--font);font-size:14px;line-height:1.6;}}
a{{color:var(--text);text-decoration:none;}}
a:hover{{color:var(--green);}}
.topbar{{background:var(--bg2);border-bottom:1px solid var(--border);
  padding:14px 28px;display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:0;z-index:100;}}
.brand{{font-size:13px;font-weight:600;color:var(--green);letter-spacing:.05em;}}
.meta{{font-size:11px;color:var(--text3);font-family:monospace;}}
.dot{{width:7px;height:7px;background:var(--green);border-radius:50%;
  display:inline-block;margin-right:6px;animation:pulse 2s infinite;}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.3}}}}
.layout{{display:grid;grid-template-columns:210px 1fr;min-height:calc(100vh - 49px);}}
.sidebar{{background:var(--bg2);border-right:1px solid var(--border);
  padding:20px 0;position:sticky;top:49px;height:calc(100vh - 49px);overflow-y:auto;}}
.sidebar a{{display:block;padding:7px 20px;font-size:12px;color:var(--text3);
  border-left:2px solid transparent;transition:all .15s;}}
.sidebar a:hover,.sidebar a.active{{color:var(--text);border-left-color:var(--green);
  background:rgba(0,200,160,.05);}}
.shead{{font-size:10px;letter-spacing:.1em;color:var(--text3);text-transform:uppercase;
  padding:14px 20px 4px;}}
.main{{padding:32px;overflow-y:auto;}}
.psec{{margin-bottom:44px;scroll-margin-top:60px;}}
.ptitle{{font-size:20px;font-weight:600;margin-bottom:3px;}}
.pdesc{{font-size:12px;color:var(--text2);margin-bottom:18px;}}
.stat-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:24px;}}
.stat{{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:14px;}}
.stat-val{{font-size:22px;font-weight:600;color:var(--green);}}
.stat-lbl{{font-size:11px;color:var(--text3);margin-top:2px;}}
.card{{background:var(--bg2);border:1px solid var(--border);border-radius:8px;
  padding:13px 15px;margin-bottom:9px;transition:border-color .15s;}}
.card:hover{{border-color:rgba(255,255,255,.15);}}
.card-title{{font-size:13px;font-weight:500;line-height:1.4;display:block;margin-bottom:5px;}}
.card-meta{{display:flex;gap:10px;flex-wrap:wrap;font-size:11px;color:var(--text3);
  margin-top:7px;font-family:monospace;}}
.sub-group{{margin-bottom:18px;}}
.sub-label{{font-size:11px;font-family:monospace;color:var(--green);
  letter-spacing:.06em;margin-bottom:7px;padding:3px 0;border-bottom:1px solid var(--border);}}
.kw-section{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:18px;}}
.kw-row{{display:flex;align-items:center;gap:12px;padding:5px 0;
  border-bottom:1px solid rgba(255,255,255,.04);}}
.kw-row:last-child{{border:none;}}
.kw-name{{font-family:monospace;font-size:12px;width:160px;color:var(--text);flex-shrink:0;}}
.kw-bar-wrap{{flex:1;height:6px;background:rgba(255,255,255,.06);border-radius:3px;overflow:hidden;}}
.kw-bar{{height:100%;background:var(--green);border-radius:3px;}}
.kw-count{{font-family:monospace;font-size:12px;color:var(--green);width:32px;text-align:right;}}
.badge{{font-size:10px;padding:2px 8px;border-radius:4px;font-family:monospace;font-weight:600;}}
.badge-new{{background:rgba(0,200,160,.15);color:var(--green);}}
.badge-hot{{background:rgba(255,107,107,.15);color:var(--red);}}
.badge-au{{background:rgba(0,144,255,.15);color:var(--blue);}}
.empty{{color:var(--text3);font-size:12px;padding:10px 0;}}
.note{{font-size:12px;color:var(--text2);line-height:1.7;background:var(--bg2);
  border:1px solid var(--border);border-radius:8px;padding:14px 16px;margin-top:12px;}}
.note code{{background:var(--bg3);padding:1px 6px;border-radius:3px;
  font-size:11px;color:var(--green);font-family:monospace;}}
@media(max-width:700px){{
  .layout{{grid-template-columns:1fr;}}
  .sidebar{{display:none;}}
  .stat-grid{{grid-template-columns:1fr 1fr;}}
}}
</style>
</head>
<body>
<div class="topbar">
  <div class="brand"><span class="dot"></span>AQARA AU · 社媒情报监控</div>
  <div class="meta">第 {run_week.split('-W')[1]} 周 &nbsp;·&nbsp; {run_date[:10]} 更新
    &nbsp;·&nbsp; Reddit · Whirlpool · Homeone · Google News</div>
</div>
<div class="layout">
  <nav class="sidebar">
    <div class="shead">本周概览</div>
    <a href="#overview">📊 数据摘要</a>
    <a href="#keywords">🔍 关键词热度</a>
    <div class="shead">Reddit</div>
    <a href="#reddit-new">🆕 最新帖子</a>
    <a href="#reddit-top">🔥 本周热门</a>
    <div class="shead">澳洲论坛</div>
    <a href="#wp-aqara">🌀 Whirlpool · Aqara</a>
    <a href="#wp-forum">🏠 Whirlpool · Smart Home</a>
    <a href="#homeone">🏗 Homeone</a>
    <div class="shead">媒体 / 全网</div>
    <a href="#google-news">📰 Google News AU</a>
    {'<a href="#google-alerts">🔔 Google Alerts</a>' if google_alerts_posts else ''}
    <div class="shead">关于</div>
    <a href="#about">ℹ️ 说明</a>
  </nav>
  <main class="main">

    <div class="psec" id="overview">
      <div class="ptitle">本周数据摘要</div>
      <div class="pdesc">第 {run_week.split('-W')[1] if '-W' in run_week else run_week} 周 · {run_date[:10]}</div>
      <div class="stat-grid">
        <div class="stat"><div class="stat-val">{len(reddit_new)}</div><div class="stat-lbl">Reddit 最新（含aqara）</div></div>
        <div class="stat"><div class="stat-val">{len(reddit_top)}</div><div class="stat-lbl">Reddit 本周热门</div></div>
        <div class="stat"><div class="stat-val">{len(wp_aqara) + len(wp_forum)}</div><div class="stat-lbl">Whirlpool 帖子</div></div>
        <div class="stat"><div class="stat-val">{len(homeone_posts) + len(google_news_posts)}</div><div class="stat-lbl">Homeone + 媒体报道</div></div>
      </div>
    </div>

    <div class="psec" id="keywords">
      <div class="ptitle">关键词热度 Top 15</div>
      <div class="pdesc">近3个月 Reddit 帖子中关键词出现次数（自动累积）</div>
      <div class="kw-section">{kw_rows}</div>
    </div>

    <div class="psec" id="reddit-new">
      <div class="ptitle">Reddit · 最新帖 <span class="badge badge-new">NEW</span></div>
      <div class="pdesc">各 subreddit 最新含 aqara 关键词的讨论</div>
      {reddit_new_html or '<div class="empty">本周暂无</div>'}
    </div>

    <div class="psec" id="reddit-top">
      <div class="ptitle">Reddit · 本周热门 <span class="badge badge-hot">HOT</span></div>
      <div class="pdesc">本周点赞和评论最多的 Aqara 相关讨论</div>
      {reddit_top_html or '<div class="empty">本周暂无</div>'}
    </div>

    <div class="psec" id="wp-aqara">
      <div class="ptitle">Whirlpool · Aqara 搜索 <span class="badge badge-au">AU</span></div>
      <div class="pdesc">forums.whirlpool.net.au 搜索 "aqara" 的最新结果</div>
      {_section_html(wp_aqara, "generic")}
    </div>

    <div class="psec" id="wp-forum">
      <div class="ptitle">Whirlpool · Smart Home 版块 <span class="badge badge-au">AU</span></div>
      <div class="pdesc">Smart Home 版块最新帖子（不限 Aqara）</div>
      {_section_html(wp_forum, "generic")}
    </div>

    <div class="psec" id="homeone">
      <div class="ptitle">Homeone · Home Automation <span class="badge badge-au">AU</span></div>
      <div class="pdesc">澳洲最大建房论坛的 Home Automation 版块</div>
      {_section_html(homeone_posts, "generic")}
    </div>

    <div class="psec" id="google-news">
      <div class="ptitle">Google News AU · 媒体报道</div>
      <div class="pdesc">澳洲媒体对 Aqara 的最新报道（Google News RSS）</div>
      {_section_html(google_news_posts, "generic")}
    </div>

    {'<div class="psec" id="google-alerts"><div class="ptitle">Google Alerts</div><div class="pdesc">全网关键词监控</div>' + _section_html(google_alerts_posts, "generic") + '</div>' if google_alerts_posts else ''}

    <div class="psec" id="about">
      <div class="ptitle">关于</div>
      <div class="note">
        本页面由 GitHub Actions 每周一早9点（悉尼时间）自动更新，无需 Reddit API Key。<br>
        数据来源：Reddit 公开接口 · Whirlpool · Homeone · Google News AU<br>
        历史数据存于 <code>docs/data/</code>，关键词趋势自动累积。<br>
        手动刷新：GitHub → Actions → Run workflow。
        <br><br>
        <strong>可选增强：</strong>设置 Google Alerts RSS 后，在仓库 Settings → Secrets 添加
        <code>GOOGLE_ALERTS_RSS</code>（填入你的 Alerts RSS URL），下次运行自动抓取。
      </div>
    </div>

  </main>
</div>
<script>
const secs = document.querySelectorAll('.psec[id]');
const links = document.querySelectorAll('.sidebar a');
new IntersectionObserver(entries => {{
  entries.forEach(e => {{
    if(e.isIntersecting) links.forEach(a =>
      a.classList.toggle('active', a.getAttribute('href')==='#'+e.target.id));
  }});
}}, {{rootMargin:'-30% 0px -65% 0px'}}).observe || secs.forEach(s => s);
const io = new IntersectionObserver(entries => {{
  entries.forEach(e => {{
    if(e.isIntersecting) links.forEach(a =>
      a.classList.toggle('active', a.getAttribute('href')==='#'+e.target.id));
  }});
}}, {{rootMargin:'-30% 0px -65% 0px'}});
secs.forEach(s => io.observe(s));
</script>
</body>
</html>"""


# ── 历史数据 ──────────────────────────────────────────────────────────────────

def load_history(data_dir) -> dict:
    history = {}
    for f in sorted(pathlib.Path(data_dir).glob("*.json")):
        try:
            d = json.loads(f.read_text())
            merged = Counter()
            for v in d.get("keyword_stats", {}).values():
                merged.update(v)
            history[f.stem] = dict(merged)
        except Exception:
            pass
    return history


def save_week_data(data_dir, week_key, reddit_new, reddit_top,
                   wp_aqara, keyword_stats):
    p = pathlib.Path(data_dir)
    p.mkdir(parents=True, exist_ok=True)
    payload = {
        "week":          week_key,
        "reddit_new":    reddit_new,
        "reddit_top":    reddit_top,
        "wp_aqara":      wp_aqara,
        "keyword_stats": {k: dict(v) for k, v in keyword_stats.items()},
    }
    out = p / f"{week_key}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"  💾 {out}")


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    now      = datetime.datetime.now(datetime.timezone.utc)
    run_date = now.strftime("%Y-%m-%d %H:%M UTC")
    run_week = now.strftime("%Y-W%W")
    print(f"\n🚀 Aqara AU Monitor v2 — {run_date}  ({run_week})\n")

    docs_dir = pathlib.Path("docs")
    data_dir = docs_dir / "data"
    docs_dir.mkdir(exist_ok=True)

    # ── Reddit ────────────────────────────────
    print("📥 Reddit（无需 API Key）...")
    reddit_new, reddit_top, keyword_stats = [], [], {}
    for sub in SUBREDDITS:
        print(f"   r/{sub} ...")
        try:
            n = fetch_reddit_new(sub, limit=5)
            t = fetch_reddit_top(sub, limit=5)
            k = fetch_reddit_keyword_counts(sub, months=3)
            reddit_new.extend(n)
            reddit_top.extend(t)
            keyword_stats[sub] = k
            print(f"   ✅ {len(n)} new · {len(t)} top · {sum(k.values())} kw")
        except Exception as e:
            print(f"   ❌ {sub}: {e}")
            keyword_stats[sub] = Counter()

    # ── Whirlpool ─────────────────────────────
    print("\n📥 Whirlpool...")
    wp_aqara = fetch_whirlpool_search("aqara", limit=8)
    print(f"   ✅ Aqara search: {len(wp_aqara)}")
    wp_forum = fetch_whirlpool_forum(limit=8)
    print(f"   ✅ Smart Home forum: {len(wp_forum)}")

    # ── Homeone ───────────────────────────────
    print("\n📥 Homeone.com.au...")
    homeone_posts = fetch_homeone(limit=8)
    print(f"   ✅ {len(homeone_posts)} posts")

    # ── Google News AU ────────────────────────
    print("\n📥 Google News AU...")
    google_news_posts = fetch_all_google_news(limit_per_query=4)
    print(f"   ✅ {len(google_news_posts)} articles")

    # ── Google Alerts RSS（可选）──────────────
    alerts_rss = os.environ.get("GOOGLE_ALERTS_RSS", "")
    google_alerts_posts = []
    if alerts_rss:
        print("\n📥 Google Alerts RSS...")
        google_alerts_posts = fetch_google_alerts_rss(alerts_rss, limit=8)
        print(f"   ✅ {len(google_alerts_posts)} items")
    else:
        print("\n⏭  Google Alerts RSS 未配置（可选）")

    # ── 保存 & 历史 ───────────────────────────
    print("\n💾 Saving data...")
    save_week_data(data_dir, run_week, reddit_new, reddit_top,
                   wp_aqara, keyword_stats)
    history = load_history(data_dir)
    print(f"   📊 {len(history)} weeks of history loaded")

    # ── 生成报告 ──────────────────────────────
    print("\n📄 Building HTML report...")
    html = build_html_report(
        run_date, run_week,
        reddit_new, reddit_top,
        wp_aqara, wp_forum,
        homeone_posts, google_news_posts, google_alerts_posts,
        keyword_stats, history,
    )
    out = docs_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"   ✅ {out} ({len(html)//1024}KB)")

    print(f"\n✅ Done — Reddit {len(reddit_new)} · WP {len(wp_aqara)+len(wp_forum)}"
          f" · Homeone {len(homeone_posts)} · News {len(google_news_posts)}\n")


if __name__ == "__main__":
    main()
