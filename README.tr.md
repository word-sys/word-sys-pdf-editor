# word-sys's PDF Editor
<img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/word_sys_pdf_editor/img/f-pv1.svg" width="256" height="256"/>

**word-sys's PDF Editor**, Pardus, Debian ve diğer Linux dağıtımları için geliştirilmiş, PDF dosyalarındaki metin, görsel ve nesne içeriklerini düzenlemeye odaklanan, sade ve kullanıcı dostu bir araçtır. Linux ekosistemindeki sade, özgür ve açık kaynaklı PDF düzenleyici ihtiyacını karşılamak amacıyla #MilliTeknolojiHamlesi ve TEKNOFEST 2025 ruhuyla sıfırdan geliştirilen word-sys's PDF Editor, hem kurumsal hem de bireysel kullanıcılara hitap eder. Ücretli PDF düzenleyicilerin sunduğu temel ve yaygın işlevlerin çoğunu eksiksiz yerine getirir, zengin ve kullanımı kolay özellikler barındırır ve TEKNOFEST 2025 Pardus Hata Yakalama ve Öneri Yarışması / Pardus Geliştirme Yarışması'nda **BİRİNCİLİK** ödülü kazanmıştır.

Geliştirici: **Barın Güzeldemirci (word-sys)**  
Lisans: **GPL-3.0-or-later**

---

> [!TIP]
> **Önerilen Kararlı Sürüm: v1.11.0** — En kararlı deneyim için **1.11.0** sürümünü kullanmanız önemle tavsiye edilir. Kurulum ayrıntıları için aşağıdaki bölümleri inceleyebilirsiniz.

---

## Ekran Görüntüleri

| **PDF Düzenleme ve Açıklama Tuvali** | **Başlangıç Ekranı ve Belge Merkezi** |
| :---: | :---: |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot1.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot1.png" alt="PDF Düzenleme Tuvali" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot2.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot2.png" alt="Başlangıç Ekranı" width="450"/></a> |
| **Yeni Belge Oluşturma Penceresi** | **Etkileşimli Hızlı Başlangıç Kılavuzu ve Rehber** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot3.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot3.png" alt="Yeni Belge Penceresi" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot4.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot4.png" alt="Hızlı Başlangıç Kılavuzu" width="450"/></a> |

---

## Temel Özellikler

*   Özelleştirilebilir sayfa boyutları ve otomatik birim dönüştürme (mm, cm, in, pt, px) ile sıfırdan PDF oluşturma
*   PDF dosyalarını açma ve görüntüleme
*   PDF dosyalarını birleştirme
*   Etkileşimli Hızlı Başlangıç Kılavuzu ve klavye kısayolları tablosu (`F1`)
*   Sayfadaki mevcut metin bloklarını seçme
*   Seçilen metni düzenleme veya silme
*   Sayfaya yeni metin blokları ekleme
*   Alfa şeffaflığı korunarak resim ekleme
*   Linux Fontconfig (`fc-match`) motoru ile sistem yazı tipi ve kalınlık desteği
*   PDF içindeki nesneleri taşıma ve yeniden konumlandırma
*   Yazı tipi ailesini, boyutunu, rengini ve biçimlendirmesini değiştirme
*   Hassas kelime seçimi ve metin vurgulama
*   Şekiller ekleme (Dikdörtgen, Elips, Onay İşareti, Çarpı)
*   Bézier eğri yumuşatma ve vektör ölçeklendirme ile serbest çizim Kalem ve Vurgulayıcı
*   Özel karakterler ve simgeler
*   Düzenlenen PDF dosyalarını kaydetme
*   Hızlı Kaydetme (`Ctrl + S`)
*   PDF belgelerini DOCX, ODT (LibreOffice gerektirir) ve düz metin TXT formatlarına aktarma
*   Küçük resim sürükle-bırak ile canlı sayfa yeniden sıralama
*   Güvenli Kaydetme (Safe Save)
*   Kısıtlı Mod (Güvenli Mod)
*   Tam çok düzeyli Geri Al / Yinele geçmişi (`Ctrl + Z` / `Ctrl + Y`)
*   İmleç odaklı hassas yakınlaştırma (`Ctrl + Fare Tekerleği` ve `Ctrl + + / - / 0`)
*   PDF belgelerine sayfa ekleme ve çıkarma

---

## Kurulum

word-sys's PDF Editor'ü sisteminize kurmanın birden çok yolu bulunmaktadır:

