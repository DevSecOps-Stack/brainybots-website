#!/usr/bin/env python3
"""
AI Pulse & Macro Cockpit — Daily Data & Gemini Synthesis Fetcher.

Zero external dependencies (Python 3 standard library only).
Fetches:
  1. Live Mutual Fund NAVs from api.mfapi.in (AMFI India) for a 3-fund Indian SIP basket
  2. Live Global AI & Indian IT stock bellwethers from Yahoo Finance public chart API
  3. Live AI/Cloud/Outage stories from Hacker News Algolia API & tech RSS feeds
  4. LMSYS Chatbot Arena Leaderboard snapshot (Overall, Coding, Open-Weights)
  5. Optional Gemini Free API synthesis when GEMINI_API_KEY is set

Outputs:
  - data/daily_pulse.json
  - data/pulse_data.js  (enables offline / file:// viewing without CORS errors)
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import html
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
JSON_OUT = os.path.join(DATA_DIR, "daily_pulse.json")
JS_OUT = os.path.join(DATA_DIR, "pulse_data.js")

IST = timezone(timedelta(hours=5, minutes=30))
USER_AGENT = "AI-Pulse-Cockpit/1.0 (+https://github.com/local/ai-pulse)"
GEMINI_MODELS = ["gemini-3-flash-preview", "gemini-3.8-flash", "gemini-2.5-flash"]

SIP_FUNDS = [
    {
        "scheme_code": "122639",
        "name": "Parag Parikh Flexi Cap",
        "short_name": "PPFAS Flexi Cap",
        "weight_pct": 30,
        "exposure": "Global Big Tech (~15% Alphabet/Microsoft/Meta/Amazon) + Indian Value + ~15-20% Cash buffer",
    },
    {
        "scheme_code": "147625",
        "name": "Motilal Oswal Nifty 500",
        "short_name": "MO Nifty 500",
        "weight_pct": 40,
        "exposure": "Broad 500-stock Indian market core (Banking, IT, Infra, Manufacturing)",
    },
    {
        "scheme_code": "140228",
        "name": "Edelweiss Mid Cap",
        "short_name": "Edelweiss Mid Cap",
        "weight_pct": 30,
        "exposure": "High-growth Indian mid-caps (higher volatility, best accumulated during dips)",
    },
]

STOCK_BELLWETHERS = [
    {"symbol": "NVDA", "label": "Nvidia", "region": "US AI Chips", "fallback_price": 162.85, "fallback_1d": -1.2, "fallback_30d": -26.4},
    {"symbol": "MSFT", "label": "Microsoft", "region": "US Cloud/AI", "fallback_price": 523.88, "fallback_1d": 0.4, "fallback_30d": -1.8},
    {"symbol": "ORCL", "label": "Oracle", "region": "US Infra/OCI", "fallback_price": 125.35, "fallback_1d": -0.8, "fallback_30d": -4.0},
    {"symbol": "GOOGL", "label": "Alphabet", "region": "US AI/PPFAS", "fallback_price": 295.77, "fallback_1d": 0.9, "fallback_30d": -14.9},
    {"symbol": "META", "label": "Meta", "region": "US Open-AI", "fallback_price": 641.69, "fallback_1d": 0.6, "fallback_30d": -13.0},
    {"symbol": "^NDX", "label": "Nasdaq 100", "region": "US Tech Index", "fallback_price": 27943.74, "fallback_1d": -0.3, "fallback_30d": -6.7},
    {"symbol": "^CNXIT", "label": "Nifty IT", "region": "India IT", "fallback_price": 31941.05, "fallback_1d": 0.05, "fallback_30d": 0.05},
    {"symbol": "^NSEI", "label": "Nifty 50", "region": "India Core", "fallback_price": 25291.10, "fallback_1d": 0.1, "fallback_30d": 9.27},
]

RSS_FEEDS = [
    {"name": "The Register", "url": "https://www.theregister.com/headlines.atom"},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/technology-lab"},
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
]

AI_KEYWORDS = (
    "ai", "llm", "nvidia", "jensen", "microsoft", "oracle", "openai", "anthropic",
    "gemini", "claude", "deepseek", "qwen", "china", "chip", "gpu", "outage",
    "outlook", "azure", "aws", "layoff", "workforce", "capex", "data center",
    "datacenter", "vllm", "kubernetes", "openshift", "chatbot arena", "lmarena",
    "bubble", "model", "inference", "agent", "hiring",
)

CATEGORY_RULES = [
    ("Outages & Layoffs", ("outage", "down", "outlook", "365", "azure", "aws", "layoff", "job cut", "firing", "restructur", "60k", "incident", "breach", "hiring")),
    ("Hyperscalers & Deals", ("microsoft", "oracle", "deal", "cancel", "capex", "billion", "data center", "datacenter", "openai", "google", "meta", "amazon", "cloud")),
    ("Chips & China AI", ("nvidia", "jensen", "tsmc", "gpu", "china", "deepseek", "qwen", "alibaba", "baidu", "bubble", "export", "tariff", "scandal", "amd")),
    ("Models & Open-Weights", ("model", "llm", "arena", "gemini", "claude", "gpt", "llama", "mistral", "vllm", "open source", "open-weight", "benchmark", "coding")),
]


def _ssl_context():
    """Return default verified SSL context."""
    return ssl.create_default_context()


def _http_get_text(url, timeout=8, headers=None):
    """Fetch URL body as UTF-8 text."""
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json, application/xml, text/xml, */*"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _http_get_json(url, timeout=8):
    """Fetch and parse JSON from URL."""
    return json.loads(_http_get_text(url, timeout=timeout))


def _http_post_json(url, payload, timeout=30):
    """POST JSON payload and return parsed JSON response."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _clean_text(raw):
    """Strip HTML tags and collapse whitespace."""
    text = html.unescape(raw or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _matches_ai_keywords(text):
    """Match whole tokens or key multi-word phrases so 'ai' doesn't false-match random words."""
    lowered = text.lower()
    for kw in AI_KEYWORDS:
        if len(kw) <= 3:
            if re.search(rf"\b{re.escape(kw)}\b", lowered):
                return True
        elif kw in lowered:
            return True
    return False


def _classify_story(title, summary=""):
    """Map story text to one of the 4 cockpit signal categories."""
    blob = f"{title} {summary}".lower()
    for category, terms in CATEGORY_RULES:
        if any(term in blob for term in terms):
            return category
    return "Models & Open-Weights"


def fetch_mf_navs():
    """Fetch live AMFI Mutual Fund NAVs and 1d/30d changes via api.mfapi.in."""
    results = []
    live_count = 0
    for fund in SIP_FUNDS:
        entry = {
            "scheme_code": fund["scheme_code"],
            "name": fund["name"],
            "short_name": fund["short_name"],
            "weight_pct": fund["weight_pct"],
            "exposure": fund["exposure"],
            "nav": None,
            "nav_date": "Unavailable",
            "change_1d_pct": 0.0,
            "change_30d_pct": 0.0,
            "status": "OFFLINE",
        }
        try:
            payload = _http_get_json(f"https://api.mfapi.in/mf/{fund['scheme_code']}", timeout=8)
            meta = payload.get("meta", {})
            rows = payload.get("data", [])
            if rows:
                latest_nav = float(rows[0]["nav"])
                entry["nav"] = round(latest_nav, 4)
                entry["nav_date"] = rows[0].get("date", "")
                if meta.get("scheme_name"):
                    entry["official_name"] = meta["scheme_name"]
                if len(rows) > 1:
                    prev_nav = float(rows[1]["nav"])
                    entry["change_1d_pct"] = round(((latest_nav - prev_nav) / prev_nav) * 100, 2)
                idx_30d = min(21, len(rows) - 1)
                if idx_30d > 0:
                    old_nav = float(rows[idx_30d]["nav"])
                    entry["change_30d_pct"] = round(((latest_nav - old_nav) / old_nav) * 100, 2)
                entry["spark"] = [round(float(r["nav"]), 4) for r in reversed(rows[: min(22, len(rows))])]
                entry["status"] = "LIVE"
                live_count += 1
        except Exception as exc:
            entry["error"] = str(exc)[:100]
        results.append(entry)
    return results, live_count


def fetch_stock_bellwethers():
    """Fetch 1-month daily chart data from Yahoo Finance public endpoint."""
    results = []
    live_count = 0
    for item in STOCK_BELLWETHERS:
        sym = item["symbol"]
        record = {
            "symbol": sym,
            "label": item["label"],
            "region": item["region"],
            "price": item["fallback_price"],
            "change_1d_pct": item["fallback_1d"],
            "change_30d_pct": item["fallback_30d"],
            "status": "BASELINE",
        }
        try:
            encoded = urllib.parse.quote(sym)
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=1mo&interval=1d"
            payload = _http_get_json(url, timeout=6)
            chart = payload.get("chart", {}).get("result", [])
            if chart:
                closes = [c for c in chart[0]["indicators"]["quote"][0]["close"] if c is not None]
                if closes:
                    latest = float(closes[-1])
                    prev = float(closes[-2]) if len(closes) >= 2 else latest
                    first = float(closes[0])
                    record["price"] = round(latest, 2)
                    record["change_1d_pct"] = round(((latest - prev) / prev) * 100, 2) if prev else 0.0
                    record["change_30d_pct"] = round(((latest - first) / first) * 100, 2) if first else 0.0
                    record["spark"] = [round(float(c), 2) for c in closes]
                    record["status"] = "LIVE"
                    live_count += 1
        except Exception:
            pass
        results.append(record)
    return results, live_count


def fetch_hn_ai_stories():
    """Fetch top recent AI, hyperscaler, chip, and outage stories from HN Algolia API."""
    endpoints = [
        "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30",
        "https://hn.algolia.com/api/v1/search_by_date?query=AI&tags=story&numericFilters=points>25&hitsPerPage=12",
        "https://hn.algolia.com/api/v1/search_by_date?query=Nvidia&tags=story&numericFilters=points>20&hitsPerPage=8",
        "https://hn.algolia.com/api/v1/search_by_date?query=Microsoft&tags=story&numericFilters=points>20&hitsPerPage=8",
    ]
    seen_ids = set()
    stories = []
    any_ok = False

    for url in endpoints:
        try:
            data = _http_get_json(url, timeout=8)
            any_ok = True
            for hit in data.get("hits", []):
                oid = hit.get("objectID")
                title = _clean_text(hit.get("title", ""))
                if not title or oid in seen_ids:
                    continue
                if "front_page" in url and not _matches_ai_keywords(title):
                    continue
                seen_ids.add(oid)
                target_url = hit.get("url") or f"https://news.ycombinator.com/item?id={oid}"
                stories.append({
                    "title": title,
                    "url": target_url,
                    "discussion_url": f"https://news.ycombinator.com/item?id={oid}",
                    "source": "Hacker News",
                    "points": int(hit.get("points") or 0),
                    "comments": int(hit.get("num_comments") or 0),
                    "published_at": hit.get("created_at", ""),
                    "category": _classify_story(title),
                })
        except Exception:
            continue

    stories.sort(key=lambda x: x.get("points", 0), reverse=True)
    return stories[:15], any_ok


def _parse_feed_xml(xml_text, source_name):
    """Parse RSS 2.0 or Atom XML into normalized story dicts."""
    items = []
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    for item in root.findall(".//item")[:20]:
        title = _clean_text(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        desc = _clean_text(item.findtext("description"))
        pub = (item.findtext("pubDate") or "").strip()
        if title and link:
            items.append((title, link, desc, pub))

    if not items:
        entries = root.findall(".//atom:entry", ns) or root.findall(".//entry")
        for entry in entries[:20]:
            title_el = entry.find("atom:title", ns) if entry.find("atom:title", ns) is not None else entry.find("title")
            link_el = entry.find("atom:link", ns) if entry.find("atom:link", ns) is not None else entry.find("link")
            sum_el = entry.find("atom:summary", ns) if entry.find("atom:summary", ns) is not None else entry.find("summary")
            upd_el = entry.find("atom:updated", ns) if entry.find("atom:updated", ns) is not None else entry.find("updated")
            title = _clean_text(title_el.text if title_el is not None else "")
            link = (link_el.attrib.get("href", "") if link_el is not None else "").strip()
            desc = _clean_text(sum_el.text if sum_el is not None else "")
            pub = (upd_el.text if upd_el is not None else "").strip()
            if title and link:
                items.append((title, link, desc, pub))

    filtered = []
    for title, link, desc, pub in items:
        if _matches_ai_keywords(f"{title} {desc}"):
            filtered.append({
                "title": title,
                "url": link,
                "source": source_name,
                "snippet": desc[:220],
                "published_at": pub,
                "category": _classify_story(title, desc),
            })
    return filtered[:6]


def fetch_rss_headlines():
    """Pull AI, cloud, and outage headlines from public tech RSS/Atom feeds."""
    stories = []
    live_feeds = 0
    for feed in RSS_FEEDS:
        try:
            xml_text = _http_get_text(feed["url"], timeout=6)
            parsed = _parse_feed_xml(xml_text, feed["name"])
            stories.extend(parsed)
            live_feeds += 1
        except Exception:
            continue
    return stories, live_feeds


def _format_org(org_raw):
    """Normalize provider names from LMArena dataset."""
    mapping = {
        "google": "Google",
        "anthropic": "Anthropic",
        "openai": "OpenAI",
        "xai": "xAI",
        "deepseek": "DeepSeek",
        "alibaba": "Alibaba",
        "qwen": "Alibaba",
        "meta": "Meta",
        "mistral": "Mistral",
        "xiaomi": "Xiaomi",
        "zai": "Z.ai",
        "moonshot": "Moonshot",
    }
    key = (org_raw or "").strip().lower()
    return mapping.get(key, key.title() if key else "Unknown")


def _to_arena_entry(row, display_rank, note_override=None):
    """Convert one LMArena dataset row into the dashboard card schema."""
    votes = int(row.get("vote_count") or 0)
    overall_rank = int(row.get("rank") or display_rank)
    ci_low = round(float(row.get("rating_lower") or row.get("rating") or 0))
    ci_high = round(float(row.get("rating_upper") or row.get("rating") or 0))
    elo = round(float(row.get("rating") or 0))
    lic = row.get("license") or "Unknown"
    note = note_override or f"Arena #{overall_rank} overall · {votes:,} human votes ({ci_low}–{ci_high} CI)"
    return {
        "rank": display_rank,
        "model": row.get("model_name", "Unknown"),
        "org": _format_org(row.get("organization")),
        "elo": elo,
        "delta": f"#{overall_rank}",
        "license": lic,
        "note": note,
    }


def _fetch_artificial_analysis():
    """Fetch live up-to-date Intelligence Index leaderboard from Artificial Analysis."""
    url = "https://artificialanalysis.ai/embed/llm-leaderboard"
    body = _http_get_text(url, timeout=12)
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S)
    parsed = []
    for tr in trs:
        tds = [
            re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", td))).strip()
            for td in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)
        ]
        if len(tds) < 6 or not tds[1].isdigit():
            continue
        imgs = re.findall(r'<img[^>]*alt="([^"]+)"', tr)
        org = imgs[0].strip() if imgs else "Unknown"
        name = re.sub(r"\s*,\s*Default Fallback$", "", tds[0]).strip()
        score = int(tds[1])
        cost = tds[2]
        ctx = tds[5]
        parsed.append({
            "model": name,
            "org": org,
            "elo": score,
            "cost": cost,
            "ctx": ctx,
            "overall_rank": len(parsed) + 1,
        })

    if not parsed:
        return None

    open_tokens = ("deepseek", "qwen", "glm", "llama", "mimo", "kimi", "mistral", "gemma", "gpt-oss", "olmo")
    is_open = lambda m: any(tok in m["model"].lower() for tok in open_tokens)

    def to_card(m, rank):
        lic = "Open-Weights" if is_open(m) else "Proprietary"
        return {
            "rank": rank,
            "model": m["model"],
            "org": m["org"],
            "elo": m["elo"],
            "delta": f"#{m['overall_rank']} · {m['cost']}",
            "license": lic,
            "note": f"AA Intelligence Index {m['elo']} · {m['cost']}/task · {m['ctx']} ctx",
        }

    overall = [to_card(m, i + 1) for i, m in enumerate(parsed[:5])]

    seen_orgs = set()
    by_lab = []
    for m in parsed:
        if m["org"] in seen_orgs:
            continue
        seen_orgs.add(m["org"])
        by_lab.append(to_card(m, len(by_lab) + 1))
        if len(by_lab) == 5:
            break

    open_weights = [to_card(m, i + 1) for i, m in enumerate([m for m in parsed if is_open(m)][:5])]

    return {
        "source": "Artificial Analysis (artificialanalysis.ai)",
        "updated_label": "Artificial Analysis · Live",
        "status": "LIVE",
        "overall": overall,
        "coding": by_lab,
        "open_weights": open_weights,
    }


