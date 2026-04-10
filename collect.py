"""
YouTube Data API v3 + Anthropic API — Akademik Yorum Toplama
Konu  : 2026 ABD-İsrail-İran Savaşı
Tarih : 28 Şubat 2026 – 29 Mart 2026

Kota tasarrufu:
  ❌ search.list        → 100 unit/sayfa  (kullanılmıyor)
  ✓ channels.list       →   1 unit/kanal  (kanal ID + uploads playlist ID)
  ✓ playlistItems.list  →   1 unit/sayfa  (video listesi)
  ✓ videos.list         →   1 unit/batch  (istatistik, 50 video/batch)
  ✓ commentThreads.list →   1 unit/sayfa  (yorumlar)

Tahmini günlük kota kullanımı: ~500 unit  (limit: 10.000)

Akış:
  Aşama 1 → playlistItems → videos_raw.csv
  Aşama 2 → Claude sınıf  → videos_classified.csv
  Aşama 3 → top-3 seçimi  → video_metadata.csv
  Aşama 4 → yorumlar çek  → yorumlar_ham.csv
  Aşama 5 → filtrele      → yorumlar_temiz.csv
"""

import csv
import logging
import os
import re
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import anthropic
import langdetect
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ══════════════════════════════════════════════════════════════
# 0.  YAPILANDIRMA
# ══════════════════════════════════════════════════════════════

load_dotenv()

YOUTUBE_API_KEY   = os.getenv("YOUTUBE_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

if not YOUTUBE_API_KEY:
    raise EnvironmentError("YOUTUBE_API_KEY .env dosyasında bulunamadı.")
if not ANTHROPIC_API_KEY:
    raise EnvironmentError("ANTHROPIC_API_KEY .env dosyasında bulunamadı.")

DATE_START = "2026-02-28T00:00:00Z"
DATE_END   = "2026-03-29T23:59:59Z"

# YouTube handle → kanal adı eşlemesi
# Handle formatı: @ ile başlayan kısa isim (youtube.com/@handle)
CHANNELS: dict[str, str] = {
    "CNN":                "@CNN",
    "BBC News":           "@BBCNews",
    "Fox News":           "@FoxNews",
    "Al Jazeera English": "@AlJazeeraEnglish",
    "Iran International": "@IranIntl",
}

MAX_COMMENTS_PER_VIDEO = 500
MIN_WORD_COUNT         = 15
LANG_CONFIDENCE_MIN    = 0.90
DEDUP_THRESHOLD        = 0.90
CLAUDE_BATCH_SIZE      = 20
CLAUDE_BATCH_DELAY_S   = 1.0

# Script kota limitini aşmadan duracak güvenlik eşiği
QUOTA_SAFETY_LIMIT = 8_000   # günlük 10.000'in %80'i

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
    """
    YouTube Data API v3 unit maliyetleri:
      channels.list        → 1 unit
      playlistItems.list   → 1 unit
      videos.list          → 1 unit
      commentThreads.list  → 1 unit
      search.list          → 100 unit  (bu scriptte KULLANILMIYOR)
    """

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

    def charge(self, endpoint: str, n: int = 1) -> None:
        cost = self.COSTS.get(endpoint, 1) * n
        self._used += cost
        self._calls[endpoint] = self._calls.get(endpoint, 0) + n
        if self._used >= self._limit:
            raise RuntimeError(
                f"Kota güvenlik eşiği aşıldı: {self._used}/{self._limit} unit. "
                "Mevcut checkpoint dosyalarından yarın devam edebilirsiniz."
            )

    @property
    def used(self) -> int:
        return self._used

    def report(self) -> str:
        lines = [f"Kota kullanımı: {self._used}/{self._limit} unit"]
        for ep, n in sorted(self._calls.items()):
            lines.append(f"  {ep}: {n} çağrı × {self.COSTS.get(ep, 1)} = {n * self.COSTS.get(ep, 1)} unit")
        return "\n".join(lines)


quota = QuotaTracker()

# ══════════════════════════════════════════════════════════════
# 3.  API ÇAĞRI SARMALAYICILARI — EXPONENTIAL BACKOFF
# ══════════════════════════════════════════════════════════════

def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

DATE_START_DT = _parse_dt(DATE_START)
DATE_END_DT   = _parse_dt(DATE_END)


def youtube_call(endpoint: str, fn, *, max_retries: int = 6, **kwargs):
    """
    YouTube API çağrısını yapar, kota sayacını günceller,
    hata durumunda exponential backoff uygular.
    """
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
            raise   # kota eşiği — yukarı taşı
        except Exception as exc:
            log.error("YouTube %s → beklenmedik hata: %s", endpoint, exc)
            return None
    log.error("YouTube %s → max deneme aşıldı, atlanıyor.", endpoint)
    return None


def anthropic_call(client: anthropic.Anthropic, messages: list, *,
                   model: str = "claude-sonnet-4-6",
                   max_tokens: int = 4096,
                   max_retries: int = 6):
    """Anthropic API çağrısını exponential backoff ile sarar."""
    delay = 2
    for attempt in range(1, max_retries + 1):
        try:
            return client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
            )
        except anthropic.RateLimitError as exc:
            log.warning("Anthropic rate-limit (deneme %d/%d), %ds bekleniyor… (%s)",
                        attempt, max_retries, delay, exc)
            time.sleep(delay)
            delay = min(delay * 2, 120)
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                log.warning("Anthropic sunucu %d (deneme %d/%d), %ds bekleniyor…",
                            exc.status_code, attempt, max_retries, delay)
                time.sleep(delay)
                delay = min(delay * 2, 120)
            else:
                log.error("Anthropic API %d: %s", exc.status_code, exc)
                return None
        except Exception as exc:
            log.error("Anthropic beklenmedik hata: %s", exc)
            return None
    log.error("Anthropic max deneme aşıldı, batch atlanıyor.")
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
    """Checkpoint varsa yükle, yoksa None döndür."""
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    log.info("  ✓ Checkpoint: %s (%d satır) — aşama atlanıyor.", path.name, len(rows))
    return rows

