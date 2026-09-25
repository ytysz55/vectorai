# VectorAI Motoru — PRD, Mimari Plan ve Geliştirme Task Listesi

**Belge durumu:** Yaşayan geliştirme planı; E0–E6 tamamlandı, E7 uygulanıyor
**Belge sürümü:** 0.2
**Ana kaynak:** `motor_teknik_rapor_kisa.md`  
**Hedef ekip:** İlk aşamada 1 çekirdek geliştirici  
**Ürün aşaması:** Yatırım kanıtı → kontrollü pilot → v1.0 adayı

---

## 0. Bu belge nasıl kullanılacak?

Bu belge aynı anda dört işlev görür:

1. Ürünün neyi çözüp neyi çözmeyeceğini tanımlayan **PRD**,
2. motorun modül ve veri sözleşmelerini tanımlayan **teknik tasarım**,
3. uygulama sırasını ve bağımlılıkları tanımlayan **geliştirme planı**,
4. tamamlanma koşulları bulunan işaretlenebilir **task listesi**.

Bağlayıcı geliştirme sırası:

> **Benchmark harness → Binary vertical slice → Multicolor fill → Stroke → Global optimizer → Validator/cut-ready/observability → Lokal job API/UI → Pilot**

Bir sonraki faza yalnızca ilgili kalite kapısı geçildikten sonra başlanır. Başarısız bir kapı yeni özellik ekleyerek gizlenmez; temsil, algoritma veya kapsam yeniden değerlendirilir.

### Öncelik sınıfları

- **P0:** Bir sonraki gate veya çalışan dikey dilim için zorunlu.
- **P1:** Güvenilir pilot için zorunlu.
- **P2:** Pilot sonrasında değerlendirilecek.

### Ürün teslim seviyeleri

- **Araştırma demosu:** Seçilmiş örneklerde teknik avantajı gösterir; ürün güvenilirliği iddiası taşımaz.
- **Yatırım prototipi:** Kilitli test setinde ölçülmüş, tekrar üretilebilir karşılaştırma sunar.
- **Pilot MVP:** Gerçek kullanıcı girdilerinde hata/güven modeli ve doğrulanmış SVG üretir.
- **v1.0 adayı:** Kalite, güvenlik, lisans, FTO ve operasyon kapılarını geçmiştir.

---

## 1. Ürün özeti

VectorAI motoru, raster görüntünün dış piksel konturunu körlemesine takip etmek yerine görüntüyü üretmiş olabilecek **en sade, topolojik olarak geçerli ve düzenlenebilir vektör tasarımı** yeniden kurar.

Ana ürün vaadi:

> **We don’t trace pixels. We reconstruct design intent.**

İlk ürün fotoğraf vektörleştirici değildir. Logo, ikon, düz renkli grafik, Türkçe yazı konturu ve temiz line-art üzerinde uzmanlaşır. Rekabet avantajı büyük bir AI modelinden değil şu bileşenlerden gelir:

- antialias-aware subpixel sınır kestirimi,
- tek kanonik geometri kullanan ortak sınır grafı,
- primitive, stroke ve Bézier alternatifleri,
- topoloji değişmeden yapılan global optimizasyon,
- çok ölçekli yeniden render ve doğrulama,
- fidelity ile node sayısını birlikte değerlendiren model seçimi,
- belirsizliği saklamayan confidence ve hata modeli.

---

## 2. Problem tanımı

Logo ve ikonlar çoğu zaman yalnızca düşük çözünürlüklü PNG/JPEG olarak bulunur. Klasik tracing araçları şu sorunları üretir:

- antialiasing veya JPEG gürültüsünü gerçek geometri sanma,
- gereksiz yüzlerce node,
- daire ve doğruların düzensiz Bézier zincirlerine dönüşmesi,
- küçük deliklerin kapanması veya sahte delik oluşması,
- komşu renklerin sınırlarının ayrı fit edilmesi sonucu gap/overlap,
- ince çizgilerin çift konturlu dolguya dönüşmesi,
- simetri, teğetlik, paralellik ve eşit genişlik gibi tasarım niyetinin kaybolması,
- `İ`, `ı`, `ğ`, `ş`, `ç`, `ö`, `ü` gibi Türkçe karakterlerde diakritik veya iç boşluk kaybı,
- görsel olarak yakın olsa bile elle düzenlenmesi zor SVG.

Ürün, yalnızca raster benzerliğini değil **topoloji, geometri, sadelik ve düzenlenebilirliği** optimize etmelidir.

---

## 3. Hedef kullanıcılar ve Jobs-to-be-Done

### 3.1 Grafik tasarımcı / küçük ajans

**İş:** Müşteriden gelen kötü logoyu tekrar çizmek.  
**Başarı:** Illustrator/Inkscape içindeki elle düzeltme süresinin azalması.  
**Kritik hatalar:** Fazla node, eğri dalgalanması, simetri kaybı, yanlış harf/delik.

### 3.2 Tabela, baskı ve kesim operatörü

**İş:** PNG/JPEG logoyu fiziksel üretime uygun kapalı kontura çevirmek.  
**Başarı:** Açık yol, çift çizgi, self-intersection ve ölçü hatası olmadan kesime geçmek.  
**Kritik mod:** `Cut-ready`.

### 3.3 API/batch kullanıcısı

**İş:** Çok sayıda görseli aynı kurallarla işlemek.  
**Başarı:** Deterministik çıktı, sabit sözleşme, açık hata kodu, süre/bellek sınırı ve idempotency.

### 3.4 Kalite/araştırma mühendisi

**İş:** Algoritma varyantlarını ve baseline’ları tarafsız ölçmek.  
**Başarı:** Sürümleri sabit araçlar, kilitli test seti, run manifest ve karşılaştırılabilir raporlar.

---

## 4. Ürün hedefleri

### 4.1 P0 hedefleri

1. Binary logo/silhouette için ilk uçtan uca deterministik vertical slice’ı üretmek.
2. Yatırım prototipinde 2–12 düz renkli grafik desteğini zorunlu olarak sunmak.
3. Bileşen, delik, junction ve bölge komşuluğu topolojisini korumak.
4. Ortak sınırı çekirdek modelde yalnızca bir kez saklamak.
5. Pixel-grid yerine subpixel boundary evidence kullanmak.
6. Primitive ve kübik Bézier adaylarını fidelity–complexity dengesiyle seçmek.
7. Her sonucu manifest, validation raporu, status ve confidence ile üretmek.
8. Aynı benchmark üzerinde VTracer ve Potrace gibi baseline’larla ölçülebilir karşılaştırma yapmak.
9. Sonucu local-first web arayüzünde kaynak/çıktı/ölçüm karşılaştırmasıyla göstermek.

Binary faz nihai ürün kapsamı değildir; multicolor aşamasına geçmeden algoritmik riski izole eden zorunlu iç kilometre taşıdır.

### 4.2 P1 hedefleri

1. Fill/stroke hipotez ayrımı ve line-art centerline çıkarımı.
2. Sabit topoloji altında global continuous optimization.
3. `Faithful`, `Geometric`, `Minimal` fill profilleri ile `Stroke` modunu sertleştirmek; `Cut-ready`yi ayrıca fiziksel ölçü belirtilen opt-in hard gate/export olarak sunmak (genel dördüncü fill modu değildir).
4. Lokal yeniden işleme ve açıklanabilir hata/güven görünümü.
5. Gerçek kullanıcı girdilerinde kontrollü pilot.
6. Gerekirse aynı web arayüzünü Tauri ile masaüstü pakete dönüştürmek.

### 4.3 Başarı iddiasının sınırı

“Vectorizer.AI’dan daha iyi” ancak izinli, kilitli ve kör benchmark sonucu ile söylenebilir. İlk pazarlama iddiası şu olmalıdır:

> Logo, ikon ve yazı konturlarında topoloji ve düzenlenebilirlik odaklı vektör yeniden yapılandırma.

---

## 5. Kapsam

### 5.1 İlk sürüm kapsamı

- PNG, JPEG ve WebP.
- Binary ve 2–12 renkli düz grafikler.
- Düşük çözünürlük, antialiasing, resize, blur ve JPEG artefaktları.
- Straight veya premultiplied alpha kaynakları.
- Bileşen, delik, iç içe bölge, ortak sınır ve junction yapıları.
- Logo, ikon, Türkçe yazı konturu ve temiz line-art.
- SVG ana çıktı.
- CLI ve artifact bundle.
- Windows ve Linux için resmî desteklenen local-first dağıtım.
- Yatırım demosunda local-first web inceleme arayüzü.
- P1 fazında aynı web arayüzünde lokal yeniden işleme ve gelişmiş debug görünümleri.
- macOS ilk sürümün destek kapsamı dışındadır.

### 5.2 Kapsam dışı

- Fotoğraf ve fotogerçekçi vektör sanat.
- Karmaşık gradient mesh.
- Genel illüstrasyon katmanlarını tahmin etme.
- Görünmeyen/örtülmüş nesne parçalarını yeniden kurma.
- Büyük üretken AI ile yeniden tasarım.
- Tam vektör editörü.
- İlk sürümde kesin font geri kazanımı veya düzenlenebilir metin garantisi.
- Nakış/dikiş yolu.
- Pilot talebi doğrulanmadan DXF/EPS.
- Spot renk ve tüm baskı öncesi süreç.

Yazı girdilerinde P0/P1 sözleşmesi **glyph konturlarını korumaktır**. OCR ve font eşleme P2’dir.

---

## 6. Ürün modları

Modlar ayrı pipeline’lar değildir. Sürümlenmiş profil dosyaları üzerinden aynı adayları farklı ağırlık ve validation kurallarıyla değerlendirir.

| Mod | Ana hedef | Davranış |
| --- | --- | --- |
| `Faithful` | Raster sadakati | Kanıtlanan küçük düzensizlikleri korur; daha fazla node’a izin verir. |
| `Geometric` | Tasarım niyeti | Primitive, simetri, paralellik, teğetlik ve eşit yarıçapı tercih eder. |
| `Minimal` | Düzenlenebilirlik | Fidelity toleransı içindeki en düşük path/segment/node maliyetini seçer. |
| `Cut-ready` | Fiziksel üretim | Kapalı contour, self-intersection yokluğu, minimum boşluk ve fiziksel ölçü kurallarını zorunlu tutar. |

Her profil şunları içermelidir:

- `profile_version`,
- objective term ağırlıkları,
- fidelity toleransları,
- primitive tercihleri,
- maksimum aday/iterasyon/süre,
- validation hard/soft gate’leri,
- SVG export politikası.

Kaynak kod içine dağılmış gizli mode sabitleri bulunmamalıdır.

---

## 7. Kullanıcı akışları

### 7.1 CLI temel akışı

```bash
vectorai trace input.png \
  --mode geometric \
  --output out/job-001 \
  --seed 0
```

Üretilen bundle:

```text
out/job-001/
  result.svg
  manifest.json
  validation.json
  preview.png
  metrics.json
  debug/                 # yalnızca açıkça istenirse
```

Akış:

