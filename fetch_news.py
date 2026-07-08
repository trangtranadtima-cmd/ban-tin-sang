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
MAX_PER_SECTION = 8
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
            ("CafeBiz",    "https://cafebiz.vn/rss/khoi-cong-nghe-doi-moi-sang-tao.rss"),
            ("CafeBiz",    "https://cafebiz.vn/rss/khoi-tai-chinh-ngan-hang.rss"),
            ("Thanh Niên", "https://thanhnien.vn/rss/the-gioi/kinh-te-the-gioi.rss"),
            ("VnExpress",  "https://vnexpress.net/rss/giao-duc.rss"),
            ("Dân Trí",    "https://dantri.com.vn/rss/cong-nghe.rss"),
            ("VnEconomy",  "https://vneconomy.vn/chuyen-doi-so.rss"),
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


def fetch_feed(source: str, url: str):
    """Trả về (source, url, entries, status_ok, note)."""
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
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "thumb": extract_thumb(e),
                    "dt": dt,
                })
                seen_links.add(link)

        articles.sort(key=lambda a: a["dt"] or datetime(1970, 1, 1, tzinfo=VN_TZ), reverse=True)
        sections_out.append({**section, "articles": articles[:MAX_PER_SECTION]})

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
      {esc(updated_line)}<br>Tự động cập nhật hằng ngày
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

    # Nếu không lấy được tin nào thì báo lỗi để workflow hiển thị cảnh báo
    if total == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
