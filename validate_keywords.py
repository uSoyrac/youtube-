"""
Keyword Validasyon — İki Aşamalı

AŞAMA A  python3 validate_keywords.py sample
  → validation/keyword_validation_sample.csv  üretir
  → Bu dosyayı Excel'de açın, her satır için:
       manual_kategori  sütununu doldurun
       (ilk_saldir / sivil_kayip / hormuz / ateskes / alakasiz)
       manual_not sütununa varsa açıklama yazın
  → Dosyayı kaydedin

AŞAMA B  python3 validate_keywords.py score
  → Doldurduğunuz CSV'yi okur
  → Precision, Recall, F1, Cohen's Kappa hesaplar
  → validation/validation_report.csv + konsol raporu üretir
"""

import csv
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR   = Path(__file__).parent
VAL_DIR    = BASE_DIR / "validation"
VAL_DIR.mkdir(exist_ok=True)

CLASSIFIED_CSV = BASE_DIR / "videos_classified.csv"
SAMPLE_CSV     = VAL_DIR  / "keyword_validation_sample.csv"

SAMPLE_PER_CELL  = 3   # kanal × kategori kesişimi başına
SAMPLE_ALAKASIZ  = 15  # "alakasiz" etiketlileri de kontrol et
RANDOM_SEED      = 42

CATEGORIES = ["ilk_saldir", "sivil_kayip", "hormuz", "ateskes", "alakasiz"]

# ──────────────────────────────────────────────────────────────
# AŞAMA A — ÖRNEKLEM ÜRETİMİ
# ──────────────────────────────────────────────────────────────