1. Girdi formatı, boyutu ve kaynak limitleri doğrulanır.
2. Renk/alpha normalizasyonu yapılır.
3. Reliability, palette ve topoloji hipotezleri oluşturulur.
4. Geometri/stroke adayları üretilir.
5. Aday sahneler mode profiliyle sıralanır.
6. Gerekliyse global optimizer çalışır.
7. SVG export edilir ve tekrar rasterize edilir.
8. Structural, geometric, topology ve fidelity validation çalışır.
9. Sonuç `success`, `degraded`, `needs_review`, `unsupported` veya `failed` olur.

### 7.2 Batch/API akışı

- Her işin `job_id`, `input_sha256`, `config_hash` ve `engine_build_id` alanı bulunur.
- Aynı idempotency anahtarı aynı işi tekrar başlatmaz.
- Batch içindeki tek girdi hatası diğer işleri durdurmaz.
- API iç solver parametrelerini değil, desteklenen mod ve limitleri açar.
- Çekirdek motor ağ erişimi olmadan çalışır.

### 7.3 Local-first web UI akışı

Arayüz React/TypeScript ile tarayıcıda açılır; motor tarayıcı/WASM içinde çalışmaz. Mevcut yerel FastAPI servisi Python orchestration katmanını çağırır; binary dilim native C++ CLI üzerinden yürür, multicolor/stroke yolları Python’dadır. Coarse-grained pybind11 köprüsü ancak ihtiyaç ölçülürse eklenir. Servis varsayılan olarak yalnızca `localhost` dinler; görüntü cihazdan çıkmaz. Cloud servis daha sonra ayrı güvenlik kararıyla aynı API sözleşmesini kullanabilir; masaüstü paket gerekirse Tauri ayrıca değerlendirilir.

**P0 yatırım demosu:**

1. Dosya ve mod seçimi.
2. Kaynak, sonuç ve baseline karşılaştırması.
3. Temel node/path ve kalite metrikleri.
4. Confidence/warning özeti.
5. SVG, manifest ve rapor indirme.

**P1 tam inceleme akışı:**

1. Region graph, shared edge ve residual heatmap görünümü.
2. Bir bölge/edge seçerek lokal mod veya constraint uygulama.
3. Etkilenen subgraph’ın yeniden işlenmesi.
4. Tüm global validation’ın yeniden çalışması.

---

## 8. Fonksiyonel gereksinimler

### 8.1 P0 — Yatırım prototipi

| ID | Gereksinim | Kabul özeti |
| --- | --- | --- |
| FR-001 | Güvenli raster decode | Desteklenmeyen/bozuk/aşırı büyük girdiler typed error üretir. |
| FR-002 | Renk ve alpha normalizasyonu | İç temsil straight-alpha linear RGBA; segmentasyon OKLab kullanır. |
| FR-003 | Reliability analizi | JPEG/blur/AA/noise haritaları stage artifact olarak üretilebilir. |
| FR-004 | Binary segmentasyon | Component ve hole ground truth ile karşılaştırılabilir. |
| FR-005 | Half-edge region graph | Tüm graph invariant’ları her stage sınırında doğrulanır. |
| FR-006 | Shared boundary | İki komşu region aynı canonical geometry’yi ters yönde kullanır. |
| FR-007 | Subpixel boundary | Edge evidence konum, normal, covariance ve residual döndürür. |
| FR-008 | Line/Bézier adayları | Her edge interval’i en az bir feasible adayla kapsanır. |
| FR-009 | MDL/model seçimi | Fidelity, topology, complexity ve constraint terimleri raporlanır. |
| FR-010 | Kanonik SVG | Stabil sıra/yön/sayı formatı; raster embed ve harici URL yok. |
| FR-011 | Render doğrulama | Sabit resvg sürümüyle çok ölçekli yeniden render yapılır. |
| FR-012 | Hata/güven modeli | Final status, warning, fallback ve confidence bileşenleri bulunur. |
| FR-013 | Benchmark runner | Aynı manifest ile engine ve baseline’lar karşılaştırılır. |
| FR-014 | Türkçe kontur testleri | Diakritik, nokta ve counter kaybı ayrı failure olarak raporlanır. |
| FR-015 | 2–12 renk palette/segmentation | Region ve adjacency metrikleri üretilir. |
| FR-016 | Multicolor junction | Diagonal ve çok bölgeli junction alternatifleri yönetilir. |
| FR-017 | Primitive recovery | Line/arc/circle/ellipse/rectangle/rounded-rect adayları desteklenir. |
| FR-018 | Local-first web demo | Upload, mod, before/after, metrik ve artifact indirme sunulur. |

### 8.2 P1 — Pilot MVP

| ID | Gereksinim | Kabul özeti |
| --- | --- | --- |
| FR-104 | Stroke branch | Centerline, width, cap, join ve junction açıklaması üretir. |
| FR-105 | Top-K scene hypotheses | Aday skor farkı ve belirsizlik saklanır. |
| FR-106 | Global optimizer | Topoloji immutable kalırken geometri/renk/width önce solver-independent deterministik backend ile optimize edilir; Gate G4 değer/runtime sonucuna göre Ceres production backend’e taşınır. |
| FR-107 | Multi-background validation | Alpha siyah, beyaz, transparan ve checkerboard üzerinde ölçülür. |
| FR-108 | Cut-ready | Açık/duplicate/self-intersecting contour hard fail olur. |
| FR-109 | Lokal yeniden işleme | Etkilenen graph bölümü invalidation sözleşmesine göre yenilenir. |
| FR-110 | Web review UI | Source/result/nodes/regions/residual/confidence gösterilir. |

### 8.3 P2 — Pilot sonrası

- OCR destekli metin alternatifi.
- Font eşleme.
- Öğrenilmiş candidate ranking.
- Küçük boundary/corner refinement modeli.
- İzinli kullanıcı düzeltmelerinden active learning.
- Talebe göre PDF/DXF/EPS genişletmesi.

---

## 9. Fonksiyonel olmayan gereksinimler

### 9.1 Performans

- 1 MP düz grafikte warm-run hedefi: **p95 ≤ 3 saniye CPU**.
- Stroke/global optimizer ağır yolu için başlangıç hedefi: **p95 ≤ 20 saniye**.
- Decode, normalize, segmentation, graph, fitting, optimization, validation ve export süreleri ayrı ölçülür.
- Peak RSS, region/edge/candidate sayısı ve solver iteration sayısı manifest’e yazılır.
- Girdi pikseli, region sayısı, edge sayısı, candidate sayısı, süre ve bellek için sert limit bulunur.
- Performans hedefleri referans makine tanımı olmadan raporlanmaz.

### 9.2 Determinizm

Aynı input byte dizisi, engine build’i, dependency sürümleri, profil, seed, thread policy ve numerik politika için aynı platformda kanonik SVG byte’ları ve manifest deterministik olmalıdır.

Kurallar:

- stabil ID ve sort,
- açık tie-break sırası,
- sabit seed,
- locale-independent sayı formatı,
- unordered container iteration’a bağlı karar vermeme,
- deterministik reduction,
- kanonik path başlangıç noktası ve yönü,
- profil ve quantization sürümünü manifest’e yazma.

Platformlar arası sözleşme ADR-008 ile belirlenene kadar byte eşitliği değil geometrik/raster tolerans eşitliği aranır.

### 9.3 Dayanıklılık ve güvenlik

- Decode bomb ve aşırı component/candidate üretimi engellenir.
- Harici baseline/renderer process’leri timeout ve kaynak sınırıyla çalışır.
- SVG parser’da script, harici entity, harici URL ve ağ erişimi kapalıdır.
- Hatalı girdi crash veya sessiz kısmi başarı üretmez.
- Fuzz crash’leri kalıcı regression fixture olur.

### 9.4 Uyumluluk

- Sınırlı ve sürümlenmiş SVG 2 alt kümesi.
- Temel öğeler: path, fill, stroke, basit group/transform.
- Script, `foreignObject`, filter ve raster `<image>` yok.
- resvg her PR’da; Chromium ve Inkscape gecelik/release testinde.

### 9.5 Gizlilik

- Telemetry varsayılan olarak kapalı/lokal.
- Kaynak görüntü, OCR metni veya tam path koordinatları varsayılan loga yazılmaz.
- Ürün işleme izni ile benchmark/eğitim izni ayrıdır.
- Debug artifact yükleme açık opt-in gerektirir.

---

## 10. Mimari ilkeler

1. **Topology first:** Topoloji, continuous optimizer’ın serbest değişkeni değildir.
2. **Shared once:** Ortak sınır tek canonical geometri olarak saklanır.
3. **Hypotheses, not premature certainty:** Belirsiz junction veya fill/stroke kararında alternatif tutulur.
4. **Primitive before generic curve:** Primitive yeterliyse daha serbest Bézier zinciri seçilmez.
5. **Render to verify:** Her sonuç yeniden rasterize edilip ölçülür.
6. **Complexity is a metric:** Node/path sayısı yalnızca UI istatistiği değil objective terimidir.
7. **Determinism by construction:** Test sonunda eklenen özellik değil temel sözleşmedir.
8. **Explain degradation:** Fallback ve düşük güven gizlenmez.
9. **Benchmark before optimization:** Ölçüm hattı olmadan algoritma “iyileştirilmez”.
10. **AI optional:** Öğrenilmiş bileşenler deterministik çekirdeğin alternatifi değil, ileride aday/güven yardımcısıdır.

---

## 11. Önerilen repository yapısı

```text
vectorai/
  CMakeLists.txt
  CMakePresets.json
  pyproject.toml
  vcpkg.json
  README.md
  docs/
    prd/
    adr/
    architecture/
    legal/
  schemas/
    engine-config.schema.json
    run-manifest.schema.json
    validation-report.schema.json
    benchmark-record.schema.json
  cpp/
    include/vectorai/
    src/
      core/
      image/
      segmentation/
      topology/
      boundary/
      candidates/
      stroke/
      selection/
      optimize/
      render/
      export/
      validate/
    tests/
    fuzz/
    benchmarks/
  python/
    vectorai_cli/
    vectorai_bench/
    vectorai_bindings/
    tests/
  apps/
    api/
    web/
  datasets/
    manifests/
    splits/
    licenses/
  benchmark/
    baselines/
    configs/
    goldens/
    reports/
  tools/
    dataset/
    degradation/
    inspect/
  third_party/
    notices/
```

Büyük raster, baseline binary ve üretilmiş benchmark artifact’leri Git’e alınmaz. Hash’li yerel/uzak artifact store kullanılır.

---

## 12. Teknoloji yığını

### 12.1 Çekirdek

- **C++17:** motor.
- **CMake + CMakePresets:** build.
- **vcpkg manifest ve baseline:** native dependency pinleme.
- **OpenCV:** ilk decode/image processing/segmentasyon.
- **Eigen:** lineer cebir.
- **Ceres:** continuous optimization; `WITH_SUITESPARSE=OFF`.
- **Clipper2:** polygon işlemleri ve cut-ready kontrolleri.
- **pybind11:** coarse-grained motor köprüsü.

### 12.2 Orkestrasyon

