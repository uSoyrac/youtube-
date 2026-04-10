"""
YouTube Data API v3 — Akademik Yorum Toplama
Konu  : 2026 ABD-İsrail-İran Savaşı
Tarih : 28 Şubat 2026 – 29 Mart 2026

Akış:
  Aşama 1 → playlistItems ile tüm videolar  → videos_raw.csv
  Aşama 2 → keyword filtresi + kategori     → videos_classified.csv
  Aşama 3 → top-3 seçimi                   → video_metadata.csv
  Aşama 4 → yorum çekimi                   → yorumlar_ham.csv
  Aşama 5 → filtreleme                     → yorumlar_temiz.csv

Kota tahmini: ~430 unit/gün  (limit: 10.000)
"""

from __future__ import annotations

import csv
import logging
import os
import re
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import langdetect
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ══════════════════════════════════════════════════════════════
# 0.  YAPILANDIRMA
# ══════════════════════════════════════════════════════════════

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
if not YOUTUBE_API_KEY:
    raise EnvironmentError("YOUTUBE_API_KEY .env dosyasında bulunamadı.")

DATE_START = "2026-02-28T00:00:00Z"
DATE_END   = "2026-03-29T23:59:59Z"

# YouTube handle → kanal adı
CHANNELS: dict[str, str] = {
    "CNN":                "@CNN",
    "BBC News":           "@BBCNews",
    "Fox News":           "@FoxNews",
    "Al Jazeera English": "@AlJazeeraEnglish",
    "Iran International": "@IranIntl",
}

# Kategori → anahtar kelimeler (başlık veya açıklamada aranır, küçük harf)
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "ilk_saldir": [
        "strike", "struck", "attack", "attacked", "bombing", "bombed",
        "airstrike", "air strike", "air raid", "missile", "missiles",
        "drone", "warplane", "warplanes", "explosion", "blast",
        "operation", "offensive", "february 28", "idf", "pentagon",
        "iran hit", "israel hit", "tehran bombed", "launched",
    ],
    "sivil_kayip": [
        "civilian", "civilians", "casualties", "killed", "death toll",
        "wounded", "injured", "hospital", "refugee", "displaced",
        "humanitarian", "children killed", "massacre", "victim",
        "bodies", "aid workers", "medical",
    ],
    "hormuz": [
        "hormuz", "strait", "crude oil", "oil price", "shipping",
        "blockade", "tanker", "vessel", "maritime", "energy supply",
        "sanctions", "barrel", "opec", "supply chain", "oil market",
    ],
    "ateskes": [
        "ceasefire", "cease-fire", "negotiations", "negotiate",
        "talks", "deal", "diplomacy", "diplomatic", "truce",
        "agreement", "peace deal", "mediation", "mediator",
        "united nations", "un resolution", "qatar", "envoy",
    ],
}

MAX_COMMENTS_PER_VIDEO = 500
MIN_WORD_COUNT         = 15
LANG_CONFIDENCE_MIN    = 0.90
DEDUP_THRESHOLD        = 0.90
QUOTA_SAFETY_LIMIT     = 8_000

OUTPUT_DIR = Path(__file__).parent

# ══════════════════════════════════════════════════════════════
# 1.  LOGLAMA
# ══════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(OUTPUT_DIR / "collect.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# 2.  KOTA TAKİPÇİSİ
# ══════════════════════════════════════════════════════════════

