#!/usr/bin/env python3
"""CU viral signal monitor.

Runs on GitHub Actions with Python stdlib only.
Public sources work without keys. NAVER/YouTube/Telegram are enabled by secrets.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "data" / "state.json"
REPORT_PATH = ROOT / "reports" / "latest.md"
KST = dt.timezone(dt.timedelta(hours=9))
USER_AGENT = "CU-Viral-Monitor/1.0 (+github-actions)"


def now_kst() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).astimezone(KST)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> bytes:
    hdrs = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_json(url: str, headers: dict[str, str] | None = None, data: bytes | None = None, method: str | None = None) -> Any:
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs, data=data, method=method)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def clean_text(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def stable_id(source: str, url: str, title: str) -> str:
    raw = f"{source}|{url}|{title}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:20]


def relevant_text(text: str, config: dict[str, Any]) -> bool:
    low = text.lower()
    cu_tokens = [x.lower() for x in config.get("cu_tokens", [])]
    product_tokens = [x.lower() for x in config.get("product_signal_tokens", [])]
    watch_terms = [x.lower() for x in config.get("watch_terms", [])]
    has_cu = any(t in low for t in cu_tokens) or any(t in low for t in watch_terms)
    has_product = any(t in low for t in product_tokens) or any(t in low for t in watch_terms)
    return has_cu and has_product


def hot_text(text: str, config: dict[str, Any]) -> bool:
    low = text.lower()
    return any(t.lower() in low for t in config.get("hot_intent_tokens", []))


def fetch_google_trends(config: dict[str, Any]) -> list[dict[str, Any]]:
    geo = config.get("google_trends_geo", "KR")
    url = f"https://trends.google.com/trending/rss?geo={urllib.parse.quote(geo)}"
    items: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(http_get(url))
        ns = {"ht": "https://trends.google.com/trending/rss"}
        for item in root.findall(".//item"):
            title = clean_text(item.findtext("title", ""))
            traffic = clean_text(item.findtext("ht:approx_traffic", "", ns))
            if relevant_text(title, config):
                items.append({
                    "source": "Google Trends",
                    "title": title,
                    "url": f"https://trends.google.com/trends/explore?geo={geo}&q={urllib.parse.quote(title)}",
                    "detail": f"급상승 검색어 {traffic}" if traffic else "급상승 검색어",
                    "published": "",
                })
    except Exception as exc:
        print(f"[warn] Google Trends failed: {exc}", file=sys.stderr)
    return items


def fetch_google_news(config: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=int(config.get("recent_hours", 30)))
    for query in config.get("search_queries", []):
        params = urllib.parse.urlencode({"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
        url = f"https://news.google.com/rss/search?{params}"
        try:
            root = ET.fromstring(http_get(url))
            for item in root.findall(".//item")[: int(config.get("max_results_per_query", 12))]:
                title = clean_text(item.findtext("title", ""))
                link = clean_text(item.findtext("link", ""))
                pub = clean_text(item.findtext("pubDate", ""))
                if not relevant_text(title, config):
                    continue
                if pub:
                    try:
                        pdt = email.utils.parsedate_to_datetime(pub)
                        if pdt.tzinfo is None:
                            pdt = pdt.replace(tzinfo=dt.timezone.utc)
                        if pdt.astimezone(dt.timezone.utc) < cutoff:
                            continue
                    except (TypeError, ValueError):
                        pass
                out.append({"source": "Google News", "title": title, "url": link, "detail": query, "published": pub})
        except Exception as exc:
            print(f"[warn] Google News '{query}' failed: {exc}", file=sys.stderr)
    return out


def naver_headers() -> dict[str, str] | None:
    cid = os.getenv("NAVER_CLIENT_ID", "").strip()
    secret = os.getenv("NAVER_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        return None
    return {"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": secret}


def fetch_naver_search(config: dict[str, Any]) -> list[dict[str, Any]]:
    headers = naver_headers()
    if not headers:
        return []
    out: list[dict[str, Any]] = []
    for endpoint, label in (("blog", "Naver Blog"), ("cafearticle", "Naver Cafe")):
        for query in config.get("search_queries", []):
            params = urllib.parse.urlencode({"query": query, "display": 20, "start": 1, "sort": "date", "format": "json"})
            url = f"https://naverapihub.apigw.ntruss.com/search/v1/{endpoint}?{params}"
            try:
                data = http_json(url, headers=headers)
                for row in data.get("items", []):
                    title = clean_text(row.get("title", ""))
                    desc = clean_text(row.get("description", ""))
                    if not relevant_text(f"{title} {desc}", config):
                        continue
                    out.append({
                        "source": label,
                        "title": title,
                        "url": row.get("link", ""),
                        "detail": query,
                        "published": row.get("postdate", ""),
                    })
            except Exception as exc:
                print(f"[warn] {label} '{query}' failed: {exc}", file=sys.stderr)
    return out


def fetch_naver_trend(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a qualitative spike signal; exact ratios are intentionally not reported."""
    headers = naver_headers()
    terms = config.get("trend_watch_terms", [])[:5]
    if not headers or not terms:
        return []
    today = now_kst().date()
    body = {
        "startDate": (today - dt.timedelta(days=9)).isoformat(),
        "endDate": today.isoformat(),
        "timeUnit": "date",
        "keywordGroups": [{"groupName": t, "keywords": [t]} for t in terms],
    }
    try:
        data = http_json(
            "https://naverapihub.apigw.ntruss.com/search-trend/v1/search",
            headers={**headers, "Content-Type": "application/json"},
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST",
        )
    except Exception as exc:
        print(f"[warn] Naver Search Trend failed: {exc}", file=sys.stderr)
        return []

    out: list[dict[str, Any]] = []
    for result in data.get("results", []):
        points = result.get("data", [])
        if len(points) < 4:
            continue
        vals = [float(p.get("ratio", 0.0)) for p in points]
        latest = vals[-1]
        base_vals = [v for v in vals[:-1] if v > 0]
        if not base_vals:
            continue
        avg = sum(base_vals) / len(base_vals)
        if latest >= max(avg * 2.0, 20.0) and latest >= max(base_vals[-3:] + [0]) * 1.35:
            term = clean_text(result.get("title", ""))
            out.append({
                "source": "Naver DataLab",
                "title": term,
                "url": "https://datalab.naver.com/keyword/trendSearch.naver",
                "detail": "검색 관심 급상승",
                "published": today.isoformat(),
            })
    return out