def get_arena_leaderboard():
    """
    Fetch live AI Leaderboard:
      1. Artificial Analysis (most up-to-date Intelligence Index, incl. latest releases)
      2. Fallback: LMArena Official Dataset on Hugging Face
      3. Fallback: Embedded snapshot if offline
    """
    try:
        aa = _fetch_artificial_analysis()
        if aa:
            return aa
    except Exception:
        pass

    url = "https://datasets-server.huggingface.co/rows?dataset=lmarena-ai%2Fleaderboard-dataset&config=text&split=latest&offset=0&length=100"
    try:
        data = _http_get_json(url, timeout=10)
        rows = [x.get("row", {}) for x in data.get("rows", []) if x.get("row", {}).get("category") == "overall"]
        rows.sort(key=lambda r: float(r.get("rank") or 9999))
        if rows:
            pub_date = rows[0].get("leaderboard_publish_date") or "Latest"
            overall = [_to_arena_entry(r, i + 1) for i, r in enumerate(rows[:5])]

            # Top distinct-provider leaders (helpful for coding/engineering comparison)
            seen_orgs = set()
            coding = []
            for r in rows:
                org = _format_org(r.get("organization"))
                if org in seen_orgs:
                    continue
                seen_orgs.add(org)
                coding.append(_to_arena_entry(r, len(coding) + 1))
                if len(coding) == 5:
                    break

            open_rows = [r for r in rows if (r.get("license") or "").lower() not in ("proprietary", "other", "")]
            open_weights = [
                _to_arena_entry(
                    r,
                    i + 1,
                    f"Overall #{int(r.get('rank') or 0)} · {int(r.get('vote_count') or 0):,} votes · Self-hostable ({r.get('license')})",
                )
                for i, r in enumerate(open_rows[:5])
            ]

            return {
                "source": "LMArena Official Dataset (lmarena.ai)",
                "updated_label": f"Live · {pub_date}",
                "status": "LIVE",
                "overall": overall,
                "coding": coding,
                "open_weights": open_weights,
            }
    except Exception:
        pass

    return {
        "source": "LMSYS Chatbot Arena (lmarena.ai)",
        "updated_label": "Offline Snapshot",
        "status": "OFFLINE",
        "overall": [
            {"rank": 1, "model": "Gemini 4 Carbon (High)", "org": "Google", "elo": 1538, "delta": "#1", "license": "Proprietary", "note": "Fallback snapshot"},
            {"rank": 2, "model": "Gemini 4 Argon (High)", "org": "Google", "elo": 1529, "delta": "#2", "license": "Proprietary", "note": "Fallback snapshot"},
            {"rank": 3, "model": "Claude Opus 5.5 (High)", "org": "Anthropic", "elo": 1514, "delta": "#3", "license": "Proprietary", "note": "Fallback snapshot"},
            {"rank": 4, "model": "Claude Fable 5.1 (Max)", "org": "Anthropic", "elo": 1512, "delta": "#4", "license": "Proprietary", "note": "Fallback snapshot"},
            {"rank": 5, "model": "Claude Opus 5 (Max)", "org": "Anthropic", "elo": 1507, "delta": "#5", "license": "Proprietary", "note": "Fallback snapshot"},
        ],
        "coding": [],
        "open_weights": [],
    }


