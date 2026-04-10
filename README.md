# YouTube Iran War Comment Dataset
## "The First Thirty Days" — Academic Research Repository

**Topic:** Bottom-up securitization and epistemic practices in YouTube comments during the 2026 US-Israel-Iran War  
**Period:** February 28 – March 29, 2026  
**Channels:** CNN, BBC News, Fox News, Al Jazeera English, Iran International

---

## Repository Structure

```
youtube_research/
├── collect.py               # Data collection pipeline (YouTube API v3)
├── analyze.py               # VADER sentiment analysis + figures
├── validate_keywords.py     # Keyword validation (Cohen's Kappa)
├── build_datasets.py        # Dataset construction script
│
├── datasets/                # Research datasets (ready for analysis)
│   ├── dataset1_ana_corpus.csv        # Main corpus (n=12,351)
│   ├── dataset2_tematik_ornek.csv     # Thematic sample (n=700)
│   └── dataset3_ag_analizi.csv        # Engagement network (n=12,285)
│
├── results/                 # Sentiment analysis outputs
│   ├── sentiment_yorumlar.csv         # Per-comment VADER scores
│   ├── kanal_ozet.csv                 # Channel-level summary
│   ├── kategori_ozet.csv              # Channel x category summary
│   ├── zaman_seri.csv                 # Daily sentiment trend
│   └── figures/                       # Publication-ready figures (PNG)
│
├── validation/              # Inter-rater reliability
│   ├── keyword_validation_sample.csv  # n=67 manually coded sample
│   └── validation_report.csv          # Precision/Recall/F1/kappa
│
├── METHODOLOGY_EN.md        # Full methodology (English)
├── METHODOLOGY_TR.md        # Full methodology (Turkish)
└── requirements.txt
```

## Key Results

| Channel | n | Positive% | Neutral% | Negative% |
|---|---|---|---|---|
| Al Jazeera English | 2,784 | 35.2% | 6.6% | 58.2% |
| BBC News | 3,126 | 32.0% | 7.0% | 60.9% |
| CNN | 3,481 | 33.6% | 6.3% | 60.2% |
| Fox News | 2,894 | 37.5% | 8.3% | 54.1% |

**Keyword validation:** Cohen's Kappa k=0.665 (n=67), substantial agreement

## Setup

```bash
pip install google-api-python-client python-dotenv langdetect vaderSentiment matplotlib
cp .env.example .env   # add your YOUTUBE_API_KEY
python3 collect.py     # collect data
python3 analyze.py     # run sentiment analysis
python3 build_datasets.py  # build research datasets
```
