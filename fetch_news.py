# -*- coding: utf-8 -*-
"""
Bản Tin Sáng — script tạo bản tin tĩnh từ RSS.
Chạy tự động trên GitHub Actions theo lịch, xuất ra index.html.
Không dùng CORS proxy: tin được lấy ở phía máy chủ nên trình duyệt
của người đọc chỉ tải một trang HTML tĩnh.
"""

import html
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import feedparser
import requests

VN_TZ = timezone(timedelta(hours=7))
TIMEOUT = 20
MAX_PER_SECTION = 16
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 BanTinSang/1.0")

# ---------------------------------------------------------------- cấu hình nguồn

SECTIONS = [
    {
        "id": "kinh-te",
        "title": "Kinh tế vĩ mô & Thị trường",
        "feeds": [
            ("VnExpress",  "https://vnexpress.net/rss/kinh-doanh.rss"),
            ("CafeF",      "https://cafef.vn/thi-truong-chung-khoan.rss"),
            ("CafeF",      "https://cafef.vn/rss.chn"),
            ("Dân Trí",    "https://dantri.com.vn/rss/kinh-doanh.rss"),
            ("Thanh Niên", "https://thanhnien.vn/rss/kinh-te.rss"),
            ("Tuổi Trẻ",   "https://tuoitre.vn/rss/kinh-doanh.rss"),
            ("VietNamNet", "https://vietnamnet.vn/rss/kinh-doanh.rss"),
            ("VnEconomy",  "https://vneconomy.vn/tai-chinh.rss"),
        ],
    },
    {
        "id": "doanh-nghiep",
        "title": "Doanh nghiệp & Kinh doanh",
        "feeds": [
            ("CafeBiz",       "https://cafebiz.vn/rss/khoi-quan-tri-phat-trien-doanh-nghiep.rss"),
            ("CafeBiz",       "https://cafebiz.vn/rss/khoi-san-xuat-thuong-mai.rss"),
            ("CafeBiz",       "https://cafebiz.vn/rss/khoi-truyen-thong-thuong-hieu.rss"),
            ("Znews",         "https://znews.vn/rss/kinh-doanh-tai-chinh.rss"),
            ("BrandsVietnam",  "scrape:brandsvietnam"),
            ("Người Lao Động","https://nld.com.vn/rss/kinh-te.rss"),
            ("VietNamNet",    "https://vietnamnet.vn/rss/thi-truong.rss"),
        ],
    },
    {
        "id": "xa-hoi",
        "title": "Xã hội & Đời sống đô thị",
        "feeds": [
            ("VnExpress",     "https://vnexpress.net/rss/thoi-su.rss"),
            ("Dân Trí",       "https://dantri.com.vn/rss/xa-hoi.rss"),
            ("CafeBiz",       "https://cafebiz.vn/rss/khoi-xa-hoi-giao-duc-dich-vu.rss"),
            ("Znews",         "https://znews.vn/rss/xa-hoi.rss"),
            ("Tuổi Trẻ",      "https://tuoitre.vn/rss/thoi-su.rss"),
            ("VietNamNet",    "https://vietnamnet.vn/rss/thoi-su.rss"),
            ("Người Lao Động","https://nld.com.vn/rss/thoi-su.rss"),
        ],
    },
    {
        "id": "tam-ly",
        "title": "Tâm lý & Phong cách sống",
        "feeds": [
            ("Tatler", "scrape:tatler"),
            ("Vietcetera", "https://vietcetera.com/vn/feed"),
            ("Vietcetera", "https://vietcetera.com/feed"),
            ("Dân Trí",    "https://dantri.com.vn/rss/doi-song.rss"),
            ("Thanh Niên", "https://thanhnien.vn/rss/doi-song.rss"),
            ("VnExpress",  "https://vnexpress.net/rss/gia-dinh.rss"),
            ("VnExpress",  "https://vnexpress.net/rss/suc-khoe.rss"),
        ],
    },
    {
        "id": "su-nghiep",
        "title": "Sự nghiệp & Xu hướng",
        "feeds": [
            ("CafeBiz",    "https://cafebiz.vn/rss/khoi-tai-chinh-ngan-hang.rss"),
            ("Thanh Niên", "https://thanhnien.vn/rss/the-gioi/kinh-te-the-gioi.rss"),
            ("VnExpress",  "https://vnexpress.net/rss/giao-duc.rss"),
            ("VnEconomy",  "https://vneconomy.vn/chuyen-doi-so.rss"),
        ],
    },
    {
        "id": "cong-nghe",
        "title": "Công nghệ",
        "feeds": [
            ("VnExpress",  "https://vnexpress.net/rss/so-hoa.rss"),
            ("Dân Trí",    "https://dantri.com.vn/rss/cong-nghe.rss"),
            ("Znews",      "https://znews.vn/rss/cong-nghe.rss"),
            ("Thanh Niên", "https://thanhnien.vn/rss/cong-nghe.rss"),
            ("VietNamNet", "https://vietnamnet.vn/rss/cong-nghe.rss"),
            ("Tuổi Trẻ",   "https://tuoitre.vn/rss/nhip-song-so.rss"),
            ("CafeBiz",    "https://cafebiz.vn/rss/khoi-cong-nghe-doi-moi-sang-tao.rss"),
        ],
    },
]