- **Python 3.12 + uv:** CLI, benchmark, dataset ve raporlama.
- **Pydantic + JSON Schema:** config/manifest/report sözleşmeleri.
- **pytest + Hypothesis:** Python testleri.
- **Catch2:** C++ unit/integration.
- **libFuzzer + ASan/UBSan:** parser/graph fuzzing.

### 12.3 Renderer ve uygulama

- **Pinned resvg CLI:** birincil referans rasterizer.
- **Chromium + Inkscape:** bağımsız uyumluluk oracle’ı.
- **FastAPI:** P0’da yalnızca localhost’a açılan ince demo API’si; P1’de tam job servisi.
- **React + TypeScript:** P0 karşılaştırma/indirme arayüzü; P1 gelişmiş inceleme ve lokal düzeltme.
- **Tauri:** Yalnızca gerçek masaüstü dağıtımı kanıtlanırsa aynı web UI için P2 paketleyici.
- **Electron ve browser/WASM motoru:** İlk sürümde kullanılmaz.

Pybind sınırı piksel veya edge seviyesinde çağrı üretmemelidir. Tercih edilen dış API:

```text
run(request, input_bytes) -> artifact_bundle
```

---

## 13. Koordinat, renk ve numerik sözleşmeleri

### 13.1 Koordinatlar

Önerilen başlangıç kararı:

- İç geometri `double` piksel uzayında çalışır.
- Sol üst köşe `(0, 0)`, sağ alt `(width, height)`.
- Piksel merkezi `(x + 0.5, y + 0.5)`.
- Y ekseni aşağı yönlüdür; SVG `viewBox="0 0 width height"` ile aynıdır.
- Optimizer conditioning için parametreler gerektiğinde görüntü diyagonaline normalize edilir; export öncesi piksel uzayına dönülür.
- Bütün distance metrikleri ham piksel yanında görüntü diyagonaline normalize değer de raporlar.

Epsilon ve quantization değerleri benchmark ile ADR-011’de kesinleştirilir. Shared geometry export sırasında bir kez formatlanıp iki yönde aynı değerlerden oluşturulur.

### 13.2 Renk

- Decode sonucu kaynak profile metadata’sı korunur.
- İç render/fidelity temsili: straight-alpha, linear-light RGBA.
- Segmentasyon/palette temsili: OKLab ve gerektiğinde ΔE.
- Non-sRGB ICC desteği ADR-002 ile kesinleşene kadar ya güvenli dönüşüm yapılır ya `degraded/unsupported` döner; sessizce sRGB varsayılmaz.
- Alpha metriği renk metriğinden ayrı raporlanır.

### 13.3 Numerik hata

- Non-finite değer anında typed internal error oluşturur.
- Her primitive parametresi fiziksel bound taşır.
- Zero-length edge, negatif radius/width ve singular transform yasaktır.
- Objective terimleri boyutsuz/normalize edilmiş olmalıdır; ham büyüklüğü en yüksek terim diğerlerini tesadüfen bastıramaz.

---

## 14. Dış API ve temel veri sözleşmeleri

### 14.1 RunRequest

```text
RunRequest
  input_bytes | input_uri(local only)
  input_media_type
  mode_profile
  engine_config_version
  seed
  resource_limits
  debug_artifact_policy
  requested_outputs
```

### 14.2 ArtifactBundle

```text
ArtifactBundle
  status
  svg
  optional_pdf
  preview_renders[]
  manifest
  validation_report
  metric_summary
  warnings[]
  optional_debug_artifacts[]
```

### 14.3 Ortak stage metadata

Her stage çıktısında:

- `schema_version`,
- stabil entity ID’leri,
- parent artifact hash,
- coordinate/color space,
- config/profile hash,
- warnings,
- stage duration,
- determinism seed,
- confidence evidence,
- artifact hash

bulunur.

### 14.4 Pipeline fonksiyon sınırları

```text
decode(InputBytes) -> SourceImage
normalize(SourceImage, ColorPolicy) -> NormalizedImage
analyzeReliability(NormalizedImage) -> ReliabilityMap
estimatePalette(NormalizedImage, ReliabilityMap) -> PaletteHypotheses
segment(NormalizedImage, PaletteHypothesis) -> LabelHypotheses
buildRegionGraph(LabelHypothesis) -> RegionGraph
estimateBoundaries(RegionGraph, NormalizedImage) -> BoundaryEvidence
buildFillCandidates(RegionGraph, BoundaryEvidence) -> CandidateSet
buildStrokeCandidates(...) -> StrokeCandidateSet
selectModels(...) -> SceneHypotheses
optimize(SceneHypothesis) -> OptimizedScene
renderAndRank(SceneHypotheses) -> RankedScenes
exportSvg(Scene) -> SvgArtifact
validate(Scene, SvgArtifact, Source) -> ValidationReport
```

Dış sınırlarda `Result<T, EngineError>` benzeri typed sonuç kullanılmalıdır. Exception süreç sınırını geçmemelidir.

---

## 15. Pipeline modülleri

### 15.1 Decode ve normalize

**Girdi:** raster byte dizisi.  
**Çıktı:** `SourceImage`, `NormalizedImage`, source hash ve metadata.

Sorumluluklar:

- format doğrulama,
- boyut ve decode budget,
- orientation,
- alpha semantiği,
- sRGB/ICC politikası,
- premultiplied → straight alpha dönüşümü,
- linear RGBA ve OKLab çalışma kopyaları.

### 15.2 Reliability analysis

Piksel veya tile başına şu kanıtları üretir:

- JPEG block/ringing olasılığı,
- blur/edge-spread tahmini,
- antialias evidence,
- alpha belirsizliği,
- saturated/low-contrast alan,
- noise/outlier ağırlığı.

Reliability map; segmentasyon, subpixel fit ve render loss ağırlıklandırmasında kullanılır.

### 15.3 Palette ve segmentasyon

- Palette sayısı sabit değil; 1–12 aralığında hipotezlenir.
- Renk uzaklığı OKLab’da, render doğrulaması linear RGBA’da yapılır.
- Spatial regularization küçük JPEG renk varyasyonlarını tek region altında toplar.
- Small component otomatik silinmez; hole/component topology etkisi kontrol edilir.
- Label hipotezleri ve skor marjı saklanır.

### 15.4 Region graph

Half-edge tabanlı planar subdivision oluşturur. Rasterın dışı özel `OuterFace` bölgesidir. Görünmeyen katman geometrisi tahmin edilmez.

### 15.5 Boundary evidence

Komşu renkler için temel model:

```text
I ≈ alpha · (coverage · C_left + (1 - coverage) · C_right)
```

Her canonical edge için:

- subpixel sample noktaları,
- normal/tangent,
- covariance veya güven interval’i,
- source support,
- blur/PSF tahmini,
- robust residual,
- junction exclusion mask

üretilir.

Tek piksel yerine edge normalinde kısa profiller kullanılır. Junction çevresi ayrı estimator ile ele alınır.

### 15.6 Candidate generation

Her aday şu alanları taşır:

- type ve version,
- kapsadığı edge interval’i,
- parametre ve bound’lar,
- degrees of freedom,
- endpoint/tangent koşulları,
- support/residual,
- complexity cost,
- hard constraint uygunluğu,
- confidence,
- deterministic tie-break key.

Fill adayları:

1. line,
2. circular arc,
3. circle,
4. ellipse/elliptical arc,
5. rectangle,
6. rounded rectangle,
7. cubic Bézier,
8. bounded cubic chain.

### 15.7 Stroke branch

- line-art routing evidence,
- skeleton/medial axis,
- centerline graph,
- local width profile,
- constant/variable width,
- butt/round/square cap,
- miter/round/bevel join,
- T/X junction,
- kısa spur temizliği,
- closed stroke ile filled ring ayrımı.

Fill ve stroke hipotezleri aynı render/topology/complexity çerçevesinde karşılaştırılır.

### 15.8 Ayrık model seçimi

Başlangıç objective’i:

```text
E_select =
  wr * E_render_proxy
+ wb * E_boundary
+ wc * E_color
+ wk * E_complexity
+ wg * E_constraints
+ wt * E_topology_risk
```

- Edge interval’lerinde bounded dynamic programming.
- Junction ve region kombinasyonlarında bounded beam search; gerekirse küçük MILP spike’ı.
- En az top-K scene hypothesis.
- Tie-break: hard validity → düşük topology risk → düşük DOF → primitive önceliği → stabil ID.

Tek curvature threshold tabanlı koordineli segmentasyon zinciri temel tasarım yapılmamalıdır. Solver ve patent etkisi ADR-007/FTO kapsamında değerlendirilir.

### 15.9 Global optimizer

Topoloji sabitlendikten sonra Ceres şu değişkenleri optimize edebilir:

- vertex/control point,
- primitive merkezi, radius ve axis,
- tangent parametreleri,
- region color/alpha,
- stroke width profile,
- symmetry axis.

Hard constraints:

- shared endpoint equality,
- twin/shared geometry identity,
- cycle closure,
- pozitif radius/width,
- component/hole/adjacency değişmemesi.

Soft constraints:

- tangent continuity,
- parallel/perpendicular,
- symmetry,
- equal radius/width,
- curvature smoothness.

Optimizer başarısız olduğunda pre-optimization scene yalnızca tüm hard validation’ları geçiyorsa `degraded` fallback olabilir. Sebep manifest’e yazılır.

### 15.10 Render-and-rank

- Hızlı iç boundary/coverage evaluator.
- Pinned resvg final oracle.
- 0.5×, 1×, 2× ve 4× render.
- Alpha için transparan, siyah, beyaz ve checkerboard arka plan.
- Renderer disagreement kontrolü.

Harici resvg, Ceres’in her iterasyonunda çağrılmamalıdır. Analytic/differentiable iç renderer ihtiyacı ayrı spike’tır.

---

## 16. Half-edge graph veri modeli ve invariant’lar

### 16.1 Temel varlıklar

#### Region

- ID,
- linear RGBA/OKLab istatistiği,
- foreground/outer-face türü,
- component/hole cycle’ları,
- area ve bounding box,
- confidence.

#### Vertex

- subpixel koordinat,
- incident half-edge’ler,
- junction sınıfı,
- covariance/confidence,
- corner/constraint referansı.

#### HalfEdge

- `origin`, `twin`, `next`, `prev`,
- `left_region`, dolaylı `right_region`,
- tek `CanonicalGeometry` referansı,
- forward/reverse yön,
- source support ve reliability.

#### Constraint

- parallel,
- perpendicular,
- tangent,
- equal radius/width,
- concentric,
- symmetry,
- endpoint coincidence,
- hard/soft ve confidence.

### 16.2 Zorunlu invariant’lar

1. Her half-edge’in tam bir twin’i vardır.
2. `twin(twin(e)) == e`.
3. `next/prev` karşılıklıdır.
4. Her edge iki region ayırır; dış taraf `OuterFace` olabilir.
5. Canonical geometry yalnızca bir kez saklanır.
6. Twin aynı geometry’yi ters yönde kullanır.
7. Region boundary cycle’ları kapalıdır.
8. Outer ve hole cycle yönleri kanoniktir.
9. Vertex çevresindeki incidence sırası planardır.
10. İzin verilmeyen edge crossing yoktur.
11. Zero-length edge ve ardışık duplicate vertex yoktur.
12. Euler karakteristiği component/hole sayısıyla uyumludur.
13. Junction valence label neighborhood ile uyumludur.
14. Export edilen komşu path’ler aynı shared curve parametrelerinden üretilir.
15. Continuous optimizer connectivity veya hole sayısını değiştiremez.

