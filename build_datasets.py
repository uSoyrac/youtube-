"""
Dataset İnşası — Üç Akademik Dataset

Dataset 1  → datasets/dataset1_ana_corpus.csv
  Tüm temiz yorumlar + video metadatası birleştirilmiş

Dataset 2  → datasets/dataset2_tematik_ornek.csv
  Purposive thematic analysis örneği (500-800 yorum)
  Seçim: en çok beğenilen + en uzun yanıt zinciri + kanal × kategori çeşitliliği

Dataset 3  → datasets/dataset3_ag_analizi.csv
  Yorum düğümü × yanıt ağırlığı — engagement network analizi için
"""

import csv
import random
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).parent
DS_DIR = BASE / "datasets"
DS_DIR.mkdir(exist_ok=True)

CLEAN_CSV    = BASE / "yorumlar_temiz.csv"
METADATA_CSV = BASE / "video_metadata.csv"

RANDOM_SEED = 42
random.seed(RANDOM_SEED)

# ─── Veri yükleme ─────────────────────────────────────────────

def load_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

comments = load_csv(CLEAN_CSV)
metadata = {r["video_id"]: r for r in load_csv(METADATA_CSV)}

print(f"Temiz yorum: {len(comments)}")
print(f"Video metadata: {len(metadata)}")

# ─── Dataset 1: Ana Corpus ────────────────────────────────────

D1_FIELDS = [
    "yorum_id", "video_id", "video_url",
    "channel_name", "channel_id",
    "kategori", "eslesen_keyword",
    "video_title", "video_published_at",
    "video_view_count", "video_like_count", "video_comment_count",
    "yorum_text", "yorum_tarihi",
    "begeni_sayisi", "yanit_sayisi",
    "yorum_kelime_sayisi",
]

d1_rows = []
for c in comments:
    vid = metadata.get(c["video_id"], {})
    d1_rows.append({
        "yorum_id":            c["yorum_id"],
        "video_id":            c["video_id"],
        "video_url":           c["video_url"],
        "channel_name":        c["channel_name"],
        "channel_id":          vid.get("channel_id", ""),
        "kategori":            c["kategori"],
        "eslesen_keyword":     vid.get("eslesen_keyword", ""),
        "video_title":         vid.get("video_title", ""),
        "video_published_at":  vid.get("published_at", ""),
        "video_view_count":    vid.get("view_count", ""),
        "video_like_count":    vid.get("like_count", ""),
        "video_comment_count": vid.get("comment_count", ""),
        "yorum_text":          c["yorum_text"],
        "yorum_tarihi":        c["yorum_tarihi"],
        "begeni_sayisi":       c["begeni_sayisi"],
        "yanit_sayisi":        c["yanit_sayisi"],
        "yorum_kelime_sayisi": len(c["yorum_text"].split()),
    })