# Từ khóa loại bỏ tin giải trí / showbiz (so khớp không phân biệt hoa thường)
BLOCKED_KEYWORDS = [
    "sao việt", "sao viet", "hoa hậu", "hoa hau", "á hậu", "a hau",
    "diễn viên", "dien vien", "ca sĩ", "ca si", "showbiz", "k-pop", "kpop",
    "người mẫu", "nguoi mau", "hoa khôi", "hoa khoi", "nam vương", "nam vuong",
    "rapper", "idol", "phim trường", "scandal", "hot girl", "hot boy",
    "liveshow", "mv ", "vũ trụ điện ảnh", "thảm đỏ", "tham do",
]

# ---------------------------------------------------------------- tiện ích

TAG_RE = re.compile(r"<[^>]+>")
IMG_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)
WS_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    text = TAG_RE.sub(" ", text or "")
    text = html.unescape(text)
    return WS_RE.sub(" ", text).strip()


def truncate(text: str, limit: int = 200) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def is_blocked(*texts: str) -> bool:
    joined = " ".join(t.lower() for t in texts if t)
    return any(kw in joined for kw in BLOCKED_KEYWORDS)


def extract_thumb(entry) -> str:
    for key in ("media_thumbnail", "media_content"):
        for item in entry.get(key, []) or []:
            url = item.get("url")
            if url:
                return url
    for enc in entry.get("enclosures", []) or []:
        href = enc.get("href") or enc.get("url")
        if href and any(ext in href.lower() for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")):
            return href
    for field in ("summary", "description"):
        raw = entry.get(field) or ""
        m = IMG_RE.search(raw)
        if m:
            return m.group(1)
    return ""


def entry_datetime(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc).astimezone(VN_TZ)
    return None


def scrape_tatler():
    """Tatler không có RSS — đọc bài tiếng Việt (đuôi -vn) từ HTML trang chủ."""
    resp = requests.get("https://www.tatlerasia.com/", timeout=TIMEOUT,
                        headers={"User-Agent": UA})
    items, seen = [], set()
    for m in re.finditer(
            r'<a[^>]+href="(/[a-z-]+/[a-z-]+/[^"]*-vn)"[^>]*>(.{0,400}?)</a>',
            resp.text, re.S):
        title = WS_RE.sub(" ", TAG_RE.sub(" ", m.group(2))).strip()
        link = "https://www.tatlerasia.com" + m.group(1)
        if len(title) > 20 and link not in seen:
            seen.add(link)
            items.append({"title": title, "link": link, "summary": ""})
    return items


def scrape_brandsvietnam():
    """BrandsVietnam không có RSS — đọc bài từ HTML trang Tiêu điểm."""
    resp = requests.get("https://www.brandsvietnam.com/featured/", timeout=TIMEOUT,
                        headers={"User-Agent": UA})
    items, seen = [], set()
    for m in re.finditer(
            r'<a[^>]+href="(https://www\.brandsvietnam\.com/congdong/topic/[^"]+)"[^>]*>([^<]{30,150})</a>',
            resp.text):
        title = WS_RE.sub(" ", m.group(2)).strip()
        if m.group(1) not in seen:
            seen.add(m.group(1))
            items.append({"title": title, "link": m.group(1), "summary": ""})
    return items


SCRAPERS = {"scrape:tatler": scrape_tatler, "scrape:brandsvietnam": scrape_brandsvietnam}


def fetch_feed(source: str, url: str):
    """Trả về (source, url, entries, status_ok, note)."""
    if url in SCRAPERS:
        try:
            entries = SCRAPERS[url]()
            if not entries:
                return source, url, [], False, "không trích được bài"
            return source, url, entries, True, f"{len(entries)} tin (đọc từ trang)"
        except requests.exceptions.Timeout:
            return source, url, [], False, "hết thời gian chờ"
        except Exception as exc:  # noqa: BLE001
            return source, url, [], False, type(exc).__name__
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
        if resp.status_code != 200:
            return source, url, [], False, f"HTTP {resp.status_code}"
        parsed = feedparser.parse(resp.content)
        if not parsed.entries:
            return source, url, [], False, "feed rỗng"
        return source, url, parsed.entries, True, f"{len(parsed.entries)} tin"
    except requests.exceptions.Timeout:
        return source, url, [], False, "hết thời gian chờ"
    except Exception as exc:  # noqa: BLE001
        return source, url, [], False, type(exc).__name__


# ---------------------------------------------------------------- thu thập

def collect():
    jobs = []
    for si, section in enumerate(SECTIONS):
        for source, url in section["feeds"]:
            jobs.append((si, source, url))

    results = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_feed, s, u): (si, s, u) for si, s, u in jobs}
        for fut in as_completed(futures):
            si, s, u = futures[fut]
            results[(si, u)] = fut.result()

    sections_out, diagnostics = [], []
    seen_links = set()

    for si, section in enumerate(SECTIONS):
        articles = []
        for source, url in section["feeds"]:
            src, _u, entries, ok, note = results[(si, url)]
            diagnostics.append((section["title"], src, url, ok, note))
            if not ok:
                continue
            for e in entries:
                link = (e.get("link") or "").strip()
                title = strip_html(e.get("title") or "")
                if not link or not title or link in seen_links:
                    continue
                summary = truncate(strip_html(e.get("summary") or e.get("description") or ""))
                if is_blocked(title, summary):
                    continue
                dt = entry_datetime(e)
                articles.append({
                    "source": src,
                    "sec_id": section["id"],
                    "grams": title_ngrams(title),
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "thumb": extract_thumb(e),
                    "dt": dt,
                })
                seen_links.add(link)

        dated = sorted((a for a in articles if a["dt"]), key=lambda a: a["dt"], reverse=True)
        undated = [a for a in articles if not a["dt"]]
        keep_undated = undated[:3]
        selected = dated[:MAX_PER_SECTION - len(keep_undated)] + keep_undated
        sections_out.append({**section, "articles": selected})

    return sections_out, diagnostics