# ══════════════════════════════════════════════════════════════
# 5.  AŞAMA 1 — KANAL ID + UPLOADS PLAYLİST + TÜM VİDEOLAR
# ══════════════════════════════════════════════════════════════
#
# Kota:  channels.list       1 unit × 5 kanal    =   5 unit
#        playlistItems.list  1 unit × ~3 sayfa   =  ~15 unit (5 kanal)
#        videos.list         1 unit × ~10 batch  =  ~10 unit
#        TOPLAM              ~30 unit  (önceki: ~10.000 unit!)

RAW_VIDEO_FIELDS = [
    "video_id", "video_url", "video_title", "description", "tags",
    "channel_name", "channel_id", "published_at",
    "view_count", "comment_count", "like_count",
]
CHECKPOINT_RAW = OUTPUT_DIR / "videos_raw.csv"


def get_channel_info(youtube, channel_name: str, handle: str) -> tuple[str, str] | None:
    """
    channels.list?forHandle → (channel_id, uploads_playlist_id)
    Maliyet: 1 unit
    """
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
    log.info("  '%s' → channel_id=%s  uploads=%s", channel_name, cid, uploads)
    return cid, uploads


def fetch_videos_from_playlist(youtube, channel_name: str,
                                channel_id: str,
                                uploads_playlist_id: str) -> list[dict]:
    """
    playlistItems.list ile uploads playlist'ini sayfalayarak DATE_START–DATE_END
    arasındaki videoları toplar. Playlist'in yeniden eskiye sıralı olması nedeniyle
    DATE_START'ın altına düşünce erken çıkar.
    Maliyet: 1 unit/sayfa
    """
    log.info("  [%s] Playlist taranıyor: %s", channel_name, uploads_playlist_id)
    video_ids_in_range: list[str] = []
    next_page = None
    pages_fetched = 0

    while True:
        resp = youtube_call(
            "playlistItems.list",
            youtube.playlistItems().list,
            part="contentDetails",
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=next_page,
        )
        if not resp:
            break

        pages_fetched += 1
        items = resp.get("items", [])
        stop_early = False

        for item in items:
            pub_str = item["contentDetails"].get("videoPublishedAt", "")
            if not pub_str:
                continue
            pub_dt = _parse_dt(pub_str)

            if pub_dt > DATE_END_DT:
                continue           # henüz tarih aralığı başlamamış, atla
            if pub_dt < DATE_START_DT:
                stop_early = True  # tarih aralığının gerisine düştük
                break
            video_ids_in_range.append(item["contentDetails"]["videoId"])

        if stop_early:
            log.info("    DATE_START öncesine geçildi, erken çıkılıyor (%d sayfa tarandı).",
                     pages_fetched)
            break

        next_page = resp.get("nextPageToken")
        if not next_page:
            break

    log.info("    %d video ID aralıkta bulundu, istatistikler çekiliyor…",
             len(video_ids_in_range))

    # videos.list ile snippet + statistics — 50'lik batch
    videos: list[dict] = []
    for i in range(0, len(video_ids_in_range), 50):
        chunk = video_ids_in_range[i : i + 50]
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
    log.info("[AŞAMA 1] Ham video çekimi  (kota: channels.list + playlistItems.list)")
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

        log.info("  [Kota] %d unit kullanıldı.", quota.used)

    write_csv(CHECKPOINT_RAW, RAW_VIDEO_FIELDS, all_videos)
    log.info("[AŞAMA 1] %d video toplandı | %s", len(all_videos), quota.report())
    return all_videos