def _baseline_curated_stories():
    """High-signal structural stories blended only if live feeds return very few items."""
    return [
        {
            "title": "Hyperscaler Capex Scrutiny: Microsoft Re-evaluates Select Data Center & Oracle Cloud Capacity Deals",
            "category": "Hyperscalers & Deals",
            "impact_horizon": "Next 30 Days",
            "severity": "shift",
            "summary": "Wall Street is watching whether Microsoft shifts marginal AI training leases away from third-party hosts like Oracle toward its own custom silicon and internal Azure regions.",
            "stock_ripple": "Short-term volatility in ORCL & power/REIT plays; neutral-to-positive for MSFT margin discipline.",
            "sip_career_note": "Enterprises want multi-cloud portability on OpenShift/K8s instead of single-cloud lock-in.",
            "source": "Macro Radar",
            "url": "https://news.ycombinator.com/",
        },
        {
            "title": "Nvidia & Global Chip Supply: Bubble Jitters vs. Sovereign & Inference Demand",
            "category": "Chips & China AI",
            "impact_horizon": "Next 30 Days",
            "severity": "dip",
            "summary": "Questions around Nvidia export rules, China GPU workarounds, and AI capex ROI periodically trigger sharp tech swings as investors weigh training peaks against inference growth.",
            "stock_ripple": "High beta swings in NVDA & Nasdaq; PPFAS cash buffer + Flexi Cap structure absorbs tech drawdowns.",
            "sip_career_note": "More GPU cost pressure pushes banks toward quantized vLLM + KEDA scale-to-zero on Kubernetes.",
            "source": "Market Structure",
            "url": "https://news.ycombinator.com/",
        },
        {
            "title": "China Open-Weight AI Wave (DeepSeek / Qwen) Compresses Inference Margins",
            "category": "Chips & China AI",
            "impact_horizon": "Next 30 Days",
            "severity": "shift",
            "summary": "Chinese labs keep matching frontier proprietary benchmarks at a fraction of API cost, forcing US hyperscalers to justify premium pricing.",
            "stock_ripple": "Pressures pure API wrappers; benefits cloud infra and enterprise IT adopters (Indian IT & GCCs).",
            "sip_career_note": "Banks prefer private self-hosted open-weight models inside locked VPC clusters.",
            "source": "AI Ecosystem",
            "url": "https://lmarena.ai/",
        },
        {
            "title": "Cloud & M365/Outlook Outages + Tech Workforce Restructuring Reminders",
            "category": "Outages & Layoffs",
            "impact_horizon": "Next 30 Days",
            "severity": "shift",
            "summary": "Recurring Outlook/Azure identity outages and big-tech restructuring headlines highlight operational fragility as companies reallocate payroll budgets toward GPU clusters.",
            "stock_ripple": "Brief reputational noise; reinforces enterprise multi-region resilience spend.",
            "sip_career_note": "Hands-on SRE, etcd/ingress recovery, and multi-cluster OpenShift operators become harder to replace.",
            "source": "Infra Watch",
            "url": "https://www.theregister.com/",
        },
    ]


