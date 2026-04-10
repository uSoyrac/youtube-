# Veri Toplama ve Analiz Metodolojisi

**Makale:** "İlk Otuz Gün: İran Savaşı'na İlişkin Epistemik Pratikler ve Alt-Yukarı Güvenlikleştirme"
**Veri Aralığı:** 28 Şubat 2026 – 29 Mart 2026 (30 gün)
**Analiz Yazılımı:** Python 3.9+, YouTube Data API v3, VADER SentimentIntensityAnalyzer

---

## 1. Veri Kaynağı ve Kanallar

Çalışma, uluslararası İngilizce haber yayıncılığında farklı editoryal duruşları temsil eden beş YouTube kanalını kapsamaktadır:

| Kanal | YouTube Handle | Editoryal Oryantasyon |
|---|---|---|
| CNN | @CNN | ABD liberal ana akım |
| BBC News | @BBCNews | Britanya kamu yayıncılığı |
| Fox News | @FoxNews | ABD muhafazakâr |
| Al Jazeera English | @AlJazeeraEnglish | Körfez / Güney perspektifi |
| Iran International | @IranIntl | İran muhalefet diasporası |

> **Not:** Iran International, toplam İngilizce yorum sayısının yetersizliği nedeniyle (n=66) nicel duygu karşılaştırmalarından çıkarılmıştır. Kanal Farsça ağırlıklı yayın yaptığından İngilizce yorum hacmi analitik olarak anlamlı eşiğin altında kalmıştır.

---

## 2. Video Seçimi

### 2.1. Ham Video Çekimi (Aşama 1)

YouTube Data API v3 `playlistItems.list` uç noktası kullanılarak her kanalın tüm yüklemeleri kanalın "uploads" oynatma listesi üzerinden taranmıştır. Bu yöntem, `search.list`'e kıyasla günlük kota tüketimini ~97 oranında azaltmaktadır (1 birim/sayfa → toplamda yaklaşık 430 birim/gün). Yayınlanma tarihi aralık dışına çıktığı ilk videoda tarama durdurulmuştur.

**Ham video toplam:** 28.842 video

### 2.2. İki Aşamalı Keyword Filtresi (Aşama 2)

**Aşama 2a — İran Savaşı Bağlam Kapısı:**
Video başlığı ve açıklamasında en az bir bağlam terimi bulunmayan videolar "alakasız" olarak işaretlenmiş ve sonraki aşamadan çıkarılmıştır. Bağlam listesi: *iran, iranian, tehran, khamenei, irgc, iran war, us-iran, israel-iran, trump iran, hormuz, persian gulf, isfahan, nuclear iran*.

**Aşama 2b — Tematik Kategori Atama:**
Bağlam kapısını geçen videolar dört tematik çerçeveyle eşleştirilmiştir:

| Kategori | Kavramsal Çerçeve | Örnek Keyword'ler |
|---|---|---|
| `ilk_saldir` | İlk saldırı / savaş harekatı | airstrike, missile, bombing, f-35 |
| `sivil_kayip` | Sivil kayıplar ve insani kriz | civilian, death toll, humanitarian |
| `hormuz` | Hürmüz Boğazı / enerji güvenliği | hormuz, tanker, oil price, blockade |
| `ateskes` | Ateşkes / müzakere / diplomasi | ceasefire, negotiations, peace, deal |

### 2.3. Keyword Validasyonu (Cohen's Kappa)

Otomatik sınıflandırmanın güvenilirliğini test etmek amacıyla iki aşamalı bir validasyon prosedürü uygulanmıştır:

**Örneklem:** Katmanlı rastgele örneklem (n=67; kanal × kategori kesişimi başına 3 video, "alakasız" havuzundan 15 ek video; RANDOM_SEED=42).

**Manuel Kodlama:** Her video için URL tıklanmış, başlık ve içerik incelenmiş ve yorum bölümü gözden geçirilerek manuel kategori belirlenmiştir.

**Sonuç:** Cohen's Kappa κ=0.665 (n=67) → *Önemli (substantial) uyum*, Q1 yayın standartları açısından kabul edilebilir eşik olan κ≥0.60 üzerinde.

**Yanlış Pozitifler:** Manuel inceleme sonucu 22 video, konu ile ilgisi olmayan yanlış eşleşme olarak tespit edilmiş ve `EXCLUDED_VIDEO_IDS` kümesine alınmıştır (ör. Küba elektrik kesintisi → "blockade", meningit haberi → "hospital"). Bu videolar otomatik sınıflandırmada çıkarılmıştır. Söz konusu müdahale makale metodoloji bölümünde "otomatik sınıflandırma + manuel doğrulama" olarak şeffaf biçimde raporlanmaktadır.

### 2.4. Final Video Seçimi (Aşama 3)

Her kanal × kategori kombinasyonu için en fazla yorum alan 3 video seçilmiştir (top-3 by comment count). Bu kriter, kamuoyu ilgisinin en yoğun toplandığı içerikleri önceliklendirmekte ve alt-yukarı güvenlikleştirme pratiklerinin incelenmesi için en verimli örneklem birimlerini sağlamaktadır.

**Seçilen video sayısı:** 66 video (5 kanal × 4-5 kategori × max 3 video)

---

## 3. Yorum Toplama ve Filtreleme

### 3.1. Ham Yorum Çekimi (Aşama 4)

YouTube Data API v3 `commentThreads.list` uç noktası kullanılarak her video için en fazla 500 ana (üst düzey) yorum zaman sırasına göre çekilmiştir. Yanıt yorumları (replies) API kota kısıtlaması nedeniyle ayrı olarak çekilmemiş; yanıt sayısı (`yanit_sayisi`) vekil ölçüt olarak kaydedilmiştir.

