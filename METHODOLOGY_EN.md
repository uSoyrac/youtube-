# Data Collection and Analysis Methodology

**Article:** "The First Thirty Days: Epistemic Practices and Bottom-Up Securitization in the Iran War"
**Data Range:** February 28, 2026 – March 29, 2026 (30 days)
**Software:** Python 3.9+, YouTube Data API v3, VADER SentimentIntensityAnalyzer

---

## 1. Data Source and Channels

The study covers five YouTube channels representing distinct editorial orientations in international English-language news broadcasting:

| Channel | YouTube Handle | Editorial Orientation |
|---|---|---|
| CNN | @CNN | U.S. liberal mainstream |
| BBC News | @BBCNews | British public broadcasting |
| Fox News | @FoxNews | U.S. conservative |
| Al Jazeera English | @AlJazeeraEnglish | Gulf/Global South perspective |
| Iran International | @IranIntl | Iranian opposition diaspora |

> **Note:** Iran International was excluded from quantitative sentiment comparisons due to insufficient English-language comment volume (n=66), attributable to the channel's predominantly Persian-language content.

---

## 2. Video Selection

### 2.1. Raw Video Retrieval (Phase 1)

All uploads from each channel were scanned via the YouTube Data API v3 `playlistItems.list` endpoint, traversing each channel's "uploads" playlist. This approach reduces daily quota consumption by ~97% compared to `search.list` (1 unit/page; approximately 430 units total per day). Scanning terminated at the first video published before the start date.

**Total raw videos:** 28,842

### 2.2. Two-Stage Keyword Filter (Phase 2)

**Stage 2a — Iran War Context Gate:**
Videos lacking at least one contextual term in their title or description were labelled "irrelevant" (*alakasiz*) and excluded from further processing. The context list comprised: *iran, iranian, tehran, khamenei, irgc, iran war, us-iran, israel-iran, trump iran, hormuz, persian gulf, isfahan, nuclear iran*.

**Stage 2b — Thematic Category Assignment:**
Videos passing the context gate were matched against four thematic frames:

| Category | Conceptual Frame | Example Keywords |
|---|---|---|
| `ilk_saldir` | Initial strike / military operation | airstrike, missile, bombing, f-35 |
| `sivil_kayip` | Civilian casualties and humanitarian crisis | civilian, death toll, humanitarian |
| `hormuz` | Strait of Hormuz / energy security | hormuz, tanker, oil price, blockade |
| `ateskes` | Ceasefire / negotiations / diplomacy | ceasefire, negotiations, peace, deal |

### 2.3. Keyword Validation (Cohen's Kappa)

A two-stage validation procedure was implemented to assess the reliability of automated classification:

**Sample:** Stratified random sample (n=67; 3 videos per channel × category intersection, plus 15 additional videos from the "irrelevant" pool; RANDOM_SEED=42).

**Manual Coding:** Each video was reviewed by clicking its URL, reading the title and description, and scanning the comment section before assigning a manual category.

**Result:** Cohen's Kappa κ=0.665 (n=67) → *Substantial agreement*, above the κ≥0.60 threshold considered acceptable for Q1 publication standards.

**False Positives:** Manual inspection identified 22 videos as topically unrelated false matches, which were added to the `EXCLUDED_VIDEO_IDS` set (e.g., Cuba electricity blackout → "blockade" keyword; meningitis news → "hospital" keyword). These videos were excluded from automated classification. This intervention is transparently reported in the article's methodology section as "automated classification with manual verification."

### 2.4. Final Video Selection (Phase 3)

For each channel × category combination, the top-3 most-commented videos were selected. This criterion prioritizes content attracting the highest concentration of public attention and provides the most analytically productive sampling units for studying bottom-up securitization practices.

**Videos selected:** 66 (5 channels × 4–5 categories × max 3 videos)

---

## 3. Comment Collection and Filtering

### 3.1. Raw Comment Retrieval (Phase 4)

Up to 500 top-level comments per video were collected via the YouTube Data API v3 `commentThreads.list` endpoint, sorted chronologically. Reply comments were not retrieved separately due to API quota constraints; reply count (`yanit_sayisi`) was retained as a proxy engagement metric.

**Total raw comments:** 30,678

### 3.2. Comment Filtering Pipeline (Phase 5)

Filters applied sequentially:

1. **Deleted content removal:** Comments containing `[deleted]` or `[removed]` were excluded.
2. **Minimum length:** Comments with fewer than 15 words were excluded.
3. **Language filter:** English-language comments were retained using `langdetect` with a confidence threshold ≥0.90.
4. **Exact-match deduplication:** Hash-based instantaneous lookup on the first 80 normalized characters (lowercase, whitespace collapsed) to remove identical copies.
5. **Fuzzy deduplication:** Sliding-window algorithm (±200 neighbors) using `difflib.SequenceMatcher`; `quick_ratio()` pre-filter with a `ratio()` ≥0.90 threshold. This approach exploits the temporal clustering behavior of bot-generated spam and reduces complexity from O(n²) to approximately O(n×200).

**Total clean comments:** 12,351

---

## 4. Sentiment Analysis