# ══════════════════════════════════════════════════════════════
# 6.  AŞAMA 2 — CLAUDE İLE SINIFLANDIRMA
# ══════════════════════════════════════════════════════════════

CLASSIFIED_FIELDS = RAW_VIDEO_FIELDS + ["claude_ilgili", "claude_kategori", "claude_gerekce"]
CHECKPOINT_CLASSIFIED = OUTPUT_DIR / "videos_classified.csv"

CLASSIFY_PROMPT_TEMPLATE = """\
Aşağıdaki YouTube videolarının her biri 2026 ABD-İsrail-İran Savaşı ile ilgili mi?

Kategori tanımları:
- ilk_saldir : Saldırıların başlaması, hava harekâtı, askeri operasyon
- sivil_kayip: Sivil ölümler, insani kriz, hastane, mülteci
- hormuz      : Boğaz kapanması, petrol, deniz ticareti, tanker
- ateskes     : Müzakere, ateşkes, diplomatik girişim, anlaşma
- genel       : İran savaşıyla ilgili ama yukarıdaki kategorilere girmiyor
- alakasiz    : Bu savaşla ilgisi yok

Her video için SADECE şu formatı kullan (başka metin ekleme):
VIDEO_ID: <id>
ILGILI: evet/hayır
KATEGORİ: ilk_saldir/sivil_kayip/hormuz/ateskes/genel/alakasiz
GEREKCE: <tek cümle>
---

Videolar:
{videos_block}
"""


def parse_claude_response(text: str, batch_ids: list[str]) -> dict[str, dict]:
    results: dict[str, dict] = {}
    for block in re.split(r"\n---\n?", text.strip()):
        block = block.strip()
        if not block:
            continue
        vid_m = re.search(r"VIDEO_ID:\s*(\S+)", block)
        ilg_m = re.search(r"ILGILI:\s*(evet|hay[ıi]r)", block, re.IGNORECASE)
        kat_m = re.search(
            r"KATEGORİ:\s*(ilk_saldir|sivil_kayip|hormuz|ateskes|genel|alakasiz)",
            block, re.IGNORECASE,
        )
        ger_m = re.search(r"GEREKCE:\s*(.+)", block)

        if not vid_m:
            continue
        vid = vid_m.group(1).strip()
        results[vid] = {
            "claude_ilgili":   ilg_m.group(1).lower() if ilg_m else "bilinmiyor",
            "claude_kategori": kat_m.group(1).lower() if kat_m else "bilinmiyor",
            "claude_gerekce":  ger_m.group(1).strip() if ger_m else "",
        }

    for vid in batch_ids:
        if vid not in results:
            log.warning("    Claude yanıtında %s yok → varsayılan atandı.", vid)
            results[vid] = {
                "claude_ilgili":   "bilinmiyor",
                "claude_kategori": "bilinmiyor",
                "claude_gerekce":  "Claude yanıtında bulunamadı",
            }
    return results