**Ham yorum toplam:** 30.678 yorum (40.214 satır; çok satırlı yorumlar nedeniyle satır sayısı farklıdır)

### 3.2. Yorum Filtreleme (Aşama 5)

Sırasıyla uygulanan filtreler:

1. **Silinmiş içerik çıkarma:** `[deleted]` veya `[removed]` içeren yorumlar çıkarıldı.
2. **Minimum uzunluk:** 15 kelimeden kısa yorumlar çıkarıldı.
3. **Dil filtresi:** `langdetect` kütüphanesi kullanılarak güven skoru ≥0.90 olan İngilizce yorumlar tutuldu.
4. **Tam eşleşme tekilleştirme:** İlk 80 karakter normalleştirilerek (küçük harf, çoklu boşluk birleştirme) hash tabanlı anlık tarama uygulandı.
5. **Bulanık eşleşme tekilleştirme:** `difflib.SequenceMatcher` ile kayan pencere algoritması (±200 komşu); `quick_ratio()` ön filtresi ve `ratio()` ≥0.90 eşiği uygulandı. Bu yöntem, bot spam'ının zaman sırası içinde kümeleneceği varsayımına dayanmakta ve O(n²) karmaşıklığını ~O(n×200)'e indirmektedir.

**Temiz yorum toplam:** 12.351 yorum

---

## 4. Duygu Analizi

Duygu analizi, Batı merkezli medya söylemi üzerine kapsamlı biçimde doğrulanmış bir kural tabanlı lexicon yöntemi olan VADER (Valence Aware Dictionary and sEntiment Reasoner; Hutto & Gilbert, 2014) ile gerçekleştirilmiştir. Compound skoru [−1, +1] aralığındadır. Sınıflandırma eşikleri:

- **Pozitif:** compound ≥ 0.05
- **Negatif:** compound ≤ −0.05
- **Nötr:** −0.05 < compound < 0.05

VADER, İngilizce sosyal medya metninde güncel transformer tabanlı modellerle karşılaştırılabilir performans sergilediği ve yorumlanabilirliği nedeniyle metodolojik şeffaflık gerektiren akademik çalışmalar için tercih edilmektedir (Ribeiro et al., 2016).

---

## 5. Araştırma Veri Setleri

Çalışmada üç ayrı veri seti oluşturulmuştur:

### Dataset 1 — Ana Corpus (`datasets/dataset1_ana_corpus.csv`)
Tüm temiz yorumları, video metadatası ve VADER duygu puanlarını içermektedir.
**n = 12.351 yorum**

### Dataset 2 — Tematik Analiz Örneği (`datasets/dataset2_tematik_ornek.csv`)
Makro desen içinde derinlemesine tematik okuma için amaçlı (purposive) örneklem. Seçim kriterleri:
- Kanal × kategori hücresi başına en fazla beğenilen 10 yorum (yüksek rezonans)
- Kanal × kategori hücresi başına en uzun yanıt zincirine sahip 10 yorum (tartışma odağı)
- Kanal × kategori hücresi başına en uzun 10 yorum (karmaşık epistemik pratikler)
- Kalan kapasite için RANDOM_SEED=42 ile rastgele katmanlı doldurma

**n = 700 yorum** (4 kanal × 5 kategori, dengeli dağılım)

### Dataset 3 — Engagement Ağı (`datasets/dataset3_ag_analizi.csv`)
Yorum düğümlerini engagement skoru ile birlikte içermektedir: `engagement_skoru = begeni_sayisi + 3 × yanit_sayisi`. Kanal × kategori kesişimlerinde epistemik "odak noktaları" tespit etmek amacıyla sıralanmıştır.
**n = 12.285 yorum** (4 ana kanal)

---

## 6. Üretilen Çıktılar

| Dosya | Açıklama |
|---|---|
| `datasets/dataset1_ana_corpus.csv` | Ana veri seti (n=12.351) |
| `datasets/dataset2_tematik_ornek.csv` | Tematik analiz örneği (n=700) |
| `datasets/dataset3_ag_analizi.csv` | Engagement ağı (n=12.285) |
| `results/sentiment_yorumlar.csv` | Yorum bazında VADER puanları |
| `results/kanal_ozet.csv` | Kanal bazında duygu özeti |
| `results/kategori_ozet.csv` | Kanal × kategori bazında özet |
| `results/zaman_seri.csv` | Günlük ortalama duygu trendi |
| `results/figures/*.png` | Yayına hazır görseller |
| `validation/keyword_validation_sample.csv` | Validasyon örneklemi (n=67) |
| `validation/validation_report.csv` | Precision / Recall / F1 / κ raporu |

---

## 7. Etik ve Sınırlılıklar

- Tüm yorumlar kamuya açık YouTube platformundan YouTube Data API v3 Kullanım Şartları çerçevesinde toplanmıştır.
- Kişisel tanımlayıcı veriler (kullanıcı adı, profil bilgisi) toplanmamıştır; yorum ID'leri pseudonimleştirme işlevi görmektedir.
- VADER, kısa ve gayri resmi metin için optimize edilmiştir; haber videosu yorumlarına uygulanması bazı özelleşmiş söylemlerde (ör. askeri terimler, ironi) sınırlı doğruluk sergileyebilir.
- Iran International'ın dışlanması, İran savaşıyla ilgili Farsça kamuoyu söylemini kapsamın dışında bırakmaktadır; bu durum bulguların yorumlanmasında göz önünde bulundurulmalıdır.

---

*Üretilme tarihi: Nisan 2026*