def _rule_based_synthesis(hn_stories, rss_stories, navs, stocks):
    """Build deterministic status bar, curated cards, and 30-day outlook from live inputs."""
    combined = hn_stories + rss_stories
    seen_titles = set()
    unique_live = []
    for st in combined:
        key = st["title"].lower()[:70]
        if key not in seen_titles:
            seen_titles.add(key)
            unique_live.append(st)

    nasdaq = next((s for s in stocks if s["symbol"] == "^NDX"), None)
    nvda = next((s for s in stocks if s["symbol"] == "NVDA"), None)
    live_nav_30d = [n["change_30d_pct"] for n in navs if n.get("status") == "LIVE"]
    avg_nav_30d = sum(live_nav_30d) / len(live_nav_30d) if live_nav_30d else 0.0

    headlines_blob = " ".join(s["title"].lower() for s in unique_live[:14])
    shift_hits = sum(
        1 for kw in ("outage", "cancel", "layoff", "scandal", "crash", "bubble", "deepseek", "qwen", "oracle", "60k", "down")
        if kw in headlines_blob
    )

    is_pullback = (
        (nasdaq and nasdaq["change_30d_pct"] <= -3.0)
        or (nvda and nvda["change_1d_pct"] <= -4.0)
        or (avg_nav_30d <= -2.5)
    )

    if is_pullback:
        status_bar = {
            "level": "BLUE",
            "badge": "SIP DISCOUNT WINDOW",
            "title": "US Tech / AI Pullback Detected — Monthly SIPs Buy Cheaper Units",
            "subtitle": f"Nasdaq 30d {nasdaq['change_30d_pct']:+.2f}% / NVDA 30d {nvda['change_30d_pct']:+.2f}%. Headlines look noisy, while Indian SIPs stay steady (30d avg {avg_nav_30d:+.2f}%).",
            "sip_action": "Keep Nifty 500 (40%), PPFAS Flexi Cap (30%), and Mid Cap (30%) strictly on autopilot. Red weeks improve rupee-cost averaging.",
        }
    elif shift_hits >= 2:
        status_bar = {
            "level": "AMBER",
            "badge": "INFRA / MACRO SHIFT",
            "title": "Real Hyperscaler & Infra Shifts in Today's Feed — Read the 3-Min Brief",
            "subtitle": "Notable cloud outage, deal restructuring, or open-weight AI disruption signals detected in today's headlines.",
            "sip_action": "Ignore short-term volatility; let the diversified SIP basket compound automatically.",
        }
    else:
        status_bar = {
            "level": "GREEN",
            "badge": "NORMAL AI CYCLE",
            "title": "All Normal — 90% of Today's AI Headlines Are Routine Media Noise",
            "subtitle": "Steady hyperscaler execution and normal market swings. No structural break requiring any portfolio action.",
            "sip_action": "Zero action needed: keep the 40/30/30 SIP basket locked on autopilot.",
        }

    curated = []
    for st in unique_live[:7]:
        cat = st.get("category") or _classify_story(st["title"])
        sev = "shift" if cat in ("Outages & Layoffs", "Hyperscalers & Deals") else "normal"
        if any(w in st["title"].lower() for w in ("crash", "bubble", "plunge", "selloff", "drop", "numbered")):
            sev = "dip"
        curated.append({
            "title": st["title"],
            "category": cat,
            "impact_horizon": "Next 30 Days",
            "severity": sev,
            "summary": st.get("snippet") or f"Live discussion from {st['source']} gaining traction across engineering and tech markets.",
            "stock_ripple": "Watch NVDA/MSFT/ORCL sympathy moves; Indian IT reacts with a 1-2 day lag.",
            "sip_career_note": "SIP stays untouched; note platform-engineering & AI reliability takeaways.",
            "source": st["source"],
            "url": st["url"],
            "points": st.get("points"),
        })

    if len(curated) < 4:
        curated.extend(_baseline_curated_stories()[: 4 - len(curated)])

    ppfas = next((n for n in navs if n["scheme_code"] == "122639"), None)
    nifty500 = next((n for n in navs if n["scheme_code"] == "147625"), None)
    midcap = next((n for n in navs if n["scheme_code"] == "140228"), None)

    ppfas_str = f"₹{ppfas['nav']} ({ppfas['change_30d_pct']:+.2f}% 30d)" if ppfas and ppfas["nav"] else "Tracking live"
    n500_str = f"₹{nifty500['nav']} ({nifty500['change_30d_pct']:+.2f}% 30d)" if nifty500 and nifty500["nav"] else "Tracking live"
    mid_str = f"₹{midcap['nav']} ({midcap['change_30d_pct']:+.2f}% 30d)" if midcap and midcap["nav"] else "Tracking live"

    thirty_day_outlook = {
        "global_tech": {
            "title": "Global AI & Big Tech (30-Day View)",
            "points": [
                "Expect choppy sessions around Nvidia supply/export rumors and Microsoft/Oracle data-center capex headlines.",
                "Cheaper Chinese open-weight releases (DeepSeek / Qwen) keep compressing raw token prices, shifting value from model APIs to enterprise deployment.",
                "Watch cloud reliability metrics—major M365/cloud outages push banks toward hybrid resilience.",
            ],
        },
        "indian_sips": {
            "title": "Indian Markets & Model SIP Basket",
            "points": [
                f"Motilal Nifty 500 (40%): {n500_str} — anchors the basket to India's broad domestic growth regardless of US chip headlines.",
                f"PPFAS Flexi Cap (30%): {ppfas_str} — gives controlled Alphabet/Microsoft/Meta exposure plus a ~15-20% cash cushion for dips.",
                f"Edelweiss Mid Cap (30%): {mid_str} — if global AI fear pulls mid-caps down over the next 30 days, monthly SIPs automatically accumulate extra units.",
            ],
        },
        "k8s_career": {
            "title": "Cloud, Kubernetes & AI Platform Radar",
            "points": [
                "Enterprise financial institutions care less about which closed model leads social media today and more about secure, private VPC inference.",
                "Open-weight leaders on the AI Leaderboard directly validate running vLLM + KEDA autoscaling on Kubernetes / OpenShift.",
                "Cloud outages and big-tech restructuring reinforce why owning multi-cluster reliability & ingress/TLS internals creates durable demand.",
            ],
        },
    }

    return {
        "status_bar": status_bar,
        "headline_banner": f"{len(unique_live)} live tech/AI signals scanned • AMFI NAVs & global bellwethers synced.",
        "curated_stories": curated,
        "thirty_day_outlook": thirty_day_outlook,
        "synthesis_mode": "Rule-Based Live Synthesizer (Add GEMINI_API_KEY for AI Brief)",
    }