2×2 checkerboard ve diagonal temas gibi belirsiz raster bağlantıları sessizce tek karara çevrilmez; alternatif topology hypothesis oluşturulur.

---

## 17. SVG export sözleşmesi

- Stabil element/path sırası.
- Stabil ID.
- Locale-independent numeric serialization.
- Kanonik cycle yönü ve başlangıç noktası.
- Shared geometry iki path’e aynı formatlanmış parametrelerden ters yönde yazılır.
- `fill-rule`, opacity, `stroke-linecap` ve `stroke-linejoin` açıkça belirtilir.
- Gereksiz group/transform nesting yoktur.
- Raster `<image>`, script, harici URL, font veya filter bağımlılığı yoktur.
- Varsayılan `viewBox` kaynak piksel koordinatıdır.
- Export profile ve serializer version manifest’e yazılır.

### 17.1 Validation seviyeleri

1. XML/schema ve yasak öğeler.
2. Half-edge/topology invariant’ları.
3. Self-intersection, open contour, duplicate edge, gap/overlap.
4. Cut-ready minimum segment/gap/closure/ölçü.
5. resvg/Chromium/Inkscape renderer agreement.
6. Multi-scale fidelity.
7. Node/path/primitive editability.
8. Türkçe diakritik, nokta ve counter koruması.

[ADR-009](adr/ADR-009-pdf-export-scope.md) tamamlandı: PDF için bağımsız path/ölçü/renderer kanıtı bulunmadığından SVG tek bağlayıcı çıktı formatıdır.

---

## 18. Hata, warning ve confidence modeli

### 18.1 Final statüler

- `success`: Tüm hard gate’ler geçti.
- `degraded`: Güvenli fallback kullanıldı; açıkça raporlandı.
- `needs_review`: Geçerli çıktı var fakat model/topoloji belirsizliği yüksek.
- `unsupported`: Girdi kapsam dışı.
- `failed`: Geçerli çıktı üretilemedi.

### 18.2 Hata kodları

- `UNSUPPORTED_INPUT`
- `DECODE_ERROR`
- `RESOURCE_LIMIT`
- `INVALID_COLOR_PROFILE`
- `AMBIGUOUS_ALPHA`
- `PALETTE_AMBIGUOUS`
- `TOPOLOGY_AMBIGUOUS`
- `NON_MANIFOLD_GRAPH`
- `INSUFFICIENT_BOUNDARY_EVIDENCE`
- `NO_FEASIBLE_CANDIDATE`
- `STROKE_AMBIGUOUS`
- `OPTIMIZER_DIVERGED`
- `EXPORT_FAILED`
- `VALIDATION_FAILED`
- `RENDERER_DISAGREEMENT`
- `INTERNAL_INVARIANT_VIOLATION`

Her hata `stage`, ilgili entity ID’leri, kullanıcı mesajı, debug bağlamı ve retryability taşır.

### 18.3 Confidence bileşenleri

- palette separation,
- topology hypothesis margin,
- boundary evidence,
- candidate score margin,
- optimizer convergence,
- renderer agreement,
- validation sonuçları.

Kalibre edilene kadar yüzde olasılık kullanılmaz. İlk sürüm `high/medium/low` ve bileşen skorları verir. Pilot verisi sonrasında reliability diagram ve ECE ile kalibrasyon yapılır.

---

## 19. Benchmark planı

### 19.1 Veri modeli

- `DesignFamily`: Aynı tasarımın bütün varyantlarını gruplayan kimlik.
- `SourceVector`: SVG hash, provenance, lisans, renderer.
- `SourceRaster`: İzinli gerçek kaynak veya sentetik render.
- `Variant`: Resolution, JPEG, blur, resize, alpha ve seed.
- `GroundTruth`: Region, component, hole, adjacency, corner, primitive, centerline, width.
- `BenchmarkCase`: Primary class, tags ve split.
- `EngineRun`: Build/config/hardware/seed.
- `CandidateArtifact`: SVG, render, graph ve validation.
- `MetricRecord`: Metric adı, sürümü, değeri ve validity.
- `HumanEvaluation`: Kör atama, tercih, süre ve failure reason.

Aynı design veya font family farklı split’lere giremez.

### 19.2 İlk 100 kaynak tasarım

- 25 logo,
- 20 ikon,
- 20 Türkçe yazı,
- 15 JPEG/blur stress tasarımı,
- 10 alpha odaklı tasarım,
- 10 line-art.

Split:

- 50 development,
- 20 validation,
- 30 locked blind test.

En az 60 tasarım bilinen SVG ground truth’tan üretilir. Varyantlar 100 tasarım sayısına dahil değildir.

### 19.3 Degradation tier’ları

- **T0:** Temiz referans render.
- **T1:** Düşük çözünürlük + standart antialiasing.
- **T2:** JPEG/resize/blur.
- **T3:** JPEG + resize + blur + alpha/background birleşimi.

Degradation generator seed, renderer sürümü ve tüm parametreleri manifest’e yazar.

### 19.4 Baseline’lar

- VTracer — sürüm/preset sabit.
- Potrace — yalnızca binary, ayrı process ve lisans notuyla.
- Inkscape Trace Bitmap.
- Illustrator Image Trace — manuel, sürüm ve preset kayıtlı.
- Vectorizer.AI — yalnızca kullanım/benchmark izni uygunsa.
- İç ablation: polygon-only, Bézier-only, no-subpixel, no-shared-edge, no-optimizer.

Baseline başarısızlığı ortalama skorda kaybolmaz; failure rate ayrıca raporlanır.

---

## 20. Metrikler ve kalite kapıları

### 20.1 Topoloji

- exact component/hole match,
- adjacency precision/recall/F1,
- junction valence/type accuracy,
- Euler characteristic match,
- stroke graph connectivity.

### 20.2 Geometri

- görüntü diyagonaline normalize symmetric Chamfer,
- Hausdorff ve p95 contour distance,
- corner localization,
- primitive parameter error,
- centerline/width profile error.

### 20.3 Fidelity

- linear RGBA MAE/RMSE,
- alpha ayrı hata,
- SSIM,
- çok ölçekli render,
- siyah/beyaz/checkerboard composite.

### 20.4 Düzenlenebilirlik

- anchor/node,
- path ve segment sayısı,
- primitive recovery precision/recall,
- symmetry/constraint recovery,
- kör edit task tamamlama süresi.

### 20.5 Geçerlilik ve operasyon

- self-intersection,
- open/duplicate contour,
- gap/overlap,
- yasak SVG öğesi,
- renderer disagreement,
- stage/total runtime,
- peak RAM,
- candidate/iteration sayısı,
- timeout/failure/fallback oranı.

### 20.6 Gate sırası

Tek birleşik skor kullanılmaz:

1. Parse ve güvenlik.
2. Geometri geçerliliği.
3. Topoloji doğruluğu.
4. Fidelity eşiği.
5. Fidelity–node Pareto.
6. Performans.
7. İnsan tercihi ve edit süresi.

### 20.7 Pilot hedefleri

- Sentetik locked sette ≥ %95 exact topology.
- Eşit veya daha iyi fidelity’de en güçlü uygun açık kaynak baseline’dan ≥ %30 az node.
- Geçerli örneklerde self-intersection < %1.
- Test SVG’lerinde %100 parse ve sıfır raster embedding.
- 1 MP düz grafikte p95 ≤ 3 saniye.
- Kör A/B testinde ≥ %65 tercih.
- `Cut-ready` kabul edilen çıktılarda sıfır açık/duplicate contour.
- Türkçe kritik karakter hataları ayrı gate; genel ortalama içinde gizlenmez.

---

## 21. Test stratejisi

### 21.1 Unit test

- Renk/alpha dönüşümü.
- Normal profile ve robust fitting.
- Line/arc/ellipse/Bézier matematiği.
- Half-edge işlemleri.
- Cycle/hole orientation.
- Objective terimleri.
- Kanonik SVG serialization.
- Hata/status mapping.

### 21.2 Property test

- `twin(twin(e)) == e`.
- Cycle reversal aynı geometrik alanı verir.
- Translation/scale normalize metriği değiştirmez.
- Export → parse → export idempotenttir.
- Palette label permutation render sonucunu değiştirmez.
- Twin edge’ler aynı canonical geometry’yi kullanır.
- Optimizer hard invariant’ları bozamaz.
- Aynı seed aynı graph/candidate sırasını üretir.

### 21.3 Integration test

- PNG/JPEG/WebP → SVG.
- Alpha ve farklı background.
- Hole/nested region.
- Diagonal junction.
- Türkçe karakter fixtures.
- Fill/stroke arbitration.
- Optimizer fallback.
- Renderer disagreement.

### 21.4 Golden test

Her golden paket:

- input hash,
- config/profile,
- canonical SVG,
- graph summary,
- validation report,
- reference render,
- metric tolerance

içerir. Aynı platformda byte-level SVG; platformlar arasında geometry/raster tolerance uygulanır.

### 21.5 Fuzzing

- Raster decoder sınırı.
- SVG parse/export round-trip.
- Half-edge mutation.
- Rastgele planar label grid.
- Degenerate primitive/Bézier.
- Optimizer NaN/Inf ve aşırı parametreler.

### 21.6 CI

#### Her PR

- Windows/Linux debug ve release build,
- unit/property/integration,
- iki kez run determinism kontrolü,
- küçük benchmark smoke,
- resvg golden,
- dependency/license scan.

#### Gecelik

- ASan/UBSan,
- fuzz corpus,
- Chromium/Inkscape renderer matrix,
- performans regression,
- orta benchmark.

#### Release

- locked benchmark,
- SBOM ve notice paketi,
- FTO checkpoint,
- artifact signing,
- manifest/schema validation.

---

## 22. Logging, telemetry ve tekrar üretilebilirlik

### 22.1 Structured log

JSONL event alanları:

- wall-clock timestamp ve monotonic duration,
- job/stage/entity ID,
- severity ve stable event code,
- region/edge/candidate sayıları,
- stage timing,
- confidence bileşenleri,
- fallback ve validation sonucu.

### 22.2 Run manifest

- input SHA-256, byte boyutu, media type,
- engine semver ve commit/build ID,
- compiler/build flags,
- dependency/renderer sürümleri,
- config/profile hash,
- random seed,
- thread/determinism policy,
- OS/CPU/GPU,
- stage süreleri ve peak RAM,
- topology/candidate/optimizer özeti,
- warning/fallback/final status,
- SVG/render/report hash’leri,
- schema/metric sürümleri,
- veri provenance/lisans referansı.

---

## 23. Lisans ve patent korumaları