class QuotaTracker:
    COSTS = {
        "channels.list":       1,
        "playlistItems.list":  1,
        "videos.list":         1,
        "commentThreads.list": 1,
    }

    def __init__(self, limit: int = QUOTA_SAFETY_LIMIT):
        self._used  = 0
        self._limit = limit
        self._calls: dict[str, int] = {}

    def charge(self, endpoint: str) -> None:
        cost = self.COSTS.get(endpoint, 1)
        self._used += cost
        self._calls[endpoint] = self._calls.get(endpoint, 0) + 1
        if self._used >= self._limit:
            raise RuntimeError(
                f"Kota güvenlik eşiği aşıldı: {self._used}/{self._limit} unit. "
                "Checkpoint dosyaları korundu — yarın kaldığınız yerden devam edebilirsiniz."
            )

    @property
    def used(self) -> int:
        return self._used

    def report(self) -> str:
        lines = [f"Kota: {self._used}/{self._limit} unit"]
        for ep, n in sorted(self._calls.items()):
            lines.append(f"  {ep}: {n} × {self.COSTS.get(ep,1)} = {n * self.COSTS.get(ep,1)} unit")
        return "\n".join(lines)


quota = QuotaTracker()

# ══════════════════════════════════════════════════════════════
# 3.  API ÇAĞRI SARMALAYICISI — EXPONENTIAL BACKOFF
# ══════════════════════════════════════════════════════════════

def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

DATE_START_DT = _parse_dt(DATE_START)
DATE_END_DT   = _parse_dt(DATE_END)


def youtube_call(endpoint: str, fn, *, max_retries: int = 6, **kwargs):
    delay = 2
    for attempt in range(1, max_retries + 1):
        try:
            result = fn(**kwargs).execute()
            quota.charge(endpoint)
            return result
        except HttpError as exc:
            status = exc.resp.status
            if status in (403, 429) or status >= 500:
                log.warning("YouTube %s → HTTP %d (deneme %d/%d), %ds bekleniyor…",
                            endpoint, status, attempt, max_retries, delay)
                time.sleep(delay)
                delay = min(delay * 2, 120)
            else:
                log.error("YouTube %s → HTTP %d: %s", endpoint, status, exc)
                return None
        except RuntimeError:
            raise
        except Exception as exc:
            log.error("YouTube %s → beklenmedik hata: %s", endpoint, exc)
            return None
    log.error("YouTube %s → max deneme aşıldı, atlanıyor.", endpoint)
    return None

# ══════════════════════════════════════════════════════════════
# 4.  CSV YARDIMCILARI
# ══════════════════════════════════════════════════════════════

def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    log.info("  → %s kaydedildi (%d satır)", path.name, len(rows))


def load_checkpoint(path: Path) -> list[dict] | None:
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8-sig") as f:
        # NUL karakterleri filtrele (bazı yorum metinlerinde oluşabilir)
        clean = (line.replace("\x00", "") for line in f)
        rows = list(csv.DictReader(clean))
    log.info("  ✓ Checkpoint: %s (%d satır) — aşama atlanıyor.", path.name, len(rows))
    return rows

# ══════════════════════════════════════════════════════════════
# 5.  AŞAMA 1 — KANAL ID + UPLOADS PLAYLİST + TÜM VİDEOLAR
# ══════════════════════════════════════════════════════════════

RAW_VIDEO_FIELDS = [
    "video_id", "video_url", "video_title", "description", "tags",
    "channel_name", "channel_id", "published_at",
    "view_count", "comment_count", "like_count",
]
CHECKPOINT_RAW = OUTPUT_DIR / "videos_raw.csv"


def get_channel_info(youtube, channel_name: str, handle: str) -> tuple[str, str] | None:
    """channels.list?forHandle → (channel_id, uploads_playlist_id)  — 1 unit"""
    resp = youtube_call(
        "channels.list",
        youtube.channels().list,
        part="id,contentDetails",
        forHandle=handle,
    )
    if not resp or not resp.get("items"):
        log.error("  '%s' (%s) → kanal bulunamadı.", channel_name, handle)
        return None
    item    = resp["items"][0]
    cid     = item["id"]
    uploads = item["contentDetails"]["relatedPlaylists"]["uploads"]
    log.info("  '%s' → %s  (uploads: %s)", channel_name, cid, uploads)
    return cid, uploads