def synthesize_with_gemini(hn_stories, rss_stories, navs, stocks, arena, api_key=None):
    """Call Gemini Free API if api_key or GEMINI_API_KEY is configured; else fallback cleanly."""
    api_key = (api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
    if not api_key:
        return _rule_based_synthesis(hn_stories, rss_stories, navs, stocks)

    raw_feed = (hn_stories + rss_stories)[:18]
    compact_feed = [
        {"title": s["title"], "source": s["source"], "url": s["url"], "category": s["category"], "points": s.get("points", 0)}
        for s in raw_feed
    ]
    compact_navs = [
        {"name": n["short_name"], "nav": n["nav"], "1d_pct": n["change_1d_pct"], "30d_pct": n["change_30d_pct"]}
        for n in navs
    ]
    compact_stocks = [
        {"symbol": s["symbol"], "1d_pct": s["change_1d_pct"], "30d_pct": s["change_30d_pct"]}
        for s in stocks
    ]

    prompt = (
        "You are an objective AI Macro & Portfolio Analyst for a Kubernetes/Cloud platform engineer "
        "tracking a 3-fund Indian SIP basket (40% Motilal Nifty 500, 30% PPFAS Flexi Cap, 30% Edelweiss Mid Cap). "
        "Keep language clean, generic, and public-safe (never mention specific rupee investment amounts or personal debt). "
        "Analyze these live tech/AI headlines, mutual fund NAVs, and stock bellwethers.\n\n"
        f"HEADLINES:\n{json.dumps(compact_feed)}\n\n"
        f"SIPS:\n{json.dumps(compact_navs)}\n\n"
        f"STOCKS:\n{json.dumps(compact_stocks)}\n\n"
        f"LEADERBOARD_TOP_3:\n{json.dumps(arena['overall'][:3])}\n\n"
        "Return 5 to 7 curated_stories, deduplicated, covering a mix of categories where the headlines allow. "
        "Use only URLs present in HEADLINES.\n"
        "Return strict JSON matching this exact schema:\n"
        "{\n"
        '  "status_bar": {\n'
        '    "level": "GREEN" or "AMBER" or "BLUE",\n'
        '    "badge": "short 2-4 word badge",\n'
        '    "title": "clear headline",\n'
        '    "subtitle": "calm 1-sentence summary",\n'
        '    "sip_action": "calm guidance reinforcing SIP autopilot (BLUE = dip discount window)"\n'
        "  },\n"
        '  "headline_banner": "1 concise sentence summarizing today",\n'
        '  "curated_stories": [\n'
        "    {\n"
        '      "title": "...",\n'
        '      "category": "Hyperscalers & Deals" | "Chips & China AI" | "Outages & Layoffs" | "Models & Open-Weights",\n'
        '      "impact_horizon": "Next 30 Days",\n'
        '      "severity": "normal" | "shift" | "dip",\n'
        '      "summary": "2-sentence plain summary",\n'
        '      "stock_ripple": "1-sentence US/India stock effect",\n'
        '      "sip_career_note": "1-sentence SIP or K8s platform takeaway",\n'
        '      "source": "...",\n'
        '      "url": "https://..."\n'
        "    }\n"
        "  ],\n"
        '  "thirty_day_outlook": {\n'
        '    "global_tech": {"title": "Global AI & Big Tech (30-Day View)", "points": ["...", "...", "..."]},\n'
        '    "indian_sips": {"title": "Indian Markets & Model SIP Basket", "points": ["...", "...", "..."]},\n'
        '    "k8s_career": {"title": "Cloud, Kubernetes & AI Platform Radar", "points": ["...", "...", "..."]}\n'
        "  }\n"
        "}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.25},
    }

    last_err = ""
    for model_name in GEMINI_MODELS:
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={urllib.parse.quote(api_key)}"
        try:
            resp = _http_post_json(endpoint, payload, timeout=35)
            raw_text = resp["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(raw_text)
            if "status_bar" in parsed and "curated_stories" in parsed and "thirty_day_outlook" in parsed:
                parsed["synthesis_mode"] = f"Gemini Free API ({model_name} LIVE)"
                return parsed
        except Exception as exc:
            last_err = str(exc)[:80]
            continue

    fallback = _rule_based_synthesis(hn_stories, rss_stories, navs, stocks)
    if last_err:
        fallback["synthesis_mode"] = f"Rule-Based Live Synthesizer (Gemini note: {last_err})"
    return fallback


def run_sync(api_key=None):
    """Run all fetchers in parallel, synthesize pulse data, write JSON + JS, and return payload."""
    os.makedirs(DATA_DIR, exist_ok=True)
    now_ist = datetime.now(IST)

    with ThreadPoolExecutor(max_workers=5) as pool:
        f_navs = pool.submit(fetch_mf_navs)
        f_stocks = pool.submit(fetch_stock_bellwethers)
        f_hn = pool.submit(fetch_hn_ai_stories)
        f_rss = pool.submit(fetch_rss_headlines)
        f_arena = pool.submit(get_arena_leaderboard)

        navs, live_navs = f_navs.result()
        stocks, live_stocks = f_stocks.result()
        hn_stories, hn_ok = f_hn.result()
        rss_stories, live_rss = f_rss.result()
        arena = f_arena.result()

    synthesis = synthesize_with_gemini(hn_stories, rss_stories, navs, stocks, arena, api_key=api_key)

    payload = {
        "meta": {
            "generated_at_iso": now_ist.isoformat(),
            "generated_at_display": now_ist.strftime("%d %b %Y, %I:%M %p IST"),
            "synthesis_mode": synthesis.get("synthesis_mode", "Rule-Based"),
            "sources_status": {
                "amfi_mfapi": f"{live_navs}/{len(SIP_FUNDS)} live",
                "stocks_yahoo": f"{live_stocks}/{len(STOCK_BELLWETHERS)} live",
                "hacker_news": f"{len(hn_stories)} stories" if hn_ok else "offline",
                "tech_rss": f"{live_rss}/{len(RSS_FEEDS)} feeds ({len(rss_stories)} stories)",
                "leaderboard": arena.get("updated_label", "Offline"),
            },
        },
        "status_bar": synthesis["status_bar"],
        "headline_banner": synthesis["headline_banner"],
        "curated_stories": synthesis["curated_stories"],
        "thirty_day_outlook": synthesis["thirty_day_outlook"],
        "live_hn_feed": hn_stories[:12],
        "rss_feed": rss_stories[:10],
        "mf_navs": navs,
        "stocks": stocks,
        "arena_leaderboard": arena,
    }

    tmp_json = JSON_OUT + ".tmp"
    with open(tmp_json, "w", encoding="utf-8") as f_json:
        json.dump(payload, f_json, indent=2, ensure_ascii=False)
    os.replace(tmp_json, JSON_OUT)

    tmp_js = JS_OUT + ".tmp"
    with open(tmp_js, "w", encoding="utf-8") as f_js:
        f_js.write("window.__AI_PULSE_DATA__ = ")
        json.dump(payload, f_js, indent=2, ensure_ascii=False)
        f_js.write(";\n")
    os.replace(tmp_js, JS_OUT)

    return payload


def main():
    """CLI entrypoint."""
    payload = run_sync()
    print(f"[AI Pulse] Updated {JSON_OUT} & {JS_OUT}")
    print(f"[AI Pulse] Status: {payload['status_bar']['level']} | Mode: {payload['meta']['synthesis_mode']}")
    print(f"[AI Pulse] Sources: {payload['meta']['sources_status']}")


if __name__ == "__main__":
    main()