- Potrace GPL kodu kapalı motorla link edilmez veya kopyalanmaz; benchmark ayrı process olarak ve dağıtım şartları hukuk kontrolüyle yürütülür.
- Ceres `WITH_SUITESPARSE=OFF`.
- Her dependency için exact version, SPDX ID, source URL, license text ve transitive kayıt tutulur.
- Release’te CycloneDX/SPDX SBOM üretilir.
- Kod, veri, model ağırlığı ve eğitim verisi lisansı ayrı değerlendirilir.
- Müşteri girdisi için ürün işleme izni, benchmark ve eğitim izninden ayrıdır.
- Rakip servis çıktıları yazılı izin/ToS uygunluğu olmadan eğitim veya kapalı benchmark materyali yapılmaz.
- US10212457, US10743035, US11395011 ve Adobe lokal/interaktif tracing aileleri için ticari release öncesi uzman FTO gerekir.
- Clean-room/invention log içinde araştırma kaynağı, spike sonucu, karar ve tarih tutulur.
- Bağımsız geliştirme tek başına patent riskini kaldırmaz.

Bu bölüm hukuki tavsiye değildir.

---

## 24. ADR listesi

- [ ] **ADR-001:** Input/output formatları ve kaynak limitleri.
- [ ] **ADR-002:** Linear RGB, OKLab, ICC ve alpha semantiği.
- [ ] **ADR-003:** C++/Python sınırı ve dependency manager.
- [ ] **ADR-004:** Half-edge orientation, outer face ve görünmeyen katman politikası.
- [ ] **ADR-005:** 4/8-connectivity ve diagonal junction hipotezleri.
- [x] **ADR-006:** İç optimizer evaluator ile referans renderer ayrımı — `docs/adr/ADR-006-optimizer-evaluator-renderer-separation.md`.
- [ ] **ADR-007:** DP/beam/MILP model selection yaklaşımı ve FTO etkisi.
- [x] **ADR-008:** Platform içi/platformlar arası determinism — `docs/adr/ADR-008-determinism-contract.md`.
- [x] **ADR-009:** PDF backend ve fiziksel ölçü — `docs/adr/ADR-009-pdf-export-scope.md` (E6 SVG-only kararı).
- [ ] **ADR-010:** Confidence kalibrasyonu ve UI sunumu.
- [x] **ADR-011:** Koordinat normalizasyonu, epsilon ve SVG quantization — `docs/adr/ADR-011-coordinate-epsilon-serialization.md`.
- [x] **ADR-012:** Fill/stroke arbitration — `docs/adr/ADR-012-fill-stroke-arbitration.md`.
- [x] **ADR-013:** Cut-ready minimum geometri toleransları — `docs/adr/ADR-013-cut-ready-physical-validation.md`.
- [ ] **ADR-014:** Artifact storage, veri retention ve silme.
- [ ] **ADR-015:** Lokal reprocess graph invalidation sınırı.
- [x] **ADR-016:** Local-first web deployment, localhost güvenliği ve opsiyonel Tauri paketleme — `docs/adr/ADR-016-local-first-web-deployment.md`.
- [x] **ADR-017:** Local observability ve privacy — `docs/adr/ADR-017-local-observability-and-privacy.md`.
- [x] **ADR-018:** Lokal job process supervision ve fail-closed publication — `docs/adr/ADR-018-local-job-supervision.md`.
- [x] **ADR-019:** Bounded FIFO queue ve özel idempotency indeksi — `docs/adr/ADR-019-idempotent-local-queue.md`.
- [x] **ADR-020:** E7 optimized job mode ve lokal UI sınırı — `docs/adr/ADR-020-e7-optimized-job-modes.md`.
- [x] **ADR-021:** Kaynak koordinatında lokal karşılaştırma ve inline SVG yayın kapısı — `docs/adr/ADR-021-local-comparison-coordinate-contract.md`.

Her ADR; bağlam, seçenekler, karar, gerekçe, benchmark kanıtı, sonuçlar ve geri dönüş maliyeti içerir.

---

## 25. Uygulama task listesi

Süreler tek deneyimli geliştirici için çalışma günü tahminidir. Task tamamlanması, yalnızca kodun yazılması değil acceptance criterion ve evrensel DoD’nin geçmesi anlamına gelir.

## E0 — Temel kararlar ve repository — 5–7 gün

**Durum:** Tamamlandı. Yerel Python/schema kontrolleri ve native CMake/Zig doğrulaması geçti; Windows/MSVC ve Linux/GCC doğrulaması CI matrisinde bağlayıcıdır.

- [x] **ARC-001 — Monorepo iskeletini kur** — P0, 1 gün, bağımlılık: yok
  - CMake, Python/uv, vcpkg, `cpp/`, `python/`, `schemas/`, `benchmark/`, `docs/` oluştur.
  - **Kabul:** Windows ve Linux’ta boş core library + Python package CI’da build olur.

- [x] **ARC-002 — Sözleşme şemalarını oluştur** — P0, 1.5 gün, bağımlılık: ARC-001
  - Engine config, manifest, validation ve benchmark record JSON Schema.
  - **Kabul:** Örnek valid/invalid fixture’lar schema testlerinden geçer.

- [x] **ARC-003 — Numerik ve determinism politikasını yaz** — P0, 1 gün, bağımlılık: ARC-001
  - Sort/tie-break/seed/thread/locale/path orientation taslağı.
  - **Kabul:** ADR-008 ve ADR-011 ilk kararları onaylıdır.

- [x] **ARC-004 — Typed error/status iskeletini kur** — P0, 0.5 gün, bağımlılık: ARC-001
  - **Kabul:** C++ → Python hata mapping testi bulunur.

- [x] **LEG-001 — Dependency ve lisans envanteri oluştur** — P0, 1 gün, bağımlılık: ARC-001
  - Allow/deny/review listesi; Potrace izolasyonu; SuiteSparse kapalı.
  - **Kabul:** SPDX tablosu ve notice üretim taslağı vardır.

- [x] **CI-001 — İlk CI matrisini kur** — P0, 1 gün, bağımlılık: ARC-001
  - **Kabul:** Windows/Linux build, unit test ve lint her PR’da çalışır.

### Gate G-FOUNDATION

Şema, determinism politikası ve lisans sınırları net değilse benchmark geliştirmesine geçilmez.

## E1 — Benchmark harness — 15–20 gün

**Durum:** Tamamlandı. T0–T3 ile 20 development case, pinned resvg/VTracer/Potrace, elle kalibre edilmiş metrikler, locked-split grant gate ve iki-run semantic/artifact determinism doğrulaması hazırdır.

- [x] **BEN-001 — Dataset manifest ve family split modeli** — P0, 2 gün, bağımlılık: ARC-002, LEG-001
  - **Kabul:** Aynı design/font family’nin iki split’e girmesi otomatik testte reddedilir.

- [x] **BEN-002 — Prosedürel shape/region fixture generator** — P0, 3 gün, bağımlılık: BEN-001
  - Circle, hole, nested shape, shared edge, junction, text-like glyph.
  - **Kabul:** Component/hole/adjacency/primitive ground truth üretir.

- [x] **BEN-003 — Deterministik degradation generator** — P0, 3 gün, bağımlılık: BEN-002
  - Resolution, JPEG, blur, resize, alpha/background.
  - **Kabul:** Aynı seed aynı byte/hash ve manifesti üretir.

- [x] **BEN-004 — SVG reference render adaptörü** — P0, 2 gün, bağımlılık: BEN-002
  - Pinned resvg ve checksum.
  - **Kabul:** Aynı SVG/resolution aynı render hash’ini üretir.

- [x] **BEN-005 — Topology ve geometry metric motoru** — P0, 3 gün, bağımlılık: BEN-001
  - **Kabul:** El ile hesaplanmış küçük fixture’larda değerler birebir doğrulanır.

- [x] **BEN-006 — Fidelity/editability/runtime metric motoru** — P0, 2 gün, bağımlılık: BEN-004
  - **Kabul:** Linear RGBA, alpha, node/path ve stage süreleri raporlanır.

- [x] **BEN-007 — VTracer baseline adaptörü** — P0, 1 gün, bağımlılık: BEN-006
  - **Kabul:** Sürüm/preset/exit status/runtime manifestte görünür.

- [x] **BEN-008 — Potrace binary baseline adaptörü** — P0, 1 gün, bağımlılık: BEN-006, LEG-001
  - **Kabul:** Yalnızca binary setinde ayrı process; dağıtım/lisans notu bulunur.

- [x] **BEN-009 — Raporlama ve Pareto grafikleri** — P0, 2 gün, bağımlılık: BEN-005, BEN-006, BEN-007
  - **Kabul:** Tek komut topology → fidelity → node gate sırasıyla HTML/JSON rapor üretir.

- [x] **BEN-010 — Locked split ve harness determinism CI** — P0, 1 gün, bağımlılık: BEN-009
  - **Kabul:** Arka arkaya iki run aynı metric/manifest çıktısını verir; locked örnekler tuning komutlarında erişilemez.

### Gate G0 — Ölçüm güvenilirliği

**Durum:** Geçildi. Windows yerel gerçek araç smoke'u ve Linux CI smoke job'u VTracer + Potrace ile tanımlıdır; semantic digest `2db22757f88585eddae63ecc80e0a6a8c24557221a6323e641293ea4af806e61` olarak iki ardışık koşuda doğrulanmıştır.

- Harness deterministik olmalı.
- En az 20 development fixture ve iki baseline çalışmalı.
- Metrikler elle doğrulanmış örneklerde doğru olmalı.
- Aksi halde motor algoritmasına başlanmaz.

## E2 — Binary vertical slice — 40–45 gün

- [x] **BIN-001 — Güvenli decode ve resource limitleri** — P0, 2 gün, bağımlılık: G0
  - **Kabul:** Bozuk/aşırı girdiler typed error; crash yok.

- [x] **BIN-002 — Renk ve alpha normalizasyonu** — P0, 3 gün, bağımlılık: BIN-001, ADR-002
  - **Kabul:** Sentetik straight/premultiplied fixture’lar tolerans içinde eşleşir.

- [x] **BIN-003 — Reliability map v1** — P0, 3 gün, bağımlılık: BIN-002
  - **Kabul:** JPEG/blur/AA sentetik fixture’larında anlamlı ve görselleştirilebilir harita üretir.

- [x] **BIN-004 — Binary segmentasyon, components ve holes** — P0, 3 gün, bağımlılık: BIN-002
  - **Kabul:** Temiz binary development setinde exact topology ≥ %99.

- [x] **BIN-005 — Half-edge RegionGraph veri modeli** — P0, 5 gün, bağımlılık: BIN-004, ADR-004, ADR-005
  - **Kabul:** Tüm temel invariant unit/property testlerinden geçer.

- [x] **BIN-006 — Graph invariant validator ve fuzz target** — P0, 3 gün, bağımlılık: BIN-005
  - **Kabul:** Rastgele küçük label grid corpus’unda crash/invariant kaçağı yok.

- [x] **BIN-007 — Subpixel boundary synthetic spike** — P0, 4 gün, bağımlılık: BIN-003, BIN-005
  - **Kabul:** Pixel-edge baseline’a karşı hata dağılımı ve continue/revise kararı raporlanır.

- [x] **BIN-008 — BoundaryEvidence production v1** — P0, 4 gün, bağımlılık: BIN-007
  - **Kabul:** Her canonical edge sample/covariance/residual üretir; junction mask uygular.