Sentiment analysis was conducted using VADER (Valence Aware Dictionary and sEntiment Reasoner; Hutto & Gilbert, 2014), a rule-based lexicon method extensively validated on Western-centric media discourse. The compound score ranges from [−1, +1]. Classification thresholds:

- **Positive:** compound ≥ 0.05
- **Negative:** compound ≤ −0.05
- **Neutral:** −0.05 < compound < 0.05

VADER was selected over transformer-based alternatives for its comparable performance on English social media text (Ribeiro et al., 2016) and for the methodological transparency it affords in academic research contexts.

---

## 5. Research Datasets

Three distinct datasets were constructed:

### Dataset 1 — Main Corpus (`datasets/dataset1_ana_corpus.csv`)
All clean comments with joined video metadata and VADER sentiment scores.
**n = 12,351 comments**

Fields: `yorum_id`, `video_id`, `video_url`, `channel_name`, `channel_id`, `kategori`, `eslesen_keyword`, `video_title`, `video_published_at`, `video_view_count`, `video_like_count`, `video_comment_count`, `yorum_text`, `yorum_tarihi`, `begeni_sayisi`, `yanit_sayisi`, `yorum_kelime_sayisi`, `compound`, `pos`, `neu`, `neg`, `sentiment`

### Dataset 2 — Thematic Analysis Sample (`datasets/dataset2_tematik_ornek.csv`)
Purposive sample for in-depth thematic reading within the macro-level patterns. Selection criteria:
- Top-10 most-liked comments per channel × category cell (high resonance)
- Top-10 by longest reply chain per channel × category cell (discussion hubs)
- Top-10 longest comments per channel × category cell (complex epistemic practices)
- Remaining capacity filled via stratified random sampling (RANDOM_SEED=42)

**n = 700 comments** (4 channels × 5 categories, balanced distribution)

### Dataset 3 — Engagement Network (`datasets/dataset3_ag_analizi.csv`)
Comment nodes ranked by engagement score: `engagement_score = likes + 3 × replies`. Designed to identify epistemic "focal points" across channel × category intersections.
**n = 12,285 comments** (4 main channels)

---

## 6. Output Files

| File | Description |
|---|---|
| `datasets/dataset1_ana_corpus.csv` | Main corpus (n=12,351) |
| `datasets/dataset2_tematik_ornek.csv` | Thematic analysis sample (n=700) |
| `datasets/dataset3_ag_analizi.csv` | Engagement network (n=12,285) |
| `results/sentiment_yorumlar.csv` | Per-comment VADER scores |
| `results/kanal_ozet.csv` | Channel-level sentiment summary |
| `results/kategori_ozet.csv` | Channel × category summary |
| `results/zaman_seri.csv` | Daily average sentiment trend |
| `results/figures/*.png` | Publication-ready figures |
| `validation/keyword_validation_sample.csv` | Validation sample (n=67) |
| `validation/validation_report.csv` | Precision / Recall / F1 / κ report |

---

## 7. Key Descriptive Statistics

| Channel | Comments | Positive% | Neutral% | Negative% | Mean Compound |
|---|---|---|---|---|---|
| Al Jazeera English | 2,784 | 35.2% | 6.6% | 58.2% | — |
| BBC News | 3,126 | 32.0% | 7.0% | 60.9% | — |
| CNN | 3,481 | 33.6% | 6.3% | 60.2% | — |
| Fox News | 2,894 | 37.5% | 8.3% | 54.1% | — |

*Iran International excluded (n=66, insufficient English-language volume)*

---

## 8. Ethical Considerations and Limitations

- All comments were collected from publicly accessible YouTube content in accordance with the YouTube Data API v3 Terms of Service.
- No personal identifying information (usernames, profile data) was collected; comment IDs serve as pseudonymous identifiers.
- VADER is optimized for short, informal text; its application to news video comments may yield reduced accuracy for specialized discourse (e.g., military terminology, sarcasm, irony).
- The exclusion of Iran International leaves Persian-language public discourse regarding the Iran War outside the scope of quantitative analysis; this should be considered when interpreting findings.
- The study captures the bottom-up dimension of securitization (audience responses) rather than elite securitizing moves; claims should be scoped accordingly.

---

### Suggested Methodological Citation

> "Keyword-based categorization was validated against manual coding of a stratified random sample (n=67). Inter-rater agreement yielded a Cohen's kappa of κ=0.67, indicating substantial agreement (Landis & Koch, 1977). Twenty-two videos identified as false positives during manual review were excluded from the corpus prior to final analysis."

---

## References

- Hutto, C.J., & Gilbert, E. (2014). VADER: A parsimonious rule-based model for sentiment analysis of social media text. *Proceedings of the Eighth International AAAI Conference on Weblogs and Social Media.*
- Landis, J.R., & Koch, G.G. (1977). The measurement of observer agreement for categorical data. *Biometrics, 33*(1), 159–174.
- Ribeiro, F.N., Araújo, M., Gonçalves, P., Gonçalves, M.A., & Benevenuto, F. (2016). SentiBench: A benchmark comparison of state-of-the-practice sentiment analysis methods. *EPJ Data Science, 5*(1), 23.

---

*Generated: April 2026*