def fetch_videos_from_playlist(youtube, channel_name: str,
                                channel_id: str,
                                uploads_id: str) -> list[dict]:
    """playlistItems.list (1 unit/sayfa) + videos.list (1 unit/batch)"""
    log.info("  [%s] Playlist taranıyor…", channel_name)
    video_ids: list[str] = []
    next_page = None
    pages = 0

    while True:
        resp = youtube_call(
            "playlistItems.list",
            youtube.playlistItems().list,
            part="contentDetails",
            playlistId=uploads_id,
            maxResults=50,
            pageToken=next_page,
        )
        if not resp:
            break

        pages += 1
        stop = False
        for item in resp.get("items", []):
            pub_str = item["contentDetails"].get("videoPublishedAt", "")
            if not pub_str:
                continue
            pub_dt = _parse_dt(pub_str)
            if pub_dt > DATE_END_DT:
                continue
            if pub_dt < DATE_START_DT:
                stop = True
                break
            video_ids.append(item["contentDetails"]["videoId"])

        if stop:
            log.info("    DATE_START öncesine geçildi, erken çıkılıyor (%d sayfa).", pages)
            break

        next_page = resp.get("nextPageToken")
        if not next_page:
            break

    log.info("    %d video ID bulundu, istatistikler çekiliyor…", len(video_ids))

    videos: list[dict] = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        resp = youtube_call(
            "videos.list",
            youtube.videos().list,
            part="snippet,statistics",
            id=",".join(chunk),
        )
        if not resp:
            continue
        for v in resp.get("items", []):
            snip  = v["snippet"]
            stats = v.get("statistics", {})
            tags  = snip.get("tags", [])
            videos.append({
                "video_id":      v["id"],
                "video_url":     f"https://www.youtube.com/watch?v={v['id']}",
                "video_title":   snip.get("title", ""),
                "description":   snip.get("description", "")[:500],
                "tags":          "|".join(tags) if tags else "",
                "channel_name":  channel_name,
                "channel_id":    channel_id,
                "published_at":  snip.get("publishedAt", ""),
                "view_count":    stats.get("viewCount", "0"),
                "comment_count": int(stats.get("commentCount", 0)),
                "like_count":    stats.get("likeCount", "0"),
            })

    log.info("    → %d video detayı alındı.", len(videos))
    return videos


def phase1_collect_videos(youtube) -> list[dict]:
    checkpoint = load_checkpoint(CHECKPOINT_RAW)
    if checkpoint is not None:
        for r in checkpoint:
            r["comment_count"] = int(r.get("comment_count", 0))
        return checkpoint

    log.info("\n" + "═" * 60)
    log.info("[AŞAMA 1] Ham video çekimi başlıyor…")
    log.info("═" * 60)

    all_videos: list[dict] = []
    for ch_name, handle in CHANNELS.items():
        log.info("▶ %s (%s)", ch_name, handle)
        info = get_channel_info(youtube, ch_name, handle)
        if not info:
            continue
        channel_id, uploads_id = info
        try:
            vids = fetch_videos_from_playlist(youtube, ch_name, channel_id, uploads_id)
            all_videos.extend(vids)
        except RuntimeError:
            raise
        except Exception as exc:
            log.error("  '%s' video çekme hatası: %s", ch_name, exc)
        log.info("  [Kota] %d unit", quota.used)

    write_csv(CHECKPOINT_RAW, RAW_VIDEO_FIELDS, all_videos)
    log.info("[AŞAMA 1] %d video | %s", len(all_videos), quota.report())
    return all_videos

# ══════════════════════════════════════════════════════════════
# 6.  AŞAMA 2 — KEYWORD FİLTRESİ + KATEGORİ ATAMA (API çağrısı yok)
# ══════════════════════════════════════════════════════════════

CLASSIFIED_FIELDS = RAW_VIDEO_FIELDS + ["kategori", "eslesen_keyword"]
CHECKPOINT_CLASSIFIED = OUTPUT_DIR / "videos_classified.csv"