- [x] **BIN-009 — Line ve cubic Bézier candidate üretimi** — P0, 4 gün, bağımlılık: BIN-008
  - **Kabul:** Her edge interval’i feasible adayla kapsanır; degenerate aday yok.

- [x] **BIN-010 — MDL/DP model selection v1** — P0, 4 gün, bağımlılık: BIN-009, ADR-007
  - **Kabul:** Sentetik çizgi/eğri setinde aynı fidelity bandında raw polygon’dan daha az node.

- [x] **BIN-011 — Kanonik SVG serializer** — P0, 3 gün, bağımlılık: BIN-010, ADR-011
  - **Kabul:** Export/parse/export idempotent; aynı platformda byte deterministik.

- [x] **BIN-012 — Structural ve raster validation v1** — P0, 2 gün, bağımlılık: BIN-011
  - **Kabul:** Raster embed, açık path, self-intersection ve fidelity failure raporlanır.

- [x] **BIN-013 — Uçtan uca CLI ve artifact bundle** — P0, 2 gün, bağımlılık: BIN-012, ARC-004
  - **Kabul:** Tek komut SVG/preview/manifest/validation/metrics üretir.

- [x] **BIN-014 — Binary locked benchmark ve ablation** — P0, 2 gün, bağımlılık: BIN-013
  - **Kabul:** No-subpixel ve Bézier-only farkları dahil G1 raporu oluşur.

### Gate G1 — Binary kanıt

**Durum:** Geçildi. 20-vakalık prosedürel binary sette exact topology `%100`, hard failure `0`, aynı veya daha iyi fidelity bandında VTracer'a karşı node avantajı `%73.21` ve Potrace'ın karşılaştırılabilir alt kümesine karşı `%16.67` ölçüldü. No-subpixel ortalama RMSE kaybı `+0.007309`, Bézier-only ortalama node farkı `+154.1`; semantic digest `671a67cc7e58d3520a22fd4adce51f60802b262dec080e5bd866d71bcd56cb7e` olarak tekrarlandı.

- Sentetik locked sette exact topology ≥ %95.
- Aynı fidelity bandında açık kaynak baseline’a karşı node avantajı gösterilmeli.
- Shared edge ve SVG validation hard fail oranı hedefin içinde olmalı.
- Avantaj yoksa multicolor’a geçilmez; boundary/model selection revize edilir.

**Yatırım demosu v0.2:** Bu gate sonrasında dürüst, ölçülebilir binary motor demosu mümkündür.

## E3 — Multicolor, primitive recovery ve demo web — 28–33 gün

**Durum:** COL-001…COL-007, GEO-001…GEO-003 ve DEMO-001 tamamlandı. 11 adet 2–12 renk stripe ile 6 logo/ikon/Türkçe vakayı içeren 17-vakalık G2 v2; overall/representative/Türkçe exact topology `%100`, resvg/Inkscape/Chromium maksimum seam gap `%0`, overall VTracer node avantajı `%61.46` ve representative node avantajı `%72.90` ile geçti. Üç renderer matrisinde minimum seam alpha `0.9961`, maksimum channel delta `0.06275`; semantic digest `af70104687b5f682e11ed19c3b5d0092ddc04c106e0763e3db2c456865cbe009` iki bağımsız koşuda tekrarlandı.

- [x] **COL-001 — OKLab palette hypotheses** — P0, 3 gün, bağımlılık: G1
  - **Kabul:** 2–12 renk sentetik sette palette count/color hatası raporlanır.

- [x] **COL-002 — Spatial multiclass segmentation** — P0, 4 gün, bağımlılık: COL-001
  - **Kabul:** JPEG renk varyasyonları gereksiz region patlaması yaratmaz.

- [x] **COL-003 — Multicolor graph ve nested region** — P0, 4 gün, bağımlılık: COL-002
  - **Kabul:** Adjacency ve hole ground truth testleri geçer.

- [x] **COL-004 — Junction topology hypotheses** — P0, 3 gün, bağımlılık: COL-003, ADR-005
  - **Kabul:** Checkerboard/diagonal/T-junction belirsizliği alternatif ve confidence üretir.

- [x] **COL-005 — Shared boundary assembly ve seam matrix** — P0, 3 gün, bağımlılık: COL-004
  - **Durum:** Canonical shared geometry, reverse face reference ve gerçek pinned resvg 0.47.0 / Inkscape 1.4.2 / Chromium 153 seam matrisi tamamlandı.
  - **Kabul:** Komşu path’ler aynı geometry’den gelir; resvg/Chromium/Inkscape test raporu vardır.

- [x] **GEO-001 — Line/arc/circle adayları** — P0, 2 gün, bağımlılık: COL-005
  - **Kabul:** Sentetik parametre recovery metriği hedef toleransta.

- [x] **GEO-002 — Ellipse ve elliptical arc** — P0, 2 gün, bağımlılık: GEO-001
  - **Kabul:** Rotation/eccentricity fixture’larında degenerate fit yok.

- [x] **GEO-003 — Rectangle ve rounded rectangle** — P0, 2 gün, bağımlılık: GEO-001
  - **Kabul:** Radius/corner consistency ground truth ile ölçülür.

- [x] **COL-006 — Multicolor model selection ve export** — P0, 3 gün, bağımlılık: GEO-001, GEO-002, GEO-003
  - **Kabul:** Top-K scene ve skor bileşenleri manifestte; topology regressions hard fail.

- [x] **COL-007 — Multicolor locked gate raporu** — P0, 1 gün, bağımlılık: COL-006
  - **Kabul:** G2 topology/fidelity/node/seam sonuçları yayınlanır.

- [x] **DEMO-001 — Minimal local-first web yatırım arayüzü** — P0, 3 gün, bağımlılık: COL-007, ADR-016
  - Upload, mod seçimi, source/result, temel metrikler ve artifact indirme.
  - **Kabul:** Motor pipeline localhost API üzerinden çağrılır; dosya dış servise gönderilmez; demo tek komutla başlar.

### Gate G2 — Multicolor yatırım prototipi

**Durum:** Geçildi. `out/multicolor-g2-renderer-matrix/g2-report.json` ve `out/multicolor-g2-renderer-matrix-repeat/g2-report.json` schema-valid ve deterministiktir. 17/17 exact topology, 17 fidelity-band karşılaştırması, üç gerçek renderer’da `%0` seam gap, overall `%61.46` ve representative `%72.90` VTracer node avantajı ölçüldü. Alpha-fringe palette patlaması stable-color-core sampling ile; nested/Türkçe topology semantiği global alpha hole ve gerçek connected-component truth ile; shared node fazlalığı twin yüzlerin ters yönde kullandığı canonical-chain sadeleştirmesiyle giderildi.

- Shared-boundary topolojisi ve renderer seam sonuçları açıkça gösterilir.
- Aynı fidelity bandında VTracer'a karşı nonnegative node advantage zorunludur.
- Türkçe kontur alt setinde kritik delik/diakritik hataları ayrı raporlanır.
- Local-first web demo, locked benchmark sonuçlarını ve artifact’leri sunar.

**Yatırım prototipi v0.3:** Bu gate, seçilmiş örnek yerine kilitli benchmark’lı multicolor web demo hedefidir.

## E4 — Stroke ve line-art — 18–22 gün

**Durum:** STR-001…STR-008 tamamlandı. 13-vakalık locked G3 corpusu routing accuracy `%92.31`, stroke connectivity `%100`, junction valence `%100`, style renderer-equivalence `%100`, fidelity-band pass `%100`, cut-outline validation `%100`, centerline p95 `0.5 px`, ortalama width error `0.337 px` ve fill dalına karşı node avantajı `%54.95` ile geçti. Semantic digest `329d630a7bf009abb5b27fc30fa1224304b5508bccd4d3ca54b62caa42ecfb2d` iki bağımsız koşuda tekrarlandı.

- [x] **STR-001 — Fill/stroke routing dataset ve classifier v1** — P1, 3 gün, bağımlılık: G2
  - **Kabul:** Confusion matrix ve düşük güven fallback kuralı vardır.

- [x] **STR-002 — Skeleton/centerline graph** — P1, 4 gün, bağımlılık: STR-001
  - **Kabul:** Sentetik line-art centerline distance/connectivity ölçülür.

- [x] **STR-003 — Width profile ve constant/variable model** — P1, 3 gün, bağımlılık: STR-002
  - **Kabul:** Width error ve complexity karşılaştırması raporlanır.

- [x] **STR-004 — Cap/join adayları** — P1, 2 gün, bağımlılık: STR-003
  - **Kabul:** Butt/round/square ve miter/round/bevel golden’ları geçer.

- [x] **STR-005 — T/X junction çözümü ve spur temizliği** — P1, 3 gün, bağımlılık: STR-004
  - **Kabul:** Junction valence/connectivity ground truth ile eşleşir.

- [x] **STR-006 — Fill/stroke arbitration** — P1, 3 gün, bağımlılık: STR-005, ADR-012
  - **Kabul:** Her iki hipotez render/topology/complexity ile karşılaştırılır; düşük güven `needs_review` olur.

- [x] **STR-007 — Stroke SVG ve cut-outline export** — P1, 2 gün, bağımlılık: STR-006
  - **Kabul:** Stroke ve outline render’ları tolerans içinde; cut validator geçer.

- [x] **STR-008 — Stroke locked gate** — P1, 1 gün, bağımlılık: STR-007
  - **Kabul:** Kopukluk, yanlış birleşme, width ve node avantajı raporlanır.

### Gate G3 — Stroke devam kararı

**Durum:** Geçildi. `out/stroke-g3-final/g3-report.json` ve `out/stroke-g3-final-repeat/g3-report.json` schema-valid ve deterministiktir. Stroke dalı aynı fidelity bandında fill’e karşı `%54.95` node avantajı gösterdi; topology/connectivity, T/X valence, cap/join renderer-equivalence, width ve cut-outline hard kriterlerinin tamamı geçti. Stroke dalı pilot MVP’de tutulur.

## E5 — Global optimizer ve render-and-rank — 15–20 gün

- [x] **OPT-001 — Objective term normalizasyonu** — P1, 2 gün, bağımlılık: G2 veya G3
  - **Durum:** Fidelity/color unit interval, boundary/regularization image-diagonal ve complexity pre-opt baseline oranıyla normalize edilir; topology weighted penalty değil hard eligibility gate’tir. Unit ve scale-invariance testleri eklendi.
  - **Kabul:** Her term unit test ve ölçek analizi içerir.

- [x] **OPT-002 — Profile ağırlıkları ve config versioning** — P1, 2 gün, bağımlılık: OPT-001
  - **Durum:** `benchmark/configs/optimizer-profiles-v1.json` dört modu, deterministic bütçeleri ve render-rank politikasını kod dışında tutar; strict loader canonical JSON üzerinden profile ve profile-set SHA-256 üretir.
  - **Kabul:** Dört modun ayarları kod dışında ve hash’lenebilir.