def fetch_youtube(config: dict[str, Any]) -> list[dict[str, Any]]:
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not key:
        return []
    out: list[dict[str, Any]] = []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=int(config.get("recent_hours", 30)))
    published_after = cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for query in config.get("youtube_queries", config.get("search_queries", []))[:8]:
        params = urllib.parse.urlencode({
            "part": "snippet",
            "q": query,
            "type": "video",
            "order": "date",
            "maxResults": 12,
            "publishedAfter": published_after,
            "regionCode": "KR",
            "relevanceLanguage": "ko",
            "key": key,
        })
        try:
            data = http_json(f"https://www.googleapis.com/youtube/v3/search?{params}")
            for row in data.get("items", []):
                vid = row.get("id", {}).get("videoId", "")
                snip = row.get("snippet", {})
                title = clean_text(snip.get("title", ""))
                desc = clean_text(snip.get("description", ""))
                if not vid or not relevant_text(f"{title} {desc}", config):
                    continue
                out.append({
                    "source": "YouTube",
                    "title": title,
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "detail": query,
                    "published": snip.get("publishedAt", ""),
                })
        except Exception as exc:
            print(f"[warn] YouTube '{query}' failed: {exc}", file=sys.stderr)
    return out


def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for item in items:
        key = item.get("url") or item.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def classify(new_items: list[dict[str, Any]], config: dict[str, Any]) -> tuple[str, list[str]]:
    if not new_items:
        return "NONE", []
    sources = {x["source"] for x in new_items}
    trend_sources = {"Google Trends", "Naver DataLab"}
    social_sources = {"Naver Blog", "Naver Cafe", "YouTube"}
    hot_count = sum(1 for x in new_items if hot_text(f"{x['title']} {x.get('detail', '')}", config))
    reasons: list[str] = []
    if sources & trend_sources:
        reasons.append("검색 관심 급상승 신호")
    if len(sources & social_sources) >= 2:
        reasons.append("서로 다른 사용자 채널에서 동시 노출")
    if hot_count >= 2:
        reasons.append("품절·재고·구매/후기성 표현 반복")
    if len(sources) >= 3:
        reasons.append("여러 출처에서 동시에 포착")

    if (sources & trend_sources and len(sources) >= 2) or len(sources & social_sources) >= 2 or (len(sources) >= 2 and hot_count >= 2):
        return "ALERT", reasons
    if len(new_items) >= 4 and len(sources) >= 2:
        return "WATCH", reasons or ["짧은 기간 신규 노출 증가"]
    return "NONE", reasons