def assign_category(title: str, description: str) -> tuple[str, str]:
    """
    Başlık + açıklamada kategori anahtar kelimelerini arar.
    Birden fazla kategori eşleşirse hepsini döndürür (ilk eşleşen kategori atanır).
    Dönüş: (kategori, eslesen_keyword)  —  eşleşme yoksa ("alakasiz", "")
    """
    text = (title + " " + description).lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return cat, kw
    return "alakasiz", ""


def phase2_keyword_filter(videos: list[dict]) -> list[dict]:
    checkpoint = load_checkpoint(CHECKPOINT_CLASSIFIED)
    if checkpoint is not None:
        for r in checkpoint:
            r["comment_count"] = int(r.get("comment_count", 0))
        return checkpoint

    log.info("\n" + "═" * 60)
    log.info("[AŞAMA 2] Keyword filtresi uygulanıyor (%d video)…", len(videos))
    log.info("═" * 60)

    classified: list[dict] = []
    counts: dict[str, int] = {}

    for v in videos:
        cat, kw = assign_category(v["video_title"], v["description"])
        row = dict(v)
        row["kategori"]        = cat
        row["eslesen_keyword"] = kw
        classified.append(row)
        counts[cat] = counts.get(cat, 0) + 1

    for cat, n in sorted(counts.items()):
        log.info("  %-15s %d video", cat, n)

    write_csv(CHECKPOINT_CLASSIFIED, CLASSIFIED_FIELDS, classified)
    log.info("[AŞAMA 2] Tamamlandı. (API çağrısı: 0)")
    return classified

# ══════════════════════════════════════════════════════════════
# 7.  AŞAMA 3 — FİNAL VİDEO SEÇİMİ (top-3 per kanal × kategori)
# ══════════════════════════════════════════════════════════════

METADATA_FIELDS = [
    "video_id", "video_url", "video_title", "channel_name", "channel_id",
    "kategori", "eslesen_keyword", "comment_count", "view_count", "like_count",
    "published_at",
]


def phase3_select(classified: list[dict]) -> list[dict]:
    log.info("\n" + "═" * 60)
    log.info("[AŞAMA 3] Final video seçimi…")
    log.info("═" * 60)

    relevant = [v for v in classified if v["kategori"] != "alakasiz"]
    log.info("  Alakasız çıkarıldı → %d / %d video kaldı.", len(relevant), len(classified))

    groups: dict[tuple, list[dict]] = {}
    for v in relevant:
        key = (v["channel_name"], v["kategori"])
        groups.setdefault(key, []).append(v)

    selected: list[dict] = []
    for (ch, cat), vlist in sorted(groups.items()):
        vlist.sort(key=lambda x: int(x.get("comment_count", 0)), reverse=True)
        top3 = vlist[:3]
        for v in top3:
            selected.append({
                "video_id":        v["video_id"],
                "video_url":       v["video_url"],
                "video_title":     v["video_title"],
                "channel_name":    v["channel_name"],
                "channel_id":      v["channel_id"],
                "kategori":        cat,
                "eslesen_keyword": v.get("eslesen_keyword", ""),
                "comment_count":   v["comment_count"],
                "view_count":      v.get("view_count", ""),
                "like_count":      v.get("like_count", ""),
                "published_at":    v.get("published_at", ""),
            })
        log.info("  [%s / %s] %d video → top-%d", ch, cat, len(vlist), len(top3))

    write_csv(OUTPUT_DIR / "video_metadata.csv", METADATA_FIELDS, selected)
    log.info("[AŞAMA 3] %d video seçildi.", len(selected))
    return selected

# ══════════════════════════════════════════════════════════════
# 8.  AŞAMA 4 — YORUM ÇEKME
# ══════════════════════════════════════════════════════════════