- [x] **OPT-003P — Solver-independent parameter blocks ve deterministik Python backend** — P1, 3 gün, bağımlılık: OPT-001, ADR-006
  - **Durum:** Canonical-order vertex, primitive, RGBA ve width block’ları; projected coordinate refinement; fixed step/iteration/evaluation bütçesi ve deterministik accepted snapshot kontratı tamamlandı.
  - **Kabul:** Vertex, primitive, color ve width bounds test edilir; sabit adım/evaluation bütçeli backend deterministiktir.

- [ ] **OPT-003C — Ceres backend parity/migration** — Koşullu P1, 3–5 gün, bağımlılık: G4
  - **Durum:** `SPIKE-017` renderer oracle bottleneck’ini doğruladı; continuous palette evaluator production OPT-003P kontratına bağlandı fakat vaka başına en fazla `46 ms` kullandı. Ceres’in end-to-end kazancı olmadığı için dependency entegrasyonu ertelendi; vertex/primitive/width evaluator maliyeti büyürse yeniden açılır.
  - **Kabul:** Yalnız G4 ölçülebilir kalite değerini doğrular veya Python heavy-path runtime hedefini kaçırırsa açılır; OPT-003P parameter/result kontratı ve determinism parity testleri korunur.

- [x] **OPT-004 — Hard/soft constraint residual’ları** — P1, 4 gün, bağımlılık: OPT-003P
  - **Durum:** Topology signature’ın component/hole/adjacency/cycle/shared geometry/connectivity/valence/path/node alanları non-compensable hard gate’tir; radius/width positivity bounds ile korunur.
  - **Kabul:** Shared boundary, closure ve positive radius/width hiçbir testte bozulmaz.

- [x] **OPT-005 — Robust refinement ve early stop** — P1, 3 gün, bağımlılık: OPT-004
  - **Durum:** Fixed candidate/iteration/evaluation bütçeleri, minimum-improvement kabulü, early stop ve node-regression reddi uygulanır.
  - **Kabul:** Fidelity iyileşir; topology/node gerilemesi olmaz; runtime bounded.

- [x] **OPT-006 — Top-K resvg render-and-rank** — P1, 2 gün, bağımlılık: OPT-005
  - **Durum:** Baseline daima Top-K içinde tutulur; `0.5×/1×/2×/4×` ve transparan/siyah/beyaz/checkerboard skorları profile fidelity bandı ve stable ID tie-break ile manifestte saklanır.
  - **Kabul:** Multi-scale/background skorları ve deterministik winner manifestte.

- [x] **OPT-007 — Divergence/fallback** — P1, 2 gün, bağımlılık: OPT-006
  - **Durum:** Non-finite/evaluator/renderer/profile failure kontrollüdür; yalnız önceden hard-valid baseline `degraded` fallback olabilir, invalid baseline fallback olmaz.
  - **Kabul:** NaN/crash yok; pre-opt fallback yalnızca hard validation geçerse kullanılır.

- [x] **OPT-008 — Optimizer ablation ve gate raporu** — P1, 1 gün, bağımlılık: OPT-007
  - **Durum:** `out/optimizer-g4-final/g4-report.json` ve repeat raporu schema-valid, digest-repeat ve runtime/RSS dışı semantic projection taşır.
  - **Kabul:** Kalite kazancı/runtime maliyeti açıkça ölçülür.

### Gate G4 — Optimizer devam kararı

**Durum:** Geçildi. 17 locked multicolor vakasında topology `%100`, fallback/node/fidelity regression `0`, iyileşen vaka `3` ve ortalama multi-scale/background RMSE kazancı `0.001594` ölçüldü. Byte-identical SVG render/score deduplication, prepared reference cache ve byte-exact compositing sonrası optimizer heavy-path p95 iki koşuda `4.79 s` ve `4.27 s` oldu. İyileşen representative vakalarda node avantajı junction `%50`, nested `%83.1`, shared-edge `%27.3` kaldı. İki bağımsız koşunun runtime-dışı semantic digest’i `cfb197b194c2a14a64e49748988e6cbce53f269c01f2c6ccbabf38480111d81a` ile eşleşti. Optimizer quality/offline yolunda tutulur; Continuous palette evaluator production yoluna bağlandı ve vaka başına en fazla `46 ms` kullandı; Ceres ancak vertex/primitive/width evaluator maliyeti ölçülebilir biçimde büyürse parity backend olarak eklenir.

Ölçülebilir kalite kazancı yoksa optimizer varsayılan hızlı moddan çıkarılır; yalnızca offline/quality modunda tutulur.

## E6 — Validator, Cut-ready ve ürün sertleştirme — 14–17 gün

- [x] **VAL-001 — Full topology/geometric validator** — P1, 3 gün, bağımlılık: G4
  - **Kabul:** Open, duplicate, crossing, gap/overlap ve invariant testleri vardır.

- [x] **VAL-002 — Cut-ready kuralları** — P1, 3 gün, bağımlılık: VAL-001, ADR-013
  - **Kabul:** Ölçü, minimum segment/gap ve closure hard gate çalışır.

- [x] **VAL-003 — Renderer agreement matrix** — P1, 2 gün, bağımlılık: VAL-001
  - **Kabul:** resvg/Chromium/Inkscape farkları release raporunda görünür.

- [x] **OBS-001 — Structured logging** — P1, 1 gün, bağımlılık: ARC-004
  - **Kabul:** Stable event code ve stage span’leri JSONL üretir.

- [x] **OBS-002 — Full run manifest** — P1, 2 gün, bağımlılık: OBS-001, ARC-002
  - **Kabul:** Run, artifact ve dependency bilgisi schema-validdir.

- [x] **OBS-003 — Privacy ve opt-in debug policy** — P1, 1 gün, bağımlılık: OBS-002, LEG-001
  - **Kabul:** Default logda görüntü/path/metin yoktur.

- [x] **EXP-001 — PDF backend spike** — P2, 2 gün, bağımlılık: VAL-001, ADR-009
  - **Kabul:** Lisans, ölçü ve renderer uyumu kararı belgelenir; başarısızsa kapsam SVG’de kalır.

- [x] **SEC-001 — Resource limit ve sandbox hardening** — P1, 2 gün, bağımlılık: VAL-001
  - **Kabul:** Timeout/memory/decode-bomb testleri geçer.

**E6 kanıtı (Windows x86-64):** `out/e6-release-windows/e6-release-report.json` şemaya uygun ve başarılıdır. 17 G2 vakanın resvg/Chromium/Inkscape üçlü karşılaştırmasında 51 renderer çifti; beyaz arka plan bileşik görüntü RMSE maksimum `0.008444` (`0.08` sınırı). Chrome ekran görüntüsü opak beyaz olduğundan ham alpha uyuşmazlığı ayrıca *gözlem* olarak raporlanır ve sahte bir alpha eşdeğerliği iddia edilmez. G2/G3/G4 tekrar digestleri eşleşti; sırasıyla `af70104687b5f682e11ed19c3b5d0092ddc04c106e0763e3db2c456865cbe009`, `329d630a7bf009abb5b27fc30fa1224304b5508bccd4d3ca54b62caa42ecfb2d`, `cfb197b194c2a14a64e49748988e6cbce53f269c01f2c6ccbabf38480111d81a`. `232` Python testi, Ruff ve mypy geçti. PDF için 32 mm vektör/ölçü deneyi olumlu, fakat bağımsız PDF renderer/topoloji uyumu kanıtlanmadığı için [ADR-009](adr/ADR-009-pdf-export-scope.md) gereği release **SVG-only**. Dış araçların ortamı sanitize edilir, timeout ve girdi/piksel/bellek bütçeleri zorlanır; OS seviyesinde bellek sandbox'ı veya Linux üzerinde üçlü tam renderer matrisi **kanıtlanmış değildir**. E7 üretim dağıtımı öncesinde bunlar ayrı platform doğrulamasına tabidir.

## E7 — API, UI ve lokal yeniden işleme — 15 gün

- [x] **API-001 — Lokal job API** — P1, 2 gün, bağımlılık: OBS-002, VAL-001
  - **Kabul:** Upload/status/cancel/artifact/error sözleşmesi stabil. `POST /v1/jobs` + status/cancel/allowlisted artifact uçları, atomik JSON durum kaydı ve gerçek worker/renderer process-tree iptali testlidir. E3 senkron endpoint uyumluluk için kalır. API-002 kuyruğu/idempotency henüz yoktur; tek worker doluyken typed `429` döner. Yeni job uçları yalnız işlevsel `geometric` ve `stroke` modlarını ilan eder.

- [x] **API-002 — Idempotency ve resource queue** — P1, 2 gün, bağımlılık: API-001
  - **Kabul:** Aynı anahtar duplicate iş üretmez; limit aşımı typed error. Ham anahtar kaydedilmeden SHA-256/fingerprint özel yan dosyası tekrar başlatmada da eşleşir; farklı talep `409`, dolu FIFO/limitli upload `429`, bozuk indeks keyed admission için `503` üretir. Tek API instance + bir worker/iki bekleyen iş varsayılandır; otomatik retention, multi-process kilidi ve OS RAM sandbox'ı kapsam dışıdır.

**E7 API/UI kanıtı:** Job/queue/cancel/restart/CORS/symlink, dört modun pinned profile routing'i ve kilitli şema fixture testleriyle `250` Python testi; Ruff, mypy, web type-check/build ve sekiz web durum/artefact/koordinat birim testi geçti. API-001/002 ve UI-001 tamamlandı. Tarayıcı E2E ve paketlenmiş wheel JSON resource doğrulaması henüz yapılmadı; native CTest bu ortamda bulunmadığı için E7 değişiklikleri için tekrar çalıştırılamadı.

- [x] **UI-001 — Upload, mode ve job status** — P1, 2 gün, bağımlılık: API-001
  - **Kabul:** Dört mode gerçek pipeline'a bağlandı: faithful/minimal farklı kilitli optimizer profilleri, geometric hızlı temel akış, stroke line-art. UI `/v1/jobs` üzerinden upload/poll/cancel, typed error ve bütün final statüleri gösterir; yalnız doğrulanmış success/degraded/needs_review dosyaları yayınlanır. Üçüncü taraf font çağrısı kaldırıldı; kayıp upload yanıtında aynı istek anahtarı yeniden kullanılır.

- [x] **UI-002 — Before/after ve baseline karşılaştırması** — P1, 2 gün, bağımlılık: UI-001
  - **Kabul:** Tek kaynak-piksel koordinatında raster, yayınlanmış **gerçek SVG** ve kullanıcı tarafından seçilen eş boyutlu yerel PNG/JPEG baseline pan/zoom paylaşır. Cursor-anchor zoom, aspect letterboxing ve sınır clamp testlidir; uyuşmayan baseline/SVG boyutu zorla ölçeklenmeyip reddedilir. Baseline görsel referanstır, otomatik Potrace/VTracer veya benchmark kanıtı değildir. Inline SVG yalnız yayımlanmış E7 job için sandbox/CSP ve symlink kontrolüyle servis edilir; tarayıcı E2E henüz yapılmadı.

- [ ] **UI-003 — Node, region ve shared-edge overlay** — P1, 2 gün, bağımlılık: UI-002
  - **Kabul:** Stabil entity ID üzerinden seçim çalışır.

