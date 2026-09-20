# Image-to-Vector Motoru — Kısa Teknik Rapor

## 1. Yönetici özeti

Amaç, fotoğrafları değil; **logo, ikon, düz renkli grafik, Türkçe yazı konturu ve temiz line-art** görsellerini az node’lu, düzenlenebilir ve topolojik olarak doğru SVG’ye çevirmektir.

Önerilen ürün klasik bir “pixel tracer” değildir. Motor, raster görüntüyü üretmiş olabilecek en sade vektör tasarımı arayan **topoloji merkezli hibrit inverse-rendering** sistemi olacaktır:

> **We don’t trace pixels. We reconstruct design intent.**

İlk sürüm için büyük bir AI modeli gerekmez. 6 GB RTX 3060 yeterlidir; çekirdeğin çoğu CPU’da deterministik çalışabilir. Rekabet avantajı; paylaşılan sınırlar, primitive tanıma, stroke çıkarımı, global kısıtlar ve yeniden render ederek doğrulamadan gelmelidir.

## 2. Kapsam

### İlk sürüm

- 2–12 renkli logo ve ikonlar
- JPEG sıkıştırmalı veya düşük çözünürlüklü grafikler
- Şeffaf arka plan ve antialiasing
- Türkçe karakterler: `ğ, Ğ, ş, Ş, İ, ı, ç, Ç, ö, Ö, ü, Ü`
- İnce/kalın çizgi, delik, iç içe bölge ve ortak sınırlar
- Çıktı modları: **Faithful, Geometric, Minimal, Cut-ready**

### İlk sürüm dışında

Fotoğraf, fotogerçekçi gölgeleme, karmaşık gradient mesh, çok katmanlı illüstrasyon ve üretken AI ile yeniden çizim.

## 3. Önerilen motor mimarisi

```text
Raster giriş
  → renk/alpha normalizasyonu
  → palet + gürültü/JPEG modeli
  → bölge etiketleme
  → planar region/shared-boundary graph
  → subpixel sınır kestirimi
  → primitive / stroke / Bézier adayları
  → ayrık model seçimi
  → global sürekli optimizasyon
  → çok ölçekli yeniden render ve doğrulama
  → SVG/PDF export
```

### 3.1 Normalizasyon

- ICC/sRGB dönüşümü, premultiplied alpha kontrolü ve linear-light çalışma kopyası.
- Segmentasyon için OKLab/ΔE; render kaybı için linear RGBA.
- JPEG blok, ringing, blur ve antialiasing güven haritaları.
- Şeffaf girdiler farklı arka planlarda değerlendirilmelidir; beyaza gömülü tek raster yeterli değildir.

### 3.2 Bölge ve topoloji

Çekirdek veri modeli bir **planar half-edge graph** olmalıdır:

- `Region`: renk/alpha, bileşenler, delikler
- `Vertex`: junction veya subpixel köşe
- `HalfEdge`: sol/sağ bölge, tek kanonik geometri
- `Constraint`: eşmerkezlilik, paralellik, diklik, teğetlik, simetri, eşit yarıçap/genişlik

Kritik kural: Komşu iki bölgenin sınırı iki kez bağımsız fit edilmez. **Shared edge bir kez çözülür**, iki bölge ters yönlerde aynı geometriyi kullanır. Böylece gap, overlap ve farklı node dizileri engellenir. SVG export sırasında aynı eğri ters yönde çoğaltılır ve resvg/Chromium/Inkscape üzerinde seam testi yapılır.

Topoloji optimizasyondan önce sabitlenmeli; bileşen, delik ve komşuluk değişiklikleri sıradan bir yumuşak ceza değil, kontrollü hipotez değişimi olmalıdır.

### 3.3 Subpixel sınır çıkarımı

İki komşu düz renk için sınır pikseli yaklaşık olarak

`I ≈ coverage · C_left + (1 − coverage) · C_right`

şeklinde modellenir. Linear-light renkler, komşu palet renkleri ve tahmini blur/PSF kullanılarak sınırın piksel içindeki konumu kestirilir. JPEG bozulmasında tek piksellik karar yerine kısa normal profilleri ve robust loss kullanılmalıdır. Junction bölgeleri normal edge noktalarından ayrı çözülmelidir.

### 3.4 Geometri adayları

Her edge zinciri için birden fazla açıklama üretilir:

