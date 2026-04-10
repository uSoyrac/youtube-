"""
Sentiment & Descriptive Analysis
Girdi  : yorumlar_temiz.csv + video_metadata.csv
Çıktı  :
  results/sentiment_yorumlar.csv   — yorum bazında skor
  results/kanal_ozet.csv           — kanal bazında özet
  results/kategori_ozet.csv        — kategori bazında özet
  results/zaman_seri.csv           — günlük duygu trendi
  results/figures/                 — grafikler (PNG)
"""

import csv
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")           # GUI gerektirmez
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# ──────────────────────────────────────────────
# 0.  YAPILANDIRMA
# ──────────────────────────────────────────────

BASE_DIR    = Path(__file__).parent
RESULTS_DIR = BASE_DIR / "results"
FIG_DIR     = RESULTS_DIR / "figures"
RESULTS_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

CLEAN_CSV    = BASE_DIR / "yorumlar_temiz.csv"
METADATA_CSV = BASE_DIR / "video_metadata.csv"

CHANNEL_COLORS = {
    "CNN":                "#CC0000",
    "BBC News":           "#BB1919",
    "Fox News":           "#003DA5",
    "Al Jazeera English": "#FDB813",
    "Iran International": "#009900",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE_DIR / "analyze.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 1.  VERİ YÜKLEME
# ──────────────────────────────────────────────

def load_clean(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    log.info("Temiz yorum yüklendi: %d satır", len(rows))
    return rows


def load_metadata(path: Path) -> dict[str, dict]:
    """video_id → metadata satırı"""
    result = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            result[row["video_id"]] = row
    log.info("Video metadata yüklendi: %d video", len(result))
    return result

# ──────────────────────────────────────────────
# 2.  VADER SENTİMENT
# ──────────────────────────────────────────────

def run_sentiment(rows: list[dict]) -> list[dict]:
    """Her yoruma compound, pos, neu, neg skorları ekle."""
    log.info("Sentiment analizi başlıyor (%d yorum)…", len(rows))
    analyzer = SentimentIntensityAnalyzer()
    enriched = []
    for r in rows:
        scores = analyzer.polarity_scores(r["yorum_text"])
        row = dict(r)
        row["compound"] = round(scores["compound"], 4)
        row["pos"]      = round(scores["pos"], 4)
        row["neu"]      = round(scores["neu"], 4)
        row["neg"]      = round(scores["neg"], 4)
        # Etiket: compound > 0.05 → pozitif, < -0.05 → negatif, diğer → nötr
        if scores["compound"] >= 0.05:
            row["sentiment"] = "pozitif"
        elif scores["compound"] <= -0.05:
            row["sentiment"] = "negatif"
        else:
            row["sentiment"] = "notr"
        enriched.append(row)

    log.info("  → Sentiment tamamlandı.")
    return enriched

# ──────────────────────────────────────────────
# 3.  ÖZET TABLOLAR
# ──────────────────────────────────────────────

def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    log.info("  → %s (%d satır)", path.name, len(rows))


def build_kanal_ozet(enriched: list[dict]) -> list[dict]:
    groups: dict[str, list[float]] = defaultdict(list)
    sentiment_counts: dict[str, dict] = defaultdict(lambda: {"pozitif": 0, "negatif": 0, "notr": 0})

    for r in enriched:
        ch = r["channel_name"]
        groups[ch].append(float(r["compound"]))
        sentiment_counts[ch][r["sentiment"]] += 1

    rows = []
    for ch, scores in sorted(groups.items()):
        n = len(scores)
        avg = sum(scores) / n
        sc = sentiment_counts[ch]
        rows.append({
            "kanal":         ch,
            "yorum_sayisi":  n,
            "ort_compound":  round(avg, 4),
            "pozitif_oran":  round(sc["pozitif"] / n, 4),
            "notr_oran":     round(sc["notr"]    / n, 4),
            "negatif_oran":  round(sc["negatif"] / n, 4),
            "pozitif_n":     sc["pozitif"],
            "notr_n":        sc["notr"],
            "negatif_n":     sc["negatif"],
        })
    return rows


def build_kategori_ozet(enriched: list[dict]) -> list[dict]:
    groups: dict[tuple, list[float]] = defaultdict(list)
    sentiment_counts: dict[tuple, dict] = defaultdict(lambda: {"pozitif": 0, "negatif": 0, "notr": 0})

    for r in enriched:
        key = (r["channel_name"], r["kategori"])
        groups[key].append(float(r["compound"]))
        sentiment_counts[key][r["sentiment"]] += 1

    rows = []
    for (ch, cat), scores in sorted(groups.items()):
        n = len(scores)
        avg = sum(scores) / n
        sc = sentiment_counts[(ch, cat)]
        rows.append({
            "kanal":        ch,
            "kategori":     cat,
            "yorum_sayisi": n,
            "ort_compound": round(avg, 4),
            "pozitif_oran": round(sc["pozitif"] / n, 4),
            "notr_oran":    round(sc["notr"]    / n, 4),
            "negatif_oran": round(sc["negatif"] / n, 4),
        })
    return rows


def build_zaman_seri(enriched: list[dict]) -> list[dict]:
    """Günlük ortalama compound skoru, kanal bazında."""
    daily: dict[tuple, list[float]] = defaultdict(list)

    for r in enriched:
        try:
            date_str = r["yorum_tarihi"][:10]   # YYYY-MM-DD
            key = (r["channel_name"], date_str)
            daily[key].append(float(r["compound"]))
        except (ValueError, IndexError):
            continue

    rows = []
    for (ch, date), scores in sorted(daily.items()):
        rows.append({
            "kanal":        ch,
            "tarih":        date,
            "yorum_sayisi": len(scores),
            "ort_compound": round(sum(scores) / len(scores), 4),
        })
    return rows

# ──────────────────────────────────────────────
# 4.  GRAFİKLER
# ──────────────────────────────────────────────

def fig_kanal_sentiment_bar(kanal_ozet: list[dict]) -> None:
    """Kanal bazında pozitif/nötr/negatif yığılmış bar."""
    channels = [r["kanal"] for r in kanal_ozet]
    pos  = [float(r["pozitif_oran"]) * 100 for r in kanal_ozet]
    neu  = [float(r["notr_oran"])    * 100 for r in kanal_ozet]
    neg  = [float(r["negatif_oran"]) * 100 for r in kanal_ozet]

    fig, ax = plt.subplots(figsize=(10, 5))
    x = range(len(channels))
    ax.bar(x, pos, label="Pozitif", color="#2ecc71")
    ax.bar(x, neu, bottom=pos, label="Nötr", color="#bdc3c7")
    bot = [p + n for p, n in zip(pos, neu)]
    ax.bar(x, neg, bottom=bot, label="Negatif", color="#e74c3c")

    ax.set_xticks(list(x))
    ax.set_xticklabels(channels, rotation=20, ha="right", fontsize=9)
    ax.set_ylabel("Yorum Oranı (%)")
    ax.set_title("Kanal Bazında Sentiment Dağılımı")
    ax.legend(loc="upper right")
    ax.set_ylim(0, 105)
    plt.tight_layout()
    path = FIG_DIR / "kanal_sentiment_bar.png"
    plt.savefig(path, dpi=150)
    plt.close()
    log.info("  → %s", path.name)


def fig_kanal_compound_box(enriched: list[dict]) -> None:
    """Kanal bazında compound skor kutu grafiği."""
    channel_data: dict[str, list[float]] = defaultdict(list)
    for r in enriched:
        channel_data[r["channel_name"]].append(float(r["compound"]))

    channels = sorted(channel_data.keys())
    data     = [channel_data[ch] for ch in channels]
    colors   = [CHANNEL_COLORS.get(ch, "#888888") for ch in channels]

    fig, ax = plt.subplots(figsize=(10, 5))
    bp = ax.boxplot(data, patch_artist=True, notch=False)
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    ax.set_xticklabels(channels, rotation=20, ha="right", fontsize=9)
    ax.set_ylabel("Compound Skoru")
    ax.set_title("Kanal Bazında Compound Skor Dağılımı")
    ax.axhline(0, color="gray", linestyle="--", linewidth=0.8)
    plt.tight_layout()
    path = FIG_DIR / "kanal_compound_box.png"
    plt.savefig(path, dpi=150)
    plt.close()
    log.info("  → %s", path.name)


def fig_zaman_trendi(zaman_seri: list[dict]) -> None:
    """Günlük ortalama compound — kanal başına çizgi grafik."""
    from collections import defaultdict

    ch_dates: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in zaman_seri:
        ch_dates[r["kanal"]][r["tarih"]].append(float(r["ort_compound"]))

    fig, ax = plt.subplots(figsize=(12, 5))
    for ch, date_map in sorted(ch_dates.items()):
        dates  = sorted(date_map.keys())
        scores = [date_map[d][0] for d in dates]
        dt_dates = [datetime.strptime(d, "%Y-%m-%d") for d in dates]
        color = CHANNEL_COLORS.get(ch, "#888888")
        ax.plot(dt_dates, scores, marker="o", markersize=3,
                label=ch, color=color, linewidth=1.5)

    ax.axhline(0, color="gray", linestyle="--", linewidth=0.8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    fig.autofmt_xdate()
    ax.set_ylabel("Ort. Compound Skoru")
    ax.set_title("Günlük Sentiment Trendi (28 Şubat – 29 Mart 2026)")
    ax.legend(fontsize=8)
    plt.tight_layout()
    path = FIG_DIR / "zaman_trendi.png"
    plt.savefig(path, dpi=150)
    plt.close()
    log.info("  → %s", path.name)


def fig_kategori_heatmap(kategori_ozet: list[dict]) -> None:
    """Kanal × kategori ortalama compound ısı haritası."""
    channels   = sorted({r["kanal"]    for r in kategori_ozet})
    categories = sorted({r["kategori"] for r in kategori_ozet})

    lookup = {(r["kanal"], r["kategori"]): float(r["ort_compound"])
              for r in kategori_ozet}

    matrix = [[lookup.get((ch, cat), 0.0) for cat in categories]
              for ch in channels]

    fig, ax = plt.subplots(figsize=(9, 5))
    im = ax.imshow(matrix, cmap="RdYlGn", vmin=-0.5, vmax=0.5, aspect="auto")
    plt.colorbar(im, ax=ax, label="Ort. Compound")

    ax.set_xticks(range(len(categories)))
    ax.set_yticks(range(len(channels)))
    ax.set_xticklabels(categories, rotation=30, ha="right", fontsize=9)
    ax.set_yticklabels(channels, fontsize=9)

    for i, ch in enumerate(channels):
        for j, cat in enumerate(categories):
            val = lookup.get((ch, cat), None)
            if val is not None:
                ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                        fontsize=8, color="black")

    ax.set_title("Kanal × Kategori Ortalama Sentiment")
    plt.tight_layout()
    path = FIG_DIR / "kategori_heatmap.png"
    plt.savefig(path, dpi=150)
    plt.close()
    log.info("  → %s", path.name)

# ──────────────────────────────────────────────
# 5.  ANA AKIŞ
# ──────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("Sentiment Analizi Başlıyor")
    log.info("=" * 60)

    rows     = load_clean(CLEAN_CSV)
    metadata = load_metadata(METADATA_CSV)

    # Sentiment skorla
    enriched = run_sentiment(rows)

    # Yorum bazında CSV
    sent_fields = list(enriched[0].keys())
    write_csv(RESULTS_DIR / "sentiment_yorumlar.csv", sent_fields, enriched)

    # Özet tablolar
    log.info("\nÖzet tablolar oluşturuluyor…")
    kanal_ozet    = build_kanal_ozet(enriched)
    kategori_ozet = build_kategori_ozet(enriched)
    zaman_seri    = build_zaman_seri(enriched)

    write_csv(RESULTS_DIR / "kanal_ozet.csv",
              ["kanal","yorum_sayisi","ort_compound","pozitif_oran","notr_oran","negatif_oran",
               "pozitif_n","notr_n","negatif_n"],
              kanal_ozet)
    write_csv(RESULTS_DIR / "kategori_ozet.csv",
              ["kanal","kategori","yorum_sayisi","ort_compound","pozitif_oran","notr_oran","negatif_oran"],
              kategori_ozet)
    write_csv(RESULTS_DIR / "zaman_seri.csv",
              ["kanal","tarih","yorum_sayisi","ort_compound"],
              zaman_seri)

    # Grafikler
    log.info("\nGrafikler oluşturuluyor…")
    fig_kanal_sentiment_bar(kanal_ozet)
    fig_kanal_compound_box(enriched)
    fig_zaman_trendi(zaman_seri)
    fig_kategori_heatmap(kategori_ozet)

    # Konsol özet
    log.info("\n" + "=" * 60)
    log.info("ÖZET")
    log.info("=" * 60)
    log.info("%-25s %8s %10s %10s %10s", "Kanal", "Yorum", "Pozitif%", "Nötr%", "Negatif%")
    log.info("-" * 65)
    for r in kanal_ozet:
        log.info("%-25s %8s %9.1f%% %9.1f%% %9.1f%%",
                 r["kanal"], r["yorum_sayisi"],
                 float(r["pozitif_oran"]) * 100,
                 float(r["notr_oran"])    * 100,
                 float(r["negatif_oran"]) * 100)
    log.info("=" * 60)
    log.info("Çıktılar: %s", RESULTS_DIR)


if __name__ == "__main__":
    main()