def phase2_classify(videos: list[dict]) -> list[dict]:
    checkpoint = load_checkpoint(CHECKPOINT_CLASSIFIED)
    if checkpoint is not None:
        for r in checkpoint:
            r["comment_count"] = int(r.get("comment_count", 0))
        return checkpoint

    log.info("\n" + "═" * 60)
    log.info("[AŞAMA 2] Claude sınıflandırması (%d video, batch=%d)…",
             len(videos), CLAUDE_BATCH_SIZE)
    log.info("═" * 60)

    client     = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    classified : list[dict] = []
    batches    = [videos[i : i + CLAUDE_BATCH_SIZE]
                  for i in range(0, len(videos), CLAUDE_BATCH_SIZE)]

    for b_idx, batch in enumerate(batches, 1):
        log.info("  Batch %d/%d (%d video)…", b_idx, len(batches), len(batch))

        block_lines = []
        for v in batch:
            desc = v["description"][:300].replace("\n", " ")
            block_lines.append(
                f"VIDEO_ID: {v['video_id']}\n"
                f"Başlık: {v['video_title']}\n"
                f"Açıklama: {desc}"
            )

        resp = anthropic_call(
            client,
            [{"role": "user",
              "content": CLASSIFY_PROMPT_TEMPLATE.format(
                  videos_block="\n\n".join(block_lines)
              )}],
        )

        if resp is None:
            batch_results = {
                v["video_id"]: {
                    "claude_ilgili":   "bilinmiyor",
                    "claude_kategori": "bilinmiyor",
                    "claude_gerekce":  "API hatası",
                }
                for v in batch
            }
        else:
            batch_results = parse_claude_response(
                resp.content[0].text,
                [v["video_id"] for v in batch],
            )

        for v in batch:
            row = dict(v)
            row.update(batch_results[v["video_id"]])
            classified.append(row)

        if b_idx < len(batches):
            time.sleep(CLAUDE_BATCH_DELAY_S)

    write_csv(CHECKPOINT_CLASSIFIED, CLASSIFIED_FIELDS, classified)
    log.info("[AŞAMA 2] Tamamlandı.")
    return classified

# ══════════════════════════════════════════════════════════════
# 7.  AŞAMA 3 — FİNAL VİDEO SEÇİMİ (top-3 per kanal × kategori)
# ══════════════════════════════════════════════════════════════

METADATA_FIELDS = [
    "video_id", "video_url", "video_title", "channel_name", "channel_id",
    "kategori", "claude_gerekce", "comment_count", "view_count", "like_count",
    "published_at",
]


def phase3_select(classified: list[dict]) -> list[dict]:
    log.info("\n" + "═" * 60)
    log.info("[AŞAMA 3] Final video seçimi…")
    log.info("═" * 60)

    relevant = [v for v in classified
                if v.get("claude_ilgili", "").lower() == "evet"
                and v.get("claude_kategori", "alakasiz") != "alakasiz"]
    log.info("  Alakasız çıkarıldı → %d / %d video kaldı.", len(relevant), len(classified))

    groups: dict[tuple, list[dict]] = {}
    for v in relevant:
        key = (v["channel_name"], v["claude_kategori"])
        groups.setdefault(key, []).append(v)

    selected: list[dict] = []
    for (ch, cat), vlist in sorted(groups.items()):
        vlist.sort(key=lambda x: int(x.get("comment_count", 0)), reverse=True)
        top3 = vlist[:3]
        for v in top3:
            selected.append({
                "video_id":       v["video_id"],
                "video_url":      v["video_url"],
                "video_title":    v["video_title"],
                "channel_name":   v["channel_name"],
                "channel_id":     v["channel_id"],
                "kategori":       cat,
                "claude_gerekce": v.get("claude_gerekce", ""),
                "comment_count":  v["comment_count"],
                "view_count":     v.get("view_count", ""),
                "like_count":     v.get("like_count", ""),
                "published_at":   v.get("published_at", ""),
            })
        log.info("  [%s / %s] %d video → top-%d seçildi.", ch, cat, len(vlist), len(top3))

    write_csv(OUTPUT_DIR / "video_metadata.csv", METADATA_FIELDS, selected)
    log.info("[AŞAMA 3] Toplam %d video seçildi.", len(selected))
    return selected