COMMENT_FIELDS = [
    "yorum_id", "video_id", "video_url", "channel_name", "kategori",
    "yorum_text", "yorum_tarihi", "begeni_sayisi", "yanit_sayisi",
]
CHECKPOINT_COMMENTS_RAW = OUTPUT_DIR / "yorumlar_ham.csv"


def fetch_comments_for_video(youtube, video: dict) -> list[dict]:
    vid  = video["video_id"]
    log.info("    [%s] yorumlar çekiliyor…", vid)

    comments: list[dict] = []
    next_page = None

    while len(comments) < MAX_COMMENTS_PER_VIDEO:
        fetch_n = min(100, MAX_COMMENTS_PER_VIDEO - len(comments))
        resp = youtube_call(
            "commentThreads.list",
            youtube.commentThreads().list,
            part="snippet",
            videoId=vid,
            order="time",
            maxResults=fetch_n,
            textFormat="plainText",
            pageToken=next_page,
        )
        if not resp:
            break

        for item in resp.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "yorum_id":      item["id"],
                "video_id":      vid,
                "video_url":     video["video_url"],
                "channel_name":  video["channel_name"],
                "kategori":      video["kategori"],
                "yorum_text":    top.get("textDisplay", ""),
                "yorum_tarihi":  top.get("publishedAt", ""),
                "begeni_sayisi": top.get("likeCount", 0),
                "yanit_sayisi":  item["snippet"].get("totalReplyCount", 0),
            })

        next_page = resp.get("nextPageToken")
        if not next_page:
            break

    log.info("      → %d yorum alındı.", len(comments))
    return comments


def phase4_collect_comments(youtube, selected_videos: list[dict]) -> list[dict]:
    checkpoint = load_checkpoint(CHECKPOINT_COMMENTS_RAW)
    if checkpoint is not None:
        return checkpoint

    log.info("\n" + "═" * 60)
    log.info("[AŞAMA 4] Yorum çekimi (%d video)…", len(selected_videos))
    log.info("═" * 60)

    all_comments: list[dict] = []
    for i, video in enumerate(selected_videos, 1):
        log.info("  Video %d/%d — %s", i, len(selected_videos),
                 video["video_title"][:70])
        try:
            comments = fetch_comments_for_video(youtube, video)
            all_comments.extend(comments)
        except RuntimeError:
            raise
        except HttpError as exc:
            if exc.resp.status == 403:
                log.warning("  [%s] yorumlar kapalı, atlanıyor.", video["video_id"])
            else:
                log.error("  [%s] HTTP %d: %s", video["video_id"], exc.resp.status, exc)
        except Exception as exc:
            log.error("  [%s] beklenmedik hata: %s", video["video_id"], exc)
        log.info("  [Kota] %d unit", quota.used)

    write_csv(CHECKPOINT_COMMENTS_RAW, COMMENT_FIELDS, all_comments)
    log.info("[AŞAMA 4] %d ham yorum | %s", len(all_comments), quota.report())
    return all_comments

# ══════════════════════════════════════════════════════════════
# 9.  AŞAMA 5 — YORUM FİLTRELEME (API çağrısı yok)
# ══════════════════════════════════════════════════════════════

def _is_english(text: str) -> bool:
    try:
        for r in langdetect.detect_langs(text):
            if r.lang == "en" and r.prob >= LANG_CONFIDENCE_MIN:
                return True
        return False
    except langdetect.lang_detect_exception.LangDetectException:
        return False


def _fingerprint(text: str) -> str:
    """Yorumun ilk 80 karakterini normalleştirerek parmak izi oluşturur."""
    return re.sub(r"\s+", " ", text.strip().lower())[:80]