def make_sample():
    print("Classified CSV yükleniyor…")
    rows = []
    with open(CLASSIFIED_CSV, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    print(f"  {len(rows)} video yüklendi.")

    random.seed(RANDOM_SEED)

    # kanal × kategori grupla
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        key = (r["channel_name"], r["kategori"])
        groups[key].append(r)

    sample: list[dict] = []

    # alakasiz dışındaki kategorilerden örnekle
    for (ch, cat), vlist in sorted(groups.items()):
        if cat == "alakasiz":
            continue
        n = min(SAMPLE_PER_CELL, len(vlist))
        picked = random.sample(vlist, n)
        for v in picked:
            sample.append({
                "video_id":       v["video_id"],
                "video_url":      v.get("video_url",
                                   f"https://www.youtube.com/watch?v={v['video_id']}"),
                "channel_name":   v["channel_name"],
                "auto_kategori":  v["kategori"],
                "eslesen_keyword": v.get("eslesen_keyword", ""),
                "video_title":    v["video_title"],
                "description":    v["description"][:300],
                # ── Araştırmacının dolduracağı sütunlar ──
                "manual_kategori": "",
                "manual_not":      "",
            })

    # alakasiz'dan da örnekle (keyword'ü kaçırdı mı?)
    alakasiz_pool = [r for r in rows if r["kategori"] == "alakasiz"]
    for v in random.sample(alakasiz_pool, min(SAMPLE_ALAKASIZ, len(alakasiz_pool))):
        sample.append({
            "video_id":        v["video_id"],
            "video_url":       v.get("video_url",
                                f"https://www.youtube.com/watch?v={v['video_id']}"),
            "channel_name":    v["channel_name"],
            "auto_kategori":   "alakasiz",
            "eslesen_keyword": "",
            "video_title":     v["video_title"],
            "description":     v["description"][:300],
            "manual_kategori": "",
            "manual_not":      "",
        })

    random.shuffle(sample)   # sıra bias'ını önle

    fields = [
        "video_id", "video_url", "channel_name",
        "auto_kategori", "eslesen_keyword",
        "video_title", "description",
        "manual_kategori", "manual_not",
    ]
    with open(SAMPLE_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sample)

    print(f"\n✓ Örneklem kaydedildi → {SAMPLE_CSV}")
    print(f"  Toplam: {len(sample)} video")
    print(f"  Dağılım:")
    cnt: dict[str, int] = defaultdict(int)
    for s in sample:
        cnt[s["auto_kategori"]] += 1
    for cat, n in sorted(cnt.items()):
        print(f"    {cat:<15} {n}")
    print()
    print("─" * 60)
    print("YAPILACAKLAR:")
    print(f"  1. {SAMPLE_CSV.name} dosyasını Excel veya Google Sheets'te açın")
    print("  2. Her satır için video_url'e tıklayıp videoyu izleyin/okuyun")
    print("  3. manual_kategori sütununa doğru kategoriyi yazın:")
    print("     ilk_saldir / sivil_kayip / hormuz / ateskes / alakasiz")
    print("  4. Emin değilseniz manual_not'a açıklama yazın")
    print("  5. Dosyayı kaydedin")
    print(f"  6. python3 validate_keywords.py score   komutunu çalıştırın")
    print("─" * 60)


# ──────────────────────────────────────────────────────────────
# AŞAMA B — SKOR HESAPLAMA
# ──────────────────────────────────────────────────────────────

def cohen_kappa(y_true: list[str], y_pred: list[str],
                labels: list[str]) -> float:
    """Macro Cohen's Kappa — çok sınıflı."""
    n = len(y_true)
    if n == 0:
        return 0.0

    # Gözlenen uyum
    p_o = sum(1 for a, b in zip(y_true, y_pred) if a == b) / n

    # Beklenen uyum
    p_e = 0.0
    for label in labels:
        p_true = y_true.count(label) / n
        p_pred = y_pred.count(label) / n
        p_e += p_true * p_pred

    if p_e == 1.0:
        return 1.0
    return (p_o - p_e) / (1.0 - p_e)


def score():
    if not SAMPLE_CSV.exists():
        print(f"Hata: {SAMPLE_CSV} bulunamadı. Önce 'sample' çalıştırın.")
        sys.exit(1)

    rows = []
    with open(SAMPLE_CSV, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    # Manuel kodlama boş olanları çıkar
    coded = [r for r in rows if r["manual_kategori"].strip()]
    missing = len(rows) - len(coded)
    if missing:
        print(f"Uyarı: {missing} satırda manual_kategori boş — hesaplamaya dahil edilmedi.")
    if not coded:
        print("Hata: Hiç kodlanmış satır yok. Excel'de doldurup kaydedin.")
        sys.exit(1)

    auto   = [r["auto_kategori"].strip().lower()   for r in coded]
    manual = [r["manual_kategori"].strip().lower() for r in coded]

    # Geçersiz etiket kontrolü
    valid_labels = set(CATEGORIES)
    invalid = [(i+2, r["manual_kategori"]) for i, r in enumerate(coded)
               if r["manual_kategori"].strip().lower() not in valid_labels]
    if invalid:
        print("Geçersiz etiket(ler):")
        for row_n, val in invalid:
            print(f"  Satır {row_n}: '{val}'")
        print(f"  Geçerli değerler: {', '.join(CATEGORIES)}")
        sys.exit(1)

    # ── Genel metrikler ──────────────────────────────────────
    kappa     = cohen_kappa(manual, auto, CATEGORIES)
    agreement = sum(1 for a, m in zip(auto, manual) if a == m) / len(coded)

    print("\n" + "=" * 60)
    print("KEYWORD VALIDASYON RAPORU")
    print("=" * 60)
    print(f"Kodlanan video sayısı  : {len(coded)}")
    print(f"Genel uyum oranı       : {agreement*100:.1f}%")
    print(f"Cohen's Kappa          : {kappa:.3f}  ", end="")
    if kappa >= 0.80:
        print("(Mükemmel ≥0.80) ✓")
    elif kappa >= 0.60:
        print("(İyi 0.60–0.79) ✓")
    elif kappa >= 0.40:
        print("(Orta 0.40–0.59) — keyword listesi gözden geçirilmeli")
    else:
        print("(Zayıf <0.40) ✗ — keyword listesi yeniden tasarlanmalı")

    # ── Kategori bazında precision / recall / F1 ────────────
    print("\nKATEGORİ BAZINDA METRİKLER")
    print("-" * 60)
    print(f"{'Kategori':<15} {'TP':>4} {'FP':>4} {'FN':>4} "
          f"{'Precision':>10} {'Recall':>8} {'F1':>8}")
    print("-" * 60)

    report_rows = []
    for cat in CATEGORIES:
        tp = sum(1 for a, m in zip(auto, manual) if a == cat and m == cat)
        fp = sum(1 for a, m in zip(auto, manual) if a == cat and m != cat)
        fn = sum(1 for a, m in zip(auto, manual) if a != cat and m == cat)

        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

        print(f"{cat:<15} {tp:>4} {fp:>4} {fn:>4} "
              f"{prec*100:>9.1f}% {rec*100:>7.1f}% {f1*100:>7.1f}%")

        report_rows.append({
            "kategori": cat, "TP": tp, "FP": fp, "FN": fn,
            "precision": round(prec, 4),
            "recall":    round(rec, 4),
            "f1":        round(f1, 4),
        })

    print("-" * 60)
    print(f"\nGenel uyum: {agreement*100:.1f}%  |  Cohen's Kappa: {kappa:.3f}")

    # ── Hatalı kodlananlar ──────────────────────────────────
    errors = [(r, a, m) for r, a, m in zip(coded, auto, manual) if a != m]
    if errors:
        print(f"\nUYUŞMAYAN SATIRLAR ({len(errors)} adet)")
        print("-" * 60)
        for r, a, m in errors:
            print(f"  AUTO={a:<15} MANUAL={m:<15} | {r['video_title'][:55]}")

    # ── CSV kaydet ──────────────────────────────────────────
    report_path = VAL_DIR / "validation_report.csv"
    with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
        fields = ["kategori","TP","FP","FN","precision","recall","f1"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report_rows)
        # Özet satır
        writer.writerow({
            "kategori": "GENEL",
            "TP": "", "FP": "", "FN": "",
            "precision": "",
            "recall":    "",
            "f1":        round(agreement, 4),
        })
        writer.writerow({
            "kategori": "COHEN_KAPPA",
            "TP": "", "FP": "", "FN": "",
            "precision": "", "recall": "",
            "f1": round(kappa, 4),
        })

    print(f"\n✓ Rapor kaydedildi → {report_path}")
    level = "excellent" if kappa >= 0.80 else "substantial" if kappa >= 0.60 else "moderate"
    print("\nMAKALE İÇİN KULLANILACAK CÜMLE:")
    print(
        f'  "Keyword-based categorization was validated against manual coding '
        f'of a stratified random sample (n={len(coded)}). '
        f'Inter-rater agreement yielded a Cohen\'s kappa of '
        f'kappa={kappa:.2f}, indicating {level} agreement."'
    )


# ──────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("sample", "score"):
        print("Kullanım:")
        print("  python3 validate_keywords.py sample   # örneklem üret")
        print("  python3 validate_keywords.py score    # doldurduktan sonra skoru hesapla")
        sys.exit(1)

    if sys.argv[1] == "sample":
        make_sample()
    else:
        score()