- [ ] **UI-004 — Residual ve confidence açıklaması** — P1, 2 gün, bağımlılık: UI-003
  - **Kabul:** Kullanıcı düşük güvenin hangi stage’den geldiğini görür.

- [ ] **UI-005 — Lokal reprocess invalidation** — P1, 3 gün, bağımlılık: UI-004, ADR-015
  - **Kabul:** Etkilenen subgraph yenilenir ve tüm global validation tekrar çalışır.

- [ ] **UI-006 — E2E ve erişilebilirlik** — P1, 2 gün, bağımlılık: UI-005
  - **Kabul:** Ana kullanıcı akışları otomatik test ve klavye kullanımıyla geçer.

## E8 — Kapalı benchmark, pilot ve release kararı — 10–15 gün

- [ ] **REL-001 — 100 design / 300 input locked benchmark** — P1, 3 gün, bağımlılık: E6; UI zorunlu değil
  - **Kabul:** Önceden kaydedilmiş eşiklerle değiştirilemez rapor üretilir.

- [ ] **REL-002 — Kör A/B tercih testi** — P1, 2 gün, bağımlılık: REL-001
  - **Kabul:** Randomizasyon, confidence interval ve failure rate dahil.

- [ ] **REL-003 — Kör edit-time testi** — P1, 2 gün, bağımlılık: REL-001
  - **Kabul:** Aynı düzenleme görevinde medyan süre ve hata ölçülür.

- [ ] **REL-004 — SBOM, third-party notices ve source offer kontrolü** — P1, 2 gün, bağımlılık: LEG-001
  - **Kabul:** Dağıtım paketi lisans kontrolünden geçer.

- [ ] **REL-005 — Uzman FTO checkpoint** — P1, süre dış danışmana bağlı, bağımlılık: final algoritma
  - **Kabul:** Blocker, design-around veya kabul edilen risk yazılıdır.

- [ ] **REL-006 — Beta karar raporu** — P1, 1 gün, bağımlılık: REL-002, REL-003, REL-004, REL-005
  - **Kabul:** `continue`, `narrow`, `delay` veya `kill/pivot` kararı metriklere bağlıdır.

---

## 26. Evrensel Definition of Done

Bir task ancak aşağıdakilerin tamamı sağlandığında biter:

- [ ] Girdi/çıktı ve hata sözleşmesi belgeli.
- [ ] Unit test eklendi.
- [ ] İlgili integration/property/golden test eklendi.
- [ ] Determinism kontrolü geçti.
- [ ] Benchmark etkisi veya “etkisiz” notu kaydedildi.
- [ ] Runtime ve peak memory ölçüldü.
- [ ] Warning/fallback kullanıcıya ve manifest’e yansıyor.
- [ ] Debug artifact gizlilik politikasına uyuyor.
- [ ] Dependency/veri provenance kontrolü tamamlandı.
- [ ] İlgili ADR güncellendi.
- [ ] CI yeşil.
- [ ] Hard validation failure yok.

Gate raporu başarısızken ona bağlı epic “tamamlandı” sayılmaz.

---

## 27. Spike listesi

| ID | Spike | Süre | Çıkacak karar |
| --- | --- | ---: | --- |
| SP-01 | Diagonal/junction topology | 3 gün | Alternatif hipotez sayısı ve connectivity politikası |
| SP-02 | Synthetic subpixel recovery | 4 gün | PSF modeli ve gerçek kazanım |
| SP-03 | Shared-edge seam matrix | 3 gün | SVG duplication/quantization politikası |
| SP-04 | Primitive MDL/DP | 5 gün | Fidelity–node kazancı yeterli mi |
| SP-05 | Fill vs stroke | 5 gün | Stroke dalı MVP’ye girmeli mi |
| SP-06 | Ceres throughput | 5 gün | Analytic residual yeterli mi |
| SP-07 | PDF backend | 3 gün | Lisans/ölçü/uyumluluk |
| SP-08 | Cross-platform determinism | 3 gün | Byte eşitliği veya tolerans sözleşmesi |

Spike kodu production’a doğrudan merge edilmez. Sonuç ADR ve benchmark artifact’i üretir.

---

## 28. Kill/continue kapıları

- **G0:** Harness veya lisanslı veri güvenilir değilse motor yatırımı durur.
- **G1:** Binary dilim topology/node avantajı göstermiyorsa multicolor başlamaz.
- **G2:** Shared-boundary seam ve adjacency güvenilir değilse topolojik üstünlük iddiası yapılmaz.
- **G3:** Stroke, fill yaklaşımını geçmiyorsa MVP’den çıkarılır.
- **G4:** Optimizer kalite kazandırmıyorsa varsayılan yoldan çıkarılır.
- **G5:** Sentetik kazanç gerçek izinli girdilere taşınmıyorsa degradation seti yeniden tasarlanır.
- **G6:** Kalite artarken edit-time düşmüyorsa UI/editor interoperability önceliklenir.
- **G7:** Türkçe yazı kritik hataları sürerse ürün iddiası logo/ikon ile daraltılır.
- **G8:** Pilot hedefleri geçmezse genel lansman yapılmaz; dar beta veya teknik pivot seçilir.

---

## 29. Takvim ve sürüm planı

### 29.1 Tek geliştirici için gerçekçi tahmin

| Faz | Süre |
| --- | ---: |
| E0 Temel | 1–1.5 hafta |
| E1 Benchmark | 3–4 hafta |
| E2 Binary vertical slice | 8–9 hafta |
| E3 Multicolor/primitive/demo web | 5.5–6.5 hafta |
| E4 Stroke | 3.5–4.5 hafta |
| E5 Optimizer | 3–4 hafta |
| E6 Sertleştirme | 3–3.5 hafta |
| E7 UI | 3 hafta |
| E8 Pilot/release | 2–3 hafta |
| **Toplam** | **33–39 hafta** |

### 29.2 İki ayrı hedef

#### Yatırım kanıtı — yaklaşık 15–21 hafta

- benchmark harness,
- binary vertical slice,
- temel multicolor/shared boundary,
- sınırlı primitive recovery,
- CLI + local-first web karşılaştırma arayüzü,
- kilitli küçük benchmark.

Bu teslim “production-ready” değildir; teknik avantaj kanıtıdır.

#### Güvenilir pilot — toplam 33–39 hafta

- stroke,
- optimizer,
- full validator/cut-ready,
- UI/lokal reprocess,
- 100 design/300 input kapalı benchmark,
- SBOM/FTO/pilot kapıları.

### 29.3 Sürümleme

- `v0.1`: benchmark harness.
- `v0.2`: binary CLI.
- `v0.3`: multicolor fill ve local-first web yatırım demosu.
- `v0.4`: stroke + cut-ready.
- `v0.5`: optimizer + validation hardening.
- `v0.6`: UI ve pilot.
- `v1.0-rc`: locked benchmark, SBOM, FTO ve pilot sonrası.

---

## 30. Risk kaydı

| Risk | Olasılık | Etki | Önlem |
| --- | --- | --- | --- |
| Yanlış topoloji | Yüksek | Çok yüksek | Alternative hypotheses, invariant validator, topology gate |
| JPEG/noise’a aşırı uyum | Yüksek | Yüksek | Reliability, robust loss, MDL, multi-scale render |
| Düşük çözünürlükte çözümsüz belirsizlik | Yüksek | Orta | Confidence düşürme, `needs_review` |
| Renderer seam/fill-rule farkı | Orta | Yüksek | Canonical shared edge, üç-renderer test |
| Fill/stroke yanlış seçimi | Orta | Yüksek | İki hipotezi de üretme, width/connectivity metriği |
| Optimizer topology bozması | Düşük | Çok yüksek | Immutable graph, hard constraints, validation |
| Ceres gecikmesi | Orta | Orta | Bounded DOF/iteration, early stop, fallback |
| Türkçe hata ortalamada gizlenir | Orta | Yüksek | Karakter/diakritik alt grup gate’i |
| Benchmark leakage | Orta | Çok yüksek | Family-level split ve locked access control |
| Lisans/patent blocker | Orta | Çok yüksek | Early inventory, design-around, uzman FTO |
| Tek geliştiricide kapsam büyümesi | Yüksek | Yüksek | Gate tabanlı scope, UI/AI en son |
| Sentetik–gerçek domain farkı | Yüksek | Yüksek | İzinli gerçek set, G5 transfer gate |

---

## 31. Açık kararlar ve varsayılanlar

### Kararlaştırılanlar

- **Multicolor zorunlu P0’dır.** Binary vertical slice yalnızca algoritmik riski azaltan iç gate’tir; yatırım prototipi 2–12 renkli girdiyi desteklemeden tamamlanmış sayılmaz.
- **Arayüz local-first web olacaktır.** React/TypeScript tarayıcı UI’ı, localhost FastAPI ve native C++ motor kullanılacaktır.
- **Windows ve Linux baştan resmî P0 platformlarıdır.** Build, test, paketleme ve determinism kontrolleri iki platformda birlikte yürütülecektir; macOS ilk sürüm kapsamı dışındadır.
- Motor ilk sürümde browser/WASM içinde çalışmayacaktır.
- Ayrı masaüstü kod tabanı yazılmayacaktır; offline kurulum talebi kanıtlanırsa aynı UI Tauri ile paketlenecektir.

Uygulama başlamadan önce P0 için kapatılması gereken diğer sorular:

1. Non-sRGB ICC profilleri P0’da destek mi, açıkça kapsam dışı mı?
2. Vectorizer.AI ve Illustrator baseline’ları için kullanım/benchmark koşulları uygun mu?
3. Gerçek müşteri örneği ve uzman vektör ground truth erişimi var mı?
4. `Cut-ready` için ilk hedef birim ve minimum tolerans nedir?
5. PDF yatırım demosunda gerçekten gerekli mi?

Cevap gelene kadar varsayılanlar:

- SVG tek bağlayıcı çıktı.
- sRGB tam destek; diğer ICC profilleri açık warning/degraded.
- Yatırım demosu CLI + local-first web review UI; lokal düzenleme P1.
- Potrace yalnızca binary benchmark subprocess.
- Fotoğraf ve gradient kapsam dışı.
- Motor CPU-first; GPU bağımlılığı yok.

---

## 32. Uygulamaya başlama kontrol listesi

- [x] Multicolor yatırım prototipi için zorunlu P0 olarak belirlendi.
- [x] Local-first web UI ve native localhost motor mimarisi seçildi.
- [x] Windows + Linux resmî P0 platform hedefi olarak belirlendi; macOS kapsam dışı bırakıldı.
- [ ] PRD kapsamının kalan maddeleri kullanıcı tarafından onaylandı.
- [ ] Yatırım prototipi ile pilot MVP ayrımı kabul edildi.
- [ ] E0 ADR’leri açıldı.
- [x] Dependency/lisans allowlist hazır.
- [x] Benchmark dataset provenance şeması hazır.
- [x] Locked split sahibi ve erişim kuralı belirlendi.
- [ ] Referans development makinesi tanımlandı.
- [x] G0 ve G1 gate eşikleri kabul edildi.
- [x] Repository/CI bootstrap tamamlandı.

Bu kontrol listesi tamamlanmadan algoritma kodu yazılmamalıdır.