# ══════════════════════════════════════════════════════════════
# 8.  AŞAMA 4 — YORUM ÇEKME
# ══════════════════════════════════════════════════════════════
#
# Kota: commentThreads.list  1 unit/sayfa
#       ~75 video × 5 sayfa (500 yorum / 100/sayfa) = ~375 unit

COMMENT_FIELDS = [
    "yorum_id", "video_id", "video_url", "channel_name", "kategori",
    "yorum_text", "yorum_tarihi", "begeni_sayisi", "yanit_sayisi",
]
CHECKPOINT_COMMENTS_RAW = OUTPUT_DIR / "yorumlar_ham.csv"


def fetch_comments_for_video(youtube, video: dict) -> list[dict]:
    vid  = video["video_id"]
    vurl = video["video_url"]
    ch   = video["channel_name"]
    cat  = video["kategori"]
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
                "video_url":     vurl,
                "channel_name":  ch,
                "kategori":      cat,
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
                log.error("  [%s] yorum hatası: %s", video["video_id"], exc)
        except Exception as exc:
            log.error("  [%s] beklenmedik hata: %s", video["video_id"], exc)

        log.info("  [Kota] %d unit kullanıldı.", quota.used)

    write_csv(CHECKPOINT_COMMENTS_RAW, COMMENT_FIELDS, all_comments)
    log.info("[AŞAMA 4] %d ham yorum | %s", len(all_comments), quota.report())
    return all_comments

# ══════════════════════════════════════════════════════════════
# 9.  AŞAMA 5 — YORUM FİLTRELEME (saf Python, API çağrısı yok)
# ══════════════════════════════════════════════════════════════

def _is_english(text: str) -> bool:
    try:
        for r in langdetect.detect_langs(text):
            if r.lang == "en" and r.prob >= LANG_CONFIDENCE_MIN:
                return True
        return False
    except langdetect.lang_detect_exception.LangDetectException:
        return False


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def phase5_filter(raw: list[dict]) -> list[dict]:
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

    seen: list[str] = []
    deduped: list[dict] = []
    for c in step:
        txt = c["yorum_text"]
        if any(_similarity(txt, s) >= DEDUP_THRESHOLD for s in seen):
            continue
        seen.append(txt)
        deduped.append(c)
    log.info("  Dedup ≥%.0f%% sonrası         : %d", DEDUP_THRESHOLD * 100, len(deduped))

    write_csv(OUTPUT_DIR / "yorumlar_temiz.csv", COMMENT_FIELDS, deduped)
    log.info("[AŞAMA 5] Temiz yorum: %d", len(deduped))
    return deduped

# ══════════════════════════════════════════════════════════════
# 10. ANA AKIŞ
# ══════════════════════════════════════════════════════════════

def main():
    log.info("=" * 60)
    log.info("YouTube + Claude Veri Toplama Başlıyor")
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

        classified = phase2_classify(raw_videos)

        selected = phase3_select(classified)
        if not selected:
            log.error("Seçilen video yok. Çıkılıyor.")
            return

        raw_comments = phase4_collect_comments(youtube, selected)
        clean_comments = phase5_filter(raw_comments)

    except RuntimeError as exc:
        # Kota güvenlik eşiği
        log.error("\n⚠  %s", exc)
        log.error("Mevcut checkpoint dosyalarından yarın kaldığınız yerden devam edebilirsiniz.")
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