### 1. Otomatik Kurulum (Önerilen Yöntem)

Pardus, Debian ve Ubuntu tabanlı dağıtımlar için en kolay kurulum yöntemidir.

1.  [**GitHub Sürümleri**](https://github.com/word-sys/word-sys-pdf-editor/releases) sayfasından en güncel `.deb` paketini indirin. Dosya adı genellikle `word-sys-pdf-editor_1.11.0_all.deb` şeklindedir.

    > [!TIP]
    > En kararlı deneyim için **1.11.0 sürümünü** tercih edin: Sürümler sayfasında `word-sys-pdf-editor_1.11.0_all.deb` dosyasını bulun.

2.  `.deb` dosyasını indirdiğiniz dizinde bir uçbirim (terminal) açın.
3.  Paketi kurmak için aşağıdaki komutu çalıştırın:
    ```bash
    sudo apt update
    sudo apt install ./word-sys-pdf-editor_1.11.0_all.deb
    ```
    *(Not: İndirdiğiniz dosya adı farklıysa komuttaki dosya adını güncelleyin.)*
4.  Kurulum sırasında bağımlılık sorunu yaşarsanız eksik paketleri gidermek için şu komutu çalıştırın:
    ```bash
    sudo apt --fix-broken install
    ```
5.  Kurulum tamamlandıktan sonra word-sys's PDF Editor'ü uygulama menünüzden başlatabilirsiniz.

---

### 2. AppImage ve Taşınabilir Paket (İkinci Önerilen Yöntem)

Tüm Linux dağıtımlarında kurulum yapmadan doğrudan çalıştırmak için uygundur.

1.  [**GitHub Sürümleri**](https://github.com/word-sys/word-sys-pdf-editor/releases) sayfasından `.AppImage` veya `*-linux-x64.tar.gz` paketini indirin.

    > En kararlı sürüm için sürümler sayfasındaki `v1.11.0` etiketini kullanın.

#### A. AppImage ile Çalıştırma

1. `word-sys-pdf-editor.AppImage` dosyasının bulunduğu dizinde terminal açın.

2. Dosyaya çalıştırma yetkisi verin:
    ```bash
    chmod +x word-sys-pdf-editor.AppImage
    ```

3. Dosyaya çift tıklayarak ya da terminalden çalıştırın:
    ```bash
    ./word-sys-pdf-editor.AppImage
    ```

#### B. Tar.gz Arşivi ile Çalıştırma

1. `word-sys-pdf-editor-linux-x64.tar.gz` dosyasının bulunduğu dizinde terminal açın.

2. Arşivi çıkartın:
    ```bash
    tar -xzf word-sys-pdf-editor-linux-x64.tar.gz
    ```

3. Çıkartılan dizine girin:
    ```bash
    cd AppDir
    ```

4. AppRun dosyasına çalıştırma izni verin:
    ```bash
    chmod +x AppRun
    ```

5. Uygulamayı başlatın:
    ```bash
    ./AppRun
    ```

---

### 3. Kaynak Koddan Kurulum (Geliştiriciler İçin)

Uygulamayı doğrudan kaynak koddan çalıştırmak veya geliştirmeye katkıda bulunmak isteyenler için uygundur.

> [!TIP]
> Kararlı bir deneyim için klonlarken **v1.11.0** etiketini kullanın. Geliştirme aşamasındaki en son değişiklikleri denemek isterseniz doğrudan `main` dalını klonlayabilirsiniz.

---

#### Pardus 23.4, Debian 12 ve Ubuntu < 24.04 — Manuel Kurulum

1.  **Gerekli Bağımlılıkları Kurun:**
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip python3-venv \
                     python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libgirepository1.0-dev \
                     python3-numpy \
                     python3-dev libcairo2-dev build-essential \
                     fonts-noto-core fonts-liberation2
    ```
    *İsteğe bağlı (DOCX dışa aktarımı için):*
    ```bash
    sudo apt install libreoffice-common
    ```

2.  **Kaynak Kodu İndirin:**

    **Önerilen (kararlı v1.11.0):**
    ```bash
    git clone --branch v1.11.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Geliştirme dalı için:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

3.  **Sanal Ortam Oluşturun ve Etkinleştirin (Önerilen):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
    *(Daha sonra ortamdan çıkmak için `deactivate` komutunu kullanabilirsiniz.)*

4.  **Python Paketlerini Kurun:**
    ```bash
    pip install PyMuPDF numpy pygobject==3.50.0
    ```

5.  **Uygulamayı Başlatın:**
    ```bash
    python3 run-editor.py
    ```

---

#### Ubuntu 24.04+, Debian 13 Trixie — Manuel Kurulum

1.  **Gerekli Bağımlılıkları Kurun:**
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip python3-venv \
                     python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libgirepository-2.0-dev \
                     python3-numpy \
                     python3-dev libcairo2-dev build-essential \
                     fonts-noto-core fonts-liberation2
    ```
    *İsteğe bağlı (DOCX aktarımı için):*
    ```bash
    sudo apt install libreoffice-common
    ```

2.  **Kaynak Kodu İndirin:**

    **Önerilen (kararlı v1.11.0):**
    ```bash
    git clone --branch v1.11.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Geliştirme dalı için:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

3.  **Sanal Ortam Oluşturun ve Etkinleştirin:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

4.  **Python Paketlerini Kurun:**
    ```bash
    pip install PyMuPDF numpy pygobject
    ```

5.  **Uygulamayı Başlatın:**
    ```bash
    python3 run-editor.py
    ```

---

#### Arch Linux ve Türevleri — Manuel Kurulum

1.  **Kaynak Kodu İndirin:**

    **Önerilen (kararlı v1.11.0):**
    ```bash
    git clone --branch v1.11.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Geliştirme dalı için:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    *İsteğe bağlı (DOCX aktarımı için):*
    ```bash
    sudo pacman -S libreoffice-fresh
    ```

2.  **Sanal Ortam Oluşturun ve Etkinleştirin:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Python Paketlerini Kurun:**
    ```bash
    pip install PyMuPDF numpy pygobject
    ```

4.  **Uygulamayı Başlatın:**
    ```bash
    python3 run-editor.py
    ```

---

#### Arch Linux ve Türevleri — AUR Üzerinden

#### BU PAKETLER PROJE SAHİBİ TARAFINDAN OLUŞTURULMAMAKTA VEYA YÖNETİLMEMEKTEDİR. YÜKLEMEDEN ÖNCE AUR ÜZERİNDEKİ İÇERİKLERİ KONTROL EDİNİZ. AUR İLE İLGİLİ SORUNLARDA İLGİLİ AUR PAKET YÖNETİCİSİ İLE İLETİŞİME GEÇİNİZ. RESMİ PAKETLER GITHUB RELEASES SAYFASINDA YAYINLANMAKTADIR.

1.  **İndirme, derleme ve kurulum:**

    ```bash
    git clone https://aur.archlinux.org/word-sys-pdf-editor
    cd word-sys-pdf-editor
    makepkg -sfi
    ```

    `yay` yardımcısı ile:
    ```bash
    yay -S word-sys-pdf-editor
    ```

    `paru` ile:
    ```bash
    paru -S word-sys-pdf-editor
    ```

    Veya AUR üzerindeki hazır ikili paket `-bin` ile:
    ```bash
    yay -S word-sys-pdf-editor-bin
    ```
    veya
    ```bash
    paru -S word-sys-pdf-editor-bin
    ```

    *İsteğe bağlı (DOCX aktarımı için):*
    ```bash
    sudo pacman -S libreoffice-fresh
    ```

2.  **Uygulamayı Başlatın:**
    ```bash
    word-sys-pdf-editor
    ```

---

## Hata Bildirimi ve Geri Bildirim

Herhangi bir hata ile karşılaşırsanız, yeni bir özellik önermek veya geri bildirimde bulunmak isterseniz lütfen [**GitHub Issues**](https://github.com/word-sys/word-sys-pdf-editor/issues) bölümünü kullanın.

---

## Katkıda Bulunma

word-sys's PDF Editor açık kaynaklı bir projedir ve katkılara açıktır. Katkıda bulunmak için:

1.  Bu depoyu forklayın.
2.  Yeni bir özellik veya hata düzeltmesi için dal oluşturun (`git checkout -b feature/yeni-ozellik` veya `git checkout -b fix/hata-adi`).
3.  Değişikliklerinizi yapın ve kaydedin (`git commit -am 'Yeni ozellik eklendi'`).
4.  Dalınızı GitHub'a gönderin (`git push origin feature/yeni-ozellik`).
5.  Bir Çekme İsteği (Pull Request) açın.

---

## Lisans

Bu proje [**GNU General Public License v3.0 or later**](LICENSE) ile lisanslanmıştır.