1. doğru/parça,
2. daire yayı,
3. elips,
4. dikdörtgen/rounded rectangle,
5. sabit veya değişken genişlikli stroke,
6. kübik Bézier zinciri.

Seçim yalnızca en düşük piksel hatasına göre değil, **minimum description length** yaklaşımıyla yapılır. Bir daire 20 Bézier node’undan biraz daha hatalı olsa bile daha düzenlenebilir olduğu için kazanabilmelidir.

Köşe ve segment seçimi için tek bir curvature threshold zincirine bağımlı olmak yerine interval adayları + dinamik programlama/model seçimi önerilir. Bu hem daha kararlı hem de aktif “coordinated piecewise Bézier vectorization” patent ailesinden teknik olarak ayrışmayı kolaylaştırır; yine de ticarileşmeden önce uzman FTO incelemesi gerekir.

### 3.5 Fill ve stroke dalları

- **Fill dalı:** çok renkli region graph ve ortak sınırlar.
- **Stroke dalı:** medial axis/centerline, genişlik profili, cap/join ve junction çözümü.
- Motor iki hipotezi yeniden render ederek karşılaştırır. İnce çizgiyi iki konturlu dolgu olarak çıkarmak yerine gerçek SVG stroke üretilebilir.
- Line-art topolojisi ayrı uzman dal olmalı; genel renk segmentasyonuna zorla eklenmemelidir.

### 3.6 Global optimizasyon

Önerilen amaç fonksiyonu:

`E = wr·Erender + wb·Eboundary + wc·Ecolor + ws·Esmooth + wk·Ecomplexity + wg·Econstraints`

- `Erender`: 0.5×, 1×, 2× ve 4× ölçeklerde linear-RGBA raster farkı
- `Eboundary`: simetrik contour/signed-distance hatası
- `Ecolor`: algısal renk farkı
- `Esmooth`: gereksiz curvature/twist cezası
- `Ecomplexity`: path, segment ve node maliyeti
- `Econstraints`: simetri, teğetlik, paralellik, eşit yarıçap vb.

Önce ayrık aday seçimi, sonra Ceres ile control point/renk/stroke genişliği optimizasyonu yapılmalıdır. Huber/Cauchy loss, JPEG artefaktlarına aşırı uyumu azaltır.

## 4. Teknoloji seçimi

### Hızlı prototip

- **Python:** deney, benchmark, raporlama
- **C++17:** OpenCV + Eigen + Ceres + Clipper2
- **pybind11:** Python–C++ köprüsü
- **resvg:** referans SVG rasterizasyonu ve uyumluluk testi
- **Web UI:** giriş/çıktı, node görünümü, residual heatmap, lokal yeniden işleme

GPU zorunlu değildir. İleride differentiable raster veya küçük belirsizlik modeli eklenirse 6 GB GPU yalnızca opsiyonel hızlandırıcı olur.

### Lisans özeti

- VTracer, PolyFit, PolyVectorization: MIT; baseline ve araştırma referansı olarak uygun.
- `flo_curves`: Apache-2.0; Bézier fitting için değerlendirilebilir.
- `kurbo` ve güncel `resvg`: MIT/Apache-2.0.
- OpenCV ve Ceres: Apache-2.0; Eigen: MPL-2.0; Clipper2: Boost Software License.
- **Potrace: GPL-2.0-or-later.** Kapalı ürün çekirdeğine kod/link olarak alınmamalı; yalnızca ayrı benchmark aracı veya ticari lisansla kullanılmalı.
- Ceres’te `WITH_SUITESPARSE=ON`, CHOLMOD/SPQR nedeniyle GPL/ticari yük doğurabilir; kapalı prototipte kapalı tutulmalı.

Bu bölüm hukuki görüş değildir; release öncesi dependency/SBOM ve hukuk kontrolü gerekir.

## 5. Benchmark ve başarı kriterleri

100 kaynak tasarım oluşturulmalı; aynı tasarımın farklı bozulmaları aynı split’te tutulmalıdır:

- 25 logo, 20 ikon, 20 Türkçe yazı,
- 15 JPEG/blur stresi, 10 alpha örneği, 10 line-art.

En az 60 örnek bilinen SVG ground truth’tan rasterize edilmeli; 30 örnek tamamen kilitli kör test olmalıdır. Baseline’lar: VTracer, Potrace (binary), Inkscape/Illustrator trace ve erişilebiliyorsa Vectorizer.AI.