with open(DS_DIR / "dataset1_ana_corpus.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=D1_FIELDS, extrasaction="ignore")
    w.writeheader()
    w.writerows(d1_rows)

print(f"\nDataset 1: {len(d1_rows)} yorum → datasets/dataset1_ana_corpus.csv")

# ─── Dataset 2: Tematik Analiz Örneği ─────────────────────────
# Purposive sample kriterleri:
#   A) Her kanal × kategori hücresinden en fazla beğenilen 5 yorum
#   B) Her kanal × kategori hücresinden en uzun yanıt zinciri olan 5 yorum
#   C) En uzun (kelime sayısı) 5 yorum her hücrede
#   → Birleşimi shuffle et, 600 yorum hedefi

CATEGORIES = ["ilk_saldir", "sivil_kayip", "hormuz", "ateskes", "genel"]
CHANNELS_4 = ["CNN", "BBC News", "Fox News", "Al Jazeera English"]

selected_ids: set[str] = set()
d2_rows: list[dict] = []

def add_to_d2(candidate):
    if candidate["yorum_id"] not in selected_ids:
        selected_ids.add(candidate["yorum_id"])
        d2_rows.append(candidate)

# Grup oluştur
groups = defaultdict(list)
for r in d1_rows:
    if r["channel_name"] in CHANNELS_4:
        groups[(r["channel_name"], r["kategori"])].append(r)

for (ch, cat), rows in groups.items():
    # A: En çok beğenilen 5
    by_likes = sorted(rows, key=lambda x: int(x["begeni_sayisi"] or 0), reverse=True)
    for r in by_likes[:5]:
        add_to_d2(r)

    # B: En uzun yanıt zinciri 5
    by_replies = sorted(rows, key=lambda x: int(x["yanit_sayisi"] or 0), reverse=True)
    for r in by_replies[:5]:
        add_to_d2(r)

    # C: En uzun yorum 5
    by_length = sorted(rows, key=lambda x: int(x["yorum_kelime_sayisi"]), reverse=True)
    for r in by_length[:5]:
        add_to_d2(r)

print(f"\nDataset 2 aday havuzu: {len(d2_rows)}")

# Hedef 600, havuz yeterliyse kısalt
TARGET_D2 = 600
if len(d2_rows) > TARGET_D2:
    # Kanal × kategori dağılımını koruyarak kırp
    random.shuffle(d2_rows)
    d2_rows = d2_rows[:TARGET_D2]

D2_FIELDS = D1_FIELDS + ["ornek_secim_nedeni"]
for r in d2_rows:
    likes = int(r["begeni_sayisi"] or 0)
    replies = int(r["yanit_sayisi"] or 0)
    words = int(r["yorum_kelime_sayisi"])
    reasons = []
    if likes >= 50:   reasons.append("high_likes")
    if replies >= 5:  reasons.append("long_reply_chain")
    if words >= 100:  reasons.append("long_comment")
    r["ornek_secim_nedeni"] = "|".join(reasons) if reasons else "stratified_sample"

with open(DS_DIR / "dataset2_tematik_ornek.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=D2_FIELDS, extrasaction="ignore")
    w.writeheader()
    w.writerows(d2_rows)

print(f"Dataset 2: {len(d2_rows)} yorum → datasets/dataset2_tematik_ornek.csv")

# Dağılım
d2_dist = defaultdict(int)
for r in d2_rows:
    d2_dist[(r["channel_name"][:15], r["kategori"])] += 1
for (ch, cat), n in sorted(d2_dist.items()):
    print(f"  {ch:<17} {cat:<15} {n:>3}")

# ─── Dataset 3: Ağ Analizi ────────────────────────────────────
# Düğüm → yorum, kenar ağırlığı → yanit_sayisi
# Engagement merkezlilik analizi için

D3_FIELDS = [
    "yorum_id", "video_id", "channel_name", "kategori",
    "video_title",
    "yorum_tarihi",
    "begeni_sayisi", "yanit_sayisi",
    "engagement_skoru",   # likes + 3×replies (yanıt ağırlıklı)
    "yorum_kelime_sayisi",
    "yorum_text_kisalt",  # ilk 200 karakter
]

d3_rows = []
for r in d1_rows:
    if r["channel_name"] not in CHANNELS_4:
        continue
    likes   = int(r["begeni_sayisi"] or 0)
    replies = int(r["yanit_sayisi"]  or 0)
    eng     = likes + 3 * replies
    d3_rows.append({
        "yorum_id":           r["yorum_id"],
        "video_id":           r["video_id"],
        "channel_name":       r["channel_name"],
        "kategori":           r["kategori"],
        "video_title":        r["video_title"][:80],
        "yorum_tarihi":       r["yorum_tarihi"],
        "begeni_sayisi":      likes,
        "yanit_sayisi":       replies,
        "engagement_skoru":   eng,
        "yorum_kelime_sayisi": r["yorum_kelime_sayisi"],
        "yorum_text_kisalt":  r["yorum_text"][:200],
    })

# engagement_skoru'na göre azalan sırala
d3_rows.sort(key=lambda x: x["engagement_skoru"], reverse=True)

with open(DS_DIR / "dataset3_ag_analizi.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=D3_FIELDS, extrasaction="ignore")
    w.writeheader()
    w.writerows(d3_rows)

print(f"\nDataset 3: {len(d3_rows)} yorum → datasets/dataset3_ag_analizi.csv")

top10 = d3_rows[:10]
print("Top 10 yorum (engagement):")
for r in top10:
    print(f"  eng={r['engagement_skoru']:>5}  likes={r['begeni_sayisi']:>4}  replies={r['yanit_sayisi']:>3}"
          f"  [{r['channel_name'][:10]}/{r['kategori'][:8]}]  {r['video_title'][:40]}")

print("\nTüm datasetler hazır → datasets/")