# ---------------------------------------------------------------- kết xuất HTML

WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


def fmt_dt(dt):
    if not dt:
        return ""
    return dt.strftime("%d/%m/%Y · %H:%M")


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def render(sections, diagnostics) -> str:
    now = datetime.now(VN_TZ)
    date_line = f"{WEEKDAYS[now.weekday()]}, ngày {now.strftime('%d/%m/%Y')}"
    updated_line = f"Cập nhật lúc {now.strftime('%H:%M')} ngày {now.strftime('%d/%m/%Y')} (giờ Việt Nam)"

    # Ticker: tiêu đề mới nhất mỗi chuyên mục xen kẽ
    ticker_items = []
    for sec in sections:
        for art in sec["articles"][:3]:
            ticker_items.append((art["source"], art["title"], art["link"]))
    ticker_html = "".join(
        f'<a class="tk" href="{esc(l)}" target="_blank" rel="noopener">'
        f'<span class="tk-src">{esc(s)}</span>{esc(t)}</a>'
        for s, t, l in ticker_items
    ) or '<span class="tk">Chưa có tin — thử cập nhật lại sau.</span>'

    section_html = []
    for sec in sections:
        cards = []
        for art in sec["articles"]:
            if art["thumb"]:
                thumb = (f'<div class="thumb" style="background-image:url(\'{esc(art["thumb"])}\')"></div>')
            else:
                thumb = f'<div class="thumb thumb-empty"><span>{esc(art["source"])}</span></div>'
            cards.append(f"""
      <article class="card">
        {thumb}
        <div class="card-body">
          <span class="src">{esc(art["source"])}</span>
          <h3><a href="{esc(art["link"])}" target="_blank" rel="noopener">{esc(art["title"])}</a></h3>
          <p>{esc(art["summary"])}</p>
          <time>{fmt_dt(art["dt"])}</time>
        </div>
      </article>""")
        empty_note = "" if cards else '<p class="empty">Chuyên mục này chưa tải được tin trong lần cập nhật gần nhất.</p>'
        section_html.append(f"""
  <section id="{sec['id']}">
    <header class="sec-head"><h2>{esc(sec['title'])}</h2><span class="rule"></span></header>
    <div class="grid">{''.join(cards)}</div>{empty_note}
  </section>""")

    diag_html = "".join(
        f'<li class="{ "ok" if ok else "err" }">{ "✓" if ok else "✗" } {esc(src)} — {esc(note)}'
        f' <span class="diag-url">{esc(url)}</span></li>'
        for _sec, src, url, ok, note in diagnostics
    )

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bản Tin Sáng — {now.strftime('%d/%m/%Y')}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {{
  --paper:#EFEEE6; --ink:#1C2321; --brass:#9C6B1F; --moss:#48583F;
  --line:rgba(28,35,33,.16);
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--paper); color:var(--ink); font-family:'Inter',sans-serif; line-height:1.55; }}
a {{ color:inherit; text-decoration:none; }}
.wrap {{ max-width:1240px; margin:0 auto; padding:0 32px; }}

/* masthead */
.masthead {{ border-bottom:2px solid var(--ink); padding:36px 0 20px; }}
.masthead .wrap {{ display:flex; align-items:flex-end; justify-content:space-between; gap:24px; flex-wrap:wrap; }}
.masthead h1 {{ font-family:'Fraunces',serif; font-weight:700; font-size:52px; letter-spacing:-.01em; }}
.masthead h1 em {{ font-style:italic; color:var(--brass); }}
.meta {{ text-align:right; font-family:'IBM Plex Mono',monospace; font-size:12.5px; color:var(--moss); }}
.meta .today {{ display:block; color:var(--ink); font-size:13.5px; margin-bottom:4px; }}
.refresh-btn {{ display:inline-block; margin-top:8px; font-family:'IBM Plex Mono',monospace; font-size:11.5px;
  border:1px solid var(--brass); color:var(--brass); padding:5px 12px; letter-spacing:.05em; }}
.refresh-btn:hover {{ background:var(--brass); color:var(--paper); }}

/* ticker */
.ticker {{ border-bottom:1px solid var(--ink); background:var(--ink); color:var(--paper); overflow:hidden; white-space:nowrap; }}
.ticker-track {{ display:inline-block; padding:9px 0; animation:tick 90s linear infinite; }}
.ticker:hover .ticker-track {{ animation-play-state:paused; }}
.tk {{ font-family:'IBM Plex Mono',monospace; font-size:12.5px; margin-right:48px; }}
.tk-src {{ color:var(--brass); margin-right:10px; }}
.tk:hover {{ text-decoration:underline; }}
@keyframes tick {{ from {{ transform:translateX(0); }} to {{ transform:translateX(-50%); }} }}
@media (prefers-reduced-motion: reduce) {{ .ticker-track {{ animation:none; }} .ticker {{ overflow-x:auto; }} }}