def telegram_send(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("[info] Telegram secrets missing; report only.")
        return False
    ok = True
    for i in range(0, len(text), 3800):
        payload = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": text[i:i + 3800],
            "disable_web_page_preview": "true",
        }).encode("utf-8")
        try:
            http_json(f"https://api.telegram.org/bot{token}/sendMessage", data=payload, method="POST")
        except Exception as exc:
            print(f"[warn] Telegram send failed: {exc}", file=sys.stderr)
            ok = False
    return ok


def render_report(level: str, reasons: list[str], items: list[dict[str, Any]], enabled_sources: list[str]) -> tuple[str, str]:
    ts = now_kst().strftime("%Y-%m-%d %H:%M KST")
    title = {"ALERT": "🚨 CU 바이럴 이상징후", "WATCH": "🔥 CU 바이럴 관찰"}.get(level, "✅ CU 바이럴 감시: 특이사항 없음")
    lines = [title, f"확인: {ts}"]
    if reasons:
        lines.append("판단: " + " / ".join(reasons))
    if items:
        lines.append("")
        for item in items[:10]:
            lines.append(f"• [{item['source']}] {item['title']}")
            if item.get("url"):
                lines.append(f"  {item['url']}")
    lines.extend(["", "확인 채널: " + ", ".join(enabled_sources)])
    text = "\n".join(lines)

    md = [f"# {title}", "", f"- 확인 시각: {ts}", f"- 활성 소스: {', '.join(enabled_sources)}"]
    if reasons:
        md.append("- 판단 근거: " + " / ".join(reasons))
    md.extend(["", "## 신규 포착"])
    if items:
        for item in items[:30]:
            md.append(f"- **{item['source']}** — [{item['title']}]({item.get('url', '')})")
    else:
        md.append("- 특이사항 없음")
    md.extend(["", "> 이 시스템은 판매량을 예측하지 않습니다. 평소와 다른 검색·노출 급증을 조기에 찾는 감시용입니다."])
    return text, "\n".join(md) + "\n"


def main() -> int:
    config = load_json(CONFIG_PATH, {})
    state = load_json(STATE_PATH, {"seen": {}, "last_run": None, "last_alert": None})
    seen: dict[str, str] = state.get("seen", {})

    items: list[dict[str, Any]] = []
    enabled = ["Google Trends", "Google News"]
    items.extend(fetch_google_trends(config))
    items.extend(fetch_google_news(config))
    if naver_headers():
        enabled.extend(["Naver Blog", "Naver Cafe", "Naver DataLab"])
        items.extend(fetch_naver_search(config))
        items.extend(fetch_naver_trend(config))
    if os.getenv("YOUTUBE_API_KEY", "").strip():
        enabled.append("YouTube")
        items.extend(fetch_youtube(config))

    new_items: list[dict[str, Any]] = []
    ts = now_kst().isoformat()
    for item in dedupe(items):
        sid = stable_id(item["source"], item.get("url", ""), item["title"])
        if sid not in seen:
            new_items.append(item)
            seen[sid] = ts

    level, reasons = classify(new_items, config)
    text, md = render_report(level, reasons, new_items, enabled)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(md, encoding="utf-8")
    print(text)

    hour = now_kst().hour
    should_send = level in {"ALERT", "WATCH"} or hour == int(config.get("daily_summary_hour_kst", 9)) or os.getenv("FORCE_TELEGRAM", "") == "1"
    if should_send:
        sent = telegram_send(text)
        if sent and level in {"ALERT", "WATCH"}:
            state["last_alert"] = ts

    state["seen"] = dict(sorted(seen.items(), key=lambda kv: kv[1], reverse=True)[:2000])
    state["last_run"] = ts
    state["last_level"] = level
    save_json(STATE_PATH, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