def phase5_filter(raw: list[dict]) -> list[dict]:
    """
    Dedup stratejisi — O(n) yerine O(n²) kaçınmak için iki aşamalı:
      1. Tam eşleşme: normalize metin hash'i ile anlık (set lookup)
      2. Bulanık eşleşme: her yorum yalnızca sonraki 300 komşusuyla
         karşılaştırılır (bot spam'ı zaman sırası içinde kümelenir)
    """
    log.info("\n" + "═" * 60)
    log.info("[AŞAMA 5] Yorum filtreleme (%d ham)…", len(raw))
    log.info("═" * 60)

    step = [c for c in raw
            if "[deleted]" not in c["yorum_text"].lower()
            and "[removed]" not in c["yorum_text"].lower()]
    log.info("  [deleted]/[removed] sonrası : %d", len(step))

    step = [c for c in step if len(c["yorum_text"].split()) >= MIN_WORD_COUNT]
    log.info("  Min %d kelime sonrası       : %d", MIN_WORD_COUNT, len(step))

    step = [c for c in step if _is_english(c["yorum_text"])]
    log.info("  İngilizce filtresi sonrası  : %d", len(step))

    # ── Aşama 1: tam eşleşme (hash) ──────────────────────────
    exact_seen: set[str] = set()
    after_exact: list[dict] = []
    for c in step:
        key = _fingerprint(c["yorum_text"])
        if key in exact_seen:
            continue
        exact_seen.add(key)
        after_exact.append(c)
    log.info("  Tam eşleşme dedup sonrası   : %d", len(after_exact))

    # ── Aşama 2: bulanık eşleşme — kayan pencere (±200) ─────
    # quick_ratio() tam hesaplamadan önce üst sınır verir; eğer o bile
    # eşiğin altındaysa tam karşılaştırma yapılmaz → ~10× hızlanma
    WINDOW = 200
    deduped: list[dict] = []
    window_texts: list[str] = []

    for c in after_exact:
        txt = c["yorum_text"]
        is_dup = False
        for prev in window_texts:
            sm = SequenceMatcher(None, txt, prev)
            if sm.quick_ratio() >= DEDUP_THRESHOLD and sm.ratio() >= DEDUP_THRESHOLD:
                is_dup = True
                break
        if is_dup:
            continue
        deduped.append(c)
        window_texts.append(txt)
        if len(window_texts) > WINDOW:
            window_texts.pop(0)

    log.info("  Bulanık dedup ≥%.0f%% sonrası  : %d", DEDUP_THRESHOLD * 100, len(deduped))

    write_csv(OUTPUT_DIR / "yorumlar_temiz.csv", COMMENT_FIELDS, deduped)
    log.info("[AŞAMA 5] Temiz yorum: %d", len(deduped))
    return deduped

# ══════════════════════════════════════════════════════════════
# 10. ANA AKIŞ
# ══════════════════════════════════════════════════════════════

def main():
    log.info("=" * 60)
    log.info("YouTube Veri Toplama Başlıyor")
    log.info("Tarih  : %s → %s", DATE_START, DATE_END)
    log.info("Çıktı  : %s", OUTPUT_DIR)
    log.info("Kota   : %d unit güvenlik eşiği", QUOTA_SAFETY_LIMIT)
    log.info("=" * 60)

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    try:
        raw_videos = phase1_collect_videos(youtube)
        if not raw_videos:
            log.error("Hiç video bulunamadı. Çıkılıyor.")
            return

        classified = phase2_keyword_filter(raw_videos)

        selected = phase3_select(classified)
        if not selected:
            log.error("Seçilen video yok. Çıkılıyor.")
            return

        raw_comments = phase4_collect_comments(youtube, selected)
        clean_comments = phase5_filter(raw_comments)

    except RuntimeError as exc:
        log.error("\n⚠  %s", exc)
        return

    log.info("\n" + "=" * 60)
    log.info("TAMAMLANDI")
    log.info("  Ham video     : %d", len(raw_videos))
    log.info("  Seçilen video : %d", len(selected))
    log.info("  Ham yorum     : %d", len(raw_comments))
    log.info("  Temiz yorum   : %d", len(clean_comments))
    log.info(quota.report())
    log.info("=" * 60)


if __name__ == "__main__":
    main()