/* sections */
section {{ padding:44px 0 8px; }}
.sec-head {{ max-width:1240px; margin:0 auto 22px; padding:0 32px; display:flex; align-items:center; gap:18px; }}
.sec-head h2 {{ font-family:'Fraunces',serif; font-weight:600; font-size:27px; white-space:nowrap; }}
.rule {{ flex:1; height:1px; background:var(--ink); position:relative; }}
.rule::after {{ content:""; position:absolute; right:0; top:-3px; width:7px; height:7px; background:var(--brass); }}
.grid {{ max-width:1240px; margin:0 auto; padding:0 32px; display:grid; grid-template-columns:repeat(4,1fr); gap:22px; }}
@media (max-width:1080px) {{ .grid {{ grid-template-columns:repeat(2,1fr); }} }}
@media (max-width:640px) {{ .grid {{ grid-template-columns:1fr; }} .masthead h1 {{ font-size:36px; }} .meta {{ text-align:left; }} }}

/* cards */
.card {{ display:flex; flex-direction:column; border:1px solid var(--line); background:#fbfaf4; }}
.thumb {{ aspect-ratio:16/9; background-size:cover; background-position:center; border-bottom:1px solid var(--line); }}
.thumb-empty {{ display:flex; align-items:center; justify-content:center;
  background:repeating-linear-gradient(45deg,#e6e4d8 0 10px,#efeee6 10px 20px); }}
.thumb-empty span {{ font-family:'IBM Plex Mono',monospace; font-size:12px; color:var(--moss); letter-spacing:.08em; text-transform:uppercase; }}
.card-body {{ padding:14px 16px 16px; display:flex; flex-direction:column; gap:8px; flex:1; }}
.src {{ font-family:'IBM Plex Mono',monospace; font-size:11px; letter-spacing:.1em; text-transform:uppercase; color:var(--brass); }}
.card h3 {{ font-family:'Fraunces',serif; font-weight:600; font-size:17.5px; line-height:1.32; }}
.card h3 a:hover {{ text-decoration:underline; text-decoration-color:var(--brass); }}
.card p {{ font-size:13.5px; color:rgba(28,35,33,.78); flex:1; }}
.card time {{ font-family:'IBM Plex Mono',monospace; font-size:11.5px; color:var(--moss); }}
.empty {{ max-width:1240px; margin:0 auto; padding:0 32px; color:var(--moss); font-size:14px; }}

/* footer */
footer {{ margin-top:56px; border-top:2px solid var(--ink); padding:28px 0 44px; font-size:13px; }}
footer h4 {{ font-family:'IBM Plex Mono',monospace; font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:var(--moss); margin-bottom:10px; }}
details {{ margin-top:14px; }}
summary {{ cursor:pointer; font-family:'IBM Plex Mono',monospace; font-size:12px; color:var(--moss); }}
.diag {{ list-style:none; margin-top:10px; font-family:'IBM Plex Mono',monospace; font-size:11.5px; line-height:1.9; }}
.diag .ok {{ color:var(--moss); }}
.diag .err {{ color:#8a3324; }}
.diag-url {{ opacity:.55; }}
.disclaimer {{ margin-top:14px; color:rgba(28,35,33,.6); }}
</style>
</head>
<body>

<header class="masthead">
  <div class="wrap">
    <h1>Bản Tin <em>Sáng</em></h1>
    <div class="meta">
      <span class="today">{esc(date_line)}</span>
      {esc(updated_line)}<br>Tự động cập nhật hằng ngày<br>
      <a class="refresh-btn" href="https://github.com/trangtranadtima-cmd/ban-tin-sang/actions/workflows/update.yml" target="_blank" rel="noopener" title="Mở GitHub → bấm Run workflow → chờ 30 giây → tải lại trang này">⟳ Cập nhật tin ngay</a>
    </div>
  </div>
</header>

<div class="ticker" aria-label="Tin mới nhất">
  <div class="ticker-track">{ticker_html}{ticker_html}</div>
</div>

<main>{''.join(section_html)}</main>

<footer>
  <div class="wrap">
    <h4>Nguồn tin</h4>
    <p>VnExpress · Dân Trí · CafeF · CafeBiz · Znews · Thanh Niên · Tuổi Trẻ · VietNamNet · Người Lao Động · VnEconomy · Vietcetera</p>
    <details>
      <summary>Trạng thái tải từng nguồn (lần cập nhật gần nhất)</summary>
      <ul class="diag">{diag_html}</ul>
    </details>
    <p class="disclaimer">Tiêu đề và mô tả lấy trực tiếp từ RSS chính thức của các báo. Bấm vào tin để đọc bài đầy đủ tại trang gốc.</p>
  </div>
</footer>

</body>
</html>
"""




# ================================================================ PHIÊN BẢN 2
# Chấm điểm "nóng": chủ đề xuất hiện trên nhiều báo khác nhau

STOPWORDS = set("""và của là có được cho với các những một trong đã sẽ khi này đó
về từ ở người tại vì sao hơn đến sau ra vẫn còn nhiều như thế nào cũng bị mới
trên dưới năm ngày hôm nay không thể làm gì ai đang theo lại rồi để bằng vào
ông bà anh chị em thì mà nếu hay hoặc do bởi cần nên phải trước giữa qua chỉ
việt nam tphcm hà nội video ảnh chùm""".split())

NGRAM_RE = re.compile(r"[0-9a-zà-ỹ]+")


def title_ngrams(title: str):
    words = [w for w in NGRAM_RE.findall(title.lower())
             if w not in STOPWORDS and len(w) > 1]
    grams = set()
    for n in (2, 3):
        for i in range(len(words) - n + 1):
            grams.add(" ".join(words[i:i + n]))
    return grams


def compute_hotness(all_articles):
    """Đếm mỗi cụm từ xuất hiện ở bao nhiêu BÁO khác nhau."""
    gram_sources = {}
    for art in all_articles:
        for g in art["grams"]:
            gram_sources.setdefault(g, set()).add(art["source"])
    gram_score = {g: len(s) for g, s in gram_sources.items()}
    for art in all_articles:
        best_gram, best = "", 1
        for g in art["grams"]:
            if gram_score.get(g, 1) > best:
                best, best_gram = gram_score[g], g
        art["hot"] = best - 1          # 0 = không báo nào khác cùng đưa
        art["hot_gram"] = best_gram
        art["hot_sources"] = best
    return gram_score, gram_sources


def recency_weight(dt, now):
    if not dt:
        return 0.0
    hours = max(0.0, (now - dt).total_seconds() / 3600)
    return max(0.0, 1.0 - hours / 48)   # tin trong 48h gần nhất được cộng điểm


def pick_highlights(sections, now, limit=12):
    pool = [a for s in sections for a in s["articles"]]
    for a in pool:
        a["score"] = a["hot"] * 2.0 + recency_weight(a["dt"], now) * 1.5
    pool.sort(key=lambda a: (a["score"], a["dt"] or datetime(1970, 1, 1, tzinfo=VN_TZ)),
              reverse=True)
    picked, per_sec, per_src = [], {}, {}
    for a in pool:
        if len(picked) >= limit:
            break
        if per_sec.get(a["sec_id"], 0) >= 3 or per_src.get(a["source"], 0) >= 3:
            continue
        picked.append(a)
        per_sec[a["sec_id"]] = per_sec.get(a["sec_id"], 0) + 1
        per_src[a["source"]] = per_src.get(a["source"], 0) + 1
    # nếu vì ràng buộc mà chưa đủ 12 thì nới lỏng
    if len(picked) < limit:
        for a in pool:
            if a not in picked:
                picked.append(a)
            if len(picked) >= limit:
                break
    return picked


def shorten(text, limit=72):
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def section_summary(sec, gram_sources):
    """Điểm nhanh: tổng hợp tự động từ tiêu đề (chủ đề nóng + tin đáng chú ý)."""
    arts = sec["articles"]
    if not arts:
        return "Chưa tải được tin cho chuyên mục này trong lần cập nhật gần nhất."
    # cụm từ nóng trong phạm vi chuyên mục
    local = {}
    for a in arts:
        for g in a["grams"]:
            local.setdefault(g, set()).add(a["source"])
    hot_phrases = sorted(
        ((g, len(s)) for g, s in local.items() if len(s) >= 2),
        key=lambda x: (x[1], len(x[0])), reverse=True)
    # loại cụm chồng lấn nhau
    chosen = []
    for g, n in hot_phrases:
        if any(g in c or c in g for c, _n in chosen):
            continue
        chosen.append((g, n))
        if len(chosen) == 2:
            break
    newest = max(arts, key=lambda a: a["dt"] or datetime(1970, 1, 1, tzinfo=VN_TZ))
    top_hot = max(arts, key=lambda a: a["hot"])
    parts = []
    if chosen:
        ph = " và ".join(f"“{g}”" for g, _n in chosen)
        nmax = max(n for _g, n in chosen)
        parts.append(f"Tâm điểm: {ph} — {nmax} báo cùng khai thác.")
    if top_hot["hot"] >= 1 and top_hot is not newest:
        parts.append(f"Đáng chú ý: {shorten(top_hot['title'])} ({top_hot['source']}).")
    parts.append(f"Mới nhất: {shorten(newest['title'])} ({newest['source']}, {fmt_dt(newest['dt'])}).")
    return " ".join(parts)


def render_v2(sections, diagnostics, highlights, summaries) -> str:
    now = datetime.now(VN_TZ)
    date_line = f"{WEEKDAYS[now.weekday()]}, ngày {now.strftime('%d/%m/%Y')}"
    updated_line = f"Cập nhật lúc {now.strftime('%H:%M')} ngày {now.strftime('%d/%m/%Y')} (giờ Việt Nam)"

    ticker_html = "".join(
        f'<a class="tk" href="{esc(a["link"])}" target="_blank" rel="noopener">'
        f'<span class="tk-src">{esc(a["source"])}</span>{esc(a["title"])}</a>'
        for a in highlights
    ) or '<span class="tk">Chưa có tin — thử cập nhật lại sau.</span>'

    def card(art, badge=False):
        if art["thumb"]:
            thumb = f'<div class="thumb" style="background-image:url(\'{esc(art["thumb"])}\')"></div>'
        else:
            thumb = f'<div class="thumb thumb-empty"><span>{esc(art["source"])}</span></div>'
        hot_badge = ""
        if badge and art.get("hot", 0) >= 1:
            hot_badge = f'<span class="hot-badge">{art["hot_sources"]} báo cùng đưa</span>'
        return f"""
      <article class="card">
        {thumb}
        <div class="card-body">
          <div class="card-top"><span class="src">{esc(art["source"])}</span>{hot_badge}</div>
          <h3><a href="{esc(art["link"])}" target="_blank" rel="noopener">{esc(art["title"])}</a></h3>
          <p>{esc(art["summary"])}</p>
          <time>{fmt_dt(art["dt"])}</time>
        </div>
      </article>"""

    hl_cards = "".join(card(a, badge=True) for a in highlights)

    brief_items = "".join(
        f'<div class="brief"><h4><button class="brief-link" data-target="tab-{sec["id"]}">'
        f'{esc(sec["title"])}</button></h4><p>{esc(summaries[sec["id"]])}</p></div>'
        for sec in sections
    )

    tab_buttons = ['<button class="tab-btn active" data-target="tab-tong-hop">Tổng hợp</button>']
    tab_panels = [f"""
  <section class="tab-panel active" id="tab-tong-hop">
    <header class="sec-head"><h2>12 tin nổi bật</h2><span class="rule"></span></header>
    <div class="grid">{hl_cards}</div>
    <header class="sec-head" style="margin-top:40px"><h2>Điểm nhanh từng chuyên mục</h2><span class="rule"></span></header>
    <div class="briefs">{brief_items}</div>
    <p class="note">Điểm nhanh được tổng hợp tự động từ tiêu đề trên các báo, không phải bài bình luận biên tập.</p>
  </section>"""]

    for sec in sections:
        tab_buttons.append(
            f'<button class="tab-btn" data-target="tab-{sec["id"]}">{esc(sec["title"])}</button>')
        page1 = "".join(card(a, badge=True) for a in sec["articles"][:8])
        page2 = "".join(card(a, badge=True) for a in sec["articles"][8:16])
        if page1:
            pages = f'<div class="slide-page"><div class="grid">{page1}</div></div>'
            hint = ""
            if page2:
                pages += f'<div class="slide-page"><div class="grid">{page2}</div></div>'
                hint = ('<div class="slide-nav"><button class="slide-btn prev" aria-label="Tin mới hơn">‹</button>'
                        '<span class="slide-hint">Kéo ngang hoặc bấm mũi tên để xem 8 tin cũ hơn</span>'
                        '<button class="slide-btn next" aria-label="Tin cũ hơn">›</button></div>')
            body = f'{hint}<div class="slide-track">{pages}</div>'
        else:
            body = '<p class="empty">Chuyên mục này chưa tải được tin.</p>'
        tab_panels.append(f"""
  <section class="tab-panel" id="tab-{sec['id']}">
    <header class="sec-head"><h2>{esc(sec['title'])}</h2><span class="rule"></span></header>
    <p class="sec-brief">{esc(summaries[sec['id']])}</p>
    {body}
  </section>""")

    diag_html = "".join(
        f'<li class="{ "ok" if ok else "err" }">{ "✓" if ok else "✗" } {esc(src)} — {esc(note)}'
        f' <span class="diag-url">{esc(url)}</span></li>'
        for _sec, src, url, ok, note in diagnostics
    )

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bản Tin Sáng — {now.strftime('%d/%m/%Y')}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {{
  --paper:#EFEEE6; --ink:#1C2321; --brass:#9C6B1F; --moss:#48583F;
  --line:rgba(28,35,33,.16);
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--paper); color:var(--ink); font-family:'Inter',sans-serif; line-height:1.55; }}
a {{ color:inherit; text-decoration:none; }}
.wrap {{ max-width:1240px; margin:0 auto; padding:0 32px; }}
.masthead {{ border-bottom:2px solid var(--ink); padding:36px 0 20px; }}
.masthead .wrap {{ display:flex; align-items:flex-end; justify-content:space-between; gap:24px; flex-wrap:wrap; }}
.masthead h1 {{ font-family:'Fraunces',serif; font-weight:700; font-size:52px; letter-spacing:-.01em; }}
.masthead h1 em {{ font-style:italic; color:var(--brass); }}
.meta {{ text-align:right; font-family:'IBM Plex Mono',monospace; font-size:12.5px; color:var(--moss); }}
.meta .today {{ display:block; color:var(--ink); font-size:13.5px; margin-bottom:4px; }}
.refresh-btn {{ display:inline-block; margin-top:8px; font-family:'IBM Plex Mono',monospace; font-size:11.5px;
  border:1px solid var(--brass); color:var(--brass); padding:5px 12px; letter-spacing:.05em; }}
.refresh-btn:hover {{ background:var(--brass); color:var(--paper); }}
.ticker {{ border-bottom:1px solid var(--ink); background:var(--ink); color:var(--paper); overflow:hidden; white-space:nowrap; }}
.ticker-track {{ display:inline-block; padding:9px 0; animation:tick 90s linear infinite; }}
.ticker:hover .ticker-track {{ animation-play-state:paused; }}
.tk {{ font-family:'IBM Plex Mono',monospace; font-size:12.5px; margin-right:48px; }}
.tk-src {{ color:var(--brass); margin-right:10px; }}
.tk:hover {{ text-decoration:underline; }}
@keyframes tick {{ from {{ transform:translateX(0); }} to {{ transform:translateX(-50%); }} }}
@media (prefers-reduced-motion: reduce) {{ .ticker-track {{ animation:none; }} .ticker {{ overflow-x:auto; }} }}
.tabbar {{ position:sticky; top:0; z-index:10; background:var(--paper); border-bottom:1px solid var(--ink); }}
.tabbar .wrap {{ display:flex; gap:4px; overflow-x:auto; }}
.tab-btn {{ font-family:'IBM Plex Mono',monospace; font-size:12.5px; letter-spacing:.04em;
  background:none; border:none; border-bottom:3px solid transparent; color:var(--moss);
  padding:13px 14px 10px; cursor:pointer; white-space:nowrap; }}
.tab-btn:hover {{ color:var(--ink); }}
.tab-btn.active {{ color:var(--ink); border-bottom-color:var(--brass); font-weight:500; }}
.tab-panel {{ display:none; padding:40px 0 8px; }}
.tab-panel.active {{ display:block; }}
.slide-nav {{ max-width:1240px; margin:-8px auto 14px; padding:0 32px; display:flex; align-items:center; gap:12px; }}
.slide-btn {{ font-family:'IBM Plex Mono',monospace; font-size:16px; line-height:1; width:30px; height:30px;
  border:1px solid var(--ink); background:#fbfaf4; color:var(--ink); cursor:pointer; }}
.slide-btn:hover {{ background:var(--brass); border-color:var(--brass); color:var(--paper); }}
.slide-hint {{ font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--moss); }}
.slide-track {{ display:flex; overflow-x:auto; scroll-snap-type:x mandatory; scroll-behavior:smooth; }}
.slide-track::-webkit-scrollbar {{ height:6px; }}
.slide-track::-webkit-scrollbar-thumb {{ background:var(--line); }}
.slide-page {{ flex:0 0 100%; scroll-snap-align:start; }}
.sec-head {{ max-width:1240px; margin:0 auto 20px; padding:0 32px; display:flex; align-items:center; gap:18px; }}
.sec-head h2 {{ font-family:'Fraunces',serif; font-weight:600; font-size:27px; white-space:nowrap; }}
.rule {{ flex:1; height:1px; background:var(--ink); position:relative; }}
.rule::after {{ content:""; position:absolute; right:0; top:-3px; width:7px; height:7px; background:var(--brass); }}
.sec-brief {{ max-width:1240px; margin:-6px auto 24px; padding:0 32px; font-size:14.5px; color:rgba(28,35,33,.85);
  border-left:3px solid var(--brass); margin-left:auto; }}
.sec-brief, .briefs {{ }}
.grid {{ max-width:1240px; margin:0 auto; padding:0 32px; display:grid; grid-template-columns:repeat(4,1fr); gap:22px; }}
@media (max-width:1080px) {{ .grid {{ grid-template-columns:repeat(2,1fr); }} }}
@media (max-width:640px) {{ .grid {{ grid-template-columns:1fr; }} .masthead h1 {{ font-size:36px; }} .meta {{ text-align:left; }} }}
.card {{ display:flex; flex-direction:column; border:1px solid var(--line); background:#fbfaf4; }}
.thumb {{ aspect-ratio:16/9; background-size:cover; background-position:center; border-bottom:1px solid var(--line); }}
.thumb-empty {{ display:flex; align-items:center; justify-content:center;
  background:repeating-linear-gradient(45deg,#e6e4d8 0 10px,#efeee6 10px 20px); }}
.thumb-empty span {{ font-family:'IBM Plex Mono',monospace; font-size:12px; color:var(--moss); letter-spacing:.08em; text-transform:uppercase; }}
.card-body {{ padding:14px 16px 16px; display:flex; flex-direction:column; gap:8px; flex:1; }}
.card-top {{ display:flex; align-items:center; justify-content:space-between; gap:8px; }}
.src {{ font-family:'IBM Plex Mono',monospace; font-size:11px; letter-spacing:.1em; text-transform:uppercase; color:var(--brass); }}
.hot-badge {{ font-family:'IBM Plex Mono',monospace; font-size:10px; color:#8a3324; border:1px solid #8a3324;
  padding:1px 6px; letter-spacing:.05em; white-space:nowrap; }}
.card h3 {{ font-family:'Fraunces',serif; font-weight:600; font-size:17.5px; line-height:1.32; }}
.card h3 a:hover {{ text-decoration:underline; text-decoration-color:var(--brass); }}
.card p {{ font-size:13.5px; color:rgba(28,35,33,.78); flex:1; }}
.card time {{ font-family:'IBM Plex Mono',monospace; font-size:11.5px; color:var(--moss); }}
.briefs {{ max-width:1240px; margin:0 auto; padding:0 32px; display:grid; grid-template-columns:repeat(2,1fr); gap:18px 32px; }}
@media (max-width:900px) {{ .briefs {{ grid-template-columns:1fr; }} }}
.brief {{ border:1px solid var(--line); background:#fbfaf4; padding:16px 18px; border-top:3px solid var(--brass); }}
.brief h4 {{ margin-bottom:6px; }}
.brief-link {{ font-family:'Fraunces',serif; font-weight:600; font-size:18px; background:none; border:none;
  cursor:pointer; color:var(--ink); padding:0; }}
.brief-link:hover {{ text-decoration:underline; text-decoration-color:var(--brass); }}
.brief p {{ font-size:13.5px; color:rgba(28,35,33,.82); }}
.note {{ max-width:1240px; margin:18px auto 0; padding:0 32px; font-family:'IBM Plex Mono',monospace;
  font-size:11.5px; color:var(--moss); }}
.empty {{ max-width:1240px; margin:0 auto; padding:0 32px; color:var(--moss); font-size:14px; }}
footer {{ margin-top:56px; border-top:2px solid var(--ink); padding:28px 0 44px; font-size:13px; }}
footer h4 {{ font-family:'IBM Plex Mono',monospace; font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:var(--moss); margin-bottom:10px; }}
details {{ margin-top:14px; }}
summary {{ cursor:pointer; font-family:'IBM Plex Mono',monospace; font-size:12px; color:var(--moss); }}
.diag {{ list-style:none; margin-top:10px; font-family:'IBM Plex Mono',monospace; font-size:11.5px; line-height:1.9; }}
.diag .ok {{ color:var(--moss); }}
.diag .err {{ color:#8a3324; }}
.diag-url {{ opacity:.55; }}
.disclaimer {{ margin-top:14px; color:rgba(28,35,33,.6); }}
</style>
</head>
<body>

<header class="masthead">
  <div class="wrap">
    <h1>Bản Tin <em>Sáng</em></h1>
    <div class="meta">
      <span class="today">{esc(date_line)}</span>
      {esc(updated_line)}<br>Tự động cập nhật hằng ngày<br>
      <a class="refresh-btn" href="https://github.com/trangtranadtima-cmd/ban-tin-sang/actions/workflows/update.yml" target="_blank" rel="noopener" title="Mở GitHub → bấm Run workflow → chờ 30 giây → tải lại trang này">⟳ Cập nhật tin ngay</a>
    </div>
  </div>
</header>

<div class="ticker" aria-label="Tin nổi bật">
  <div class="ticker-track">{ticker_html}{ticker_html}</div>
</div>

<nav class="tabbar"><div class="wrap">{''.join(tab_buttons)}</div></nav>

<main>{''.join(tab_panels)}</main>

<footer>
  <div class="wrap">
    <h4>Nguồn tin</h4>
    <p>VnExpress · Dân Trí · CafeF · CafeBiz · Znews · Thanh Niên · Tuổi Trẻ · VietNamNet · Người Lao Động · VnEconomy · Vietcetera · Tatler · BrandsVietnam</p>
    <details>
      <summary>Trạng thái tải từng nguồn (lần cập nhật gần nhất)</summary>
      <ul class="diag">{diag_html}</ul>
    </details>
    <p class="disclaimer">Tiêu đề và mô tả lấy trực tiếp từ RSS chính thức của các báo. Nhãn “N báo cùng đưa” và mục Điểm nhanh do máy tổng hợp từ tiêu đề. Bấm vào tin để đọc bài đầy đủ tại trang gốc.</p>
  </div>
</footer>

<script>
function activate(id) {{
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.target === id));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === id));
  window.scrollTo({{top: 0, behavior: 'instant'}});
}}
document.querySelectorAll('.tab-btn, .brief-link').forEach(el =>
  el.addEventListener('click', () => activate(el.dataset.target)));
document.querySelectorAll('.tab-panel').forEach(panel => {{
  const track = panel.querySelector('.slide-track');
  if (!track) return;
  panel.querySelectorAll('.slide-btn').forEach(btn =>
    btn.addEventListener('click', () => track.scrollBy({{left: btn.classList.contains('next') ? track.clientWidth : -track.clientWidth, behavior: 'smooth'}})));
}});
</script>
</body>
</html>
"""


def main():
    sections, diagnostics = collect()
    total = sum(len(s["articles"]) for s in sections)
    ok_feeds = sum(1 for *_x, ok, _n in diagnostics if ok)
    print(f"Tổng số tin: {total} | Nguồn tải thành công: {ok_feeds}/{len(diagnostics)}")
    for sec_title, src, url, ok, note in diagnostics:
        print(f"  [{'OK ' if ok else 'ERR'}] {src:<16} {note:<20} {url}")

    html_out = render(sections, diagnostics)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_out)
    print("Đã ghi index.html")

    # --- phiên bản 2: tab Tổng hợp + Điểm nhanh ---
    now = datetime.now(VN_TZ)
    all_articles = [a for s in sections for a in s["articles"]]
    gram_score, gram_sources = compute_hotness(all_articles)
    highlights = pick_highlights(sections, now, limit=12)
    summaries = {s["id"]: section_summary(s, gram_sources) for s in sections}
    with open("v2.html", "w", encoding="utf-8") as f:
        f.write(render_v2(sections, diagnostics, highlights, summaries))
    print("Đã ghi v2.html")

    # Nếu không lấy được tin nào thì báo lỗi để workflow hiển thị cảnh báo
    if total == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