### Ölçümler

- **Topoloji:** bileşen/delik sayısı, adjacency precision/recall, junction doğruluğu
- **Geometri:** symmetric Chamfer, Hausdorff ve corner sapması
- **Fidelity:** linear RGBA hata, SSIM; birden çok çözünürlük ve arka plan
- **Düzenlenebilirlik:** node/path sayısı, primitive recovery, simetri
- **Geçerlilik:** self-intersection, açık contour, gap/overlap, renderer farkı
- **Operasyon:** CPU süre, peak RAM, lokal düzeltme süresi
- **İnsan testi:** kör A/B tercih ve hedef düzenlemeyi tamamlama süresi

### MVP geçiş hedefleri

- Sentetik kör sette ≥ %95 topoloji doğruluğu
- Eşit veya daha iyi fidelity’de en iyi açık kaynak baseline’dan ≥ %30 az node
- Geçerli örneklerde self-intersection < %1
- 1 MP düz grafikte p95 CPU süresi ≤ 3 saniye
- Kör A/B testinde ≥ %65 tercih

Tek bir birleşik skor sonuçları saklamamalı; önce topoloji/geçerlilik kapıları, sonra fidelity–node Pareto grafiği kullanılmalıdır.

## 6. Uygulama sırası

1. **Hafta 1:** dataset, degradation generator, baseline ve resvg ölçüm harness’i.
2. **Hafta 2–3:** palet/segmentasyon, region graph, delik ve shared-edge assembly.
3. **Hafta 4:** antialias-aware subpixel boundary extractor.
4. **Hafta 5–6:** line/arc/ellipse/rounded-rect/Bézier adayları ve MDL seçimi.
5. **Hafta 7:** Ceres global optimizer ve multi-scale render-and-rank.
6. **Hafta 8:** stroke/centerline dalı, Türkçe yazı ve cut-ready doğrulamaları.
7. **Hafta 9–10:** güven skoru, lokal yeniden işleme, demo UI ve kör benchmark.

İlk dikey dilim binary logo üzerinde baştan sona çalışmalı; çok renk, stroke ve UI ancak ölçüm hattı kurulduktan sonra eklenmelidir.

## 7. Başlıca riskler

- **Yanlış topoloji:** en büyük ürün riski; confidence ve alternatif hipotez tutulmalı.
- **Noise’a aşırı uyum:** multi-scale loss + MDL + robust loss ile sınırlandırılmalı.
- **SVG renderer farkları:** en az üç renderer ile golden test yapılmalı.
- **Patent/FTO:** özellikle US10212457/US10743035/US11395011; ayrıca Adobe’nin lokal/etkileşimli tracing patentleri incelenmeli. Bu tarama yalnızca teknik ön elemedir.
- **Rakip iddiası:** “Vectorizer.AI’dan daha iyi” ancak kilitli kör sette gösterildikten sonra söylenmeli. İlk iddia, dar kapsamda daha iyi topoloji ve düzenlenebilirlik olmalıdır.

## 8. Son karar

En doğru yatırım prototipi, büyük AI modeli değil; **ortak sınır grafı + subpixel coverage + primitive/stroke hipotezleri + global render doğrulaması**dır. Bu yaklaşım dar hedef kümesinde teknik olarak savunulabilir bir üstünlük yaratır ve ileride AI’ı yalnızca belirsiz bölgelerde yardımcı modül olarak eklemeye açıktır.

## Temel kaynaklar

- VTracer: <https://github.com/visioncortex/vtracer>
- PolyFit ve makale: <https://www.cs.ubc.ca/labs/imager/tr/2020/ClipArtVectorization/>
- PolyVectorization: <https://github.com/bmpix/PolyVectorization>
- Potrace: <https://potrace.sourceforge.net/>
- Vectorizer.AI ürün beyanları: <https://vectorizer.ai/>
- Ceres bağımlılık/lisans uyarıları: <https://ceres-solver.readthedocs.io/latest/installation.html>
- Adobe lokal vectorization ailesi: <https://patents.google.com/patent/US9972073B2/en>
- Adobe interactive edge tracing: <https://patents.google.com/patent/US10685459B2/en>
- Raster image tracing: <https://patents.google.com/patent/US11257256B2/en>
- Coordinated piecewise Bézier ailesi: <https://patents.google.com/patent/US10743035B2/en>
