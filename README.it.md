**Lingue:** [English](README.md) | [Türkçe](README.tr.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [Italiano](README.it.md) | [Русский](README.ru.md)

# word-sys's PDF Editor
<img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/word_sys_pdf_editor/img/f-pv1.svg" width="256" height="256"/>

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPLv3+-blue.svg)](LICENSE)
[![GitHub All Releases](https://img.shields.io/github/downloads/word-sys/word-sys-pdf-editor/total)](https://github.com/word-sys/word-sys-pdf-editor/releases)
[![Flathub](https://img.shields.io/flathub/v/io.github.word_sys.word-sys-pdf-editor?logo=flathub)](https://flathub.org/apps/io.github.word_sys.word-sys-pdf-editor)

**word-sys's PDF Editor** è uno strumento semplice e intuitivo sviluppato per Pardus, Debian e altre distribuzioni Linux, focalizzato sulla modifica di testo, immagini e oggetti nei documenti PDF. Sviluppato da zero nello spirito di #MilliTeknolojiHamlesi e TEKNOFEST 2025 per colmare la necessità di un editor PDF libero, semplice e open source nell'ecosistema Linux, word-sys's PDF Editor si rivolge sia a utenti aziendali sia a privati. Svolge la maggior parte delle operazioni essenziali offerte dagli editor a pagamento, include numerose funzioni di facile impiego ed è stato vincitore del **PRIMO POSTO** al concorso di sviluppo Pardus TEKNOFEST 2025.

Sviluppatore: **Barın Güzeldemirci (word-sys)**  
Licenza: **GPL-3.0-or-later**

---

> [!TIP]
> **Versione stabile consigliata: v1.12.0** — Per la massima stabilità operativa, si consiglia vivamente l'utilizzo della versione **1.12.0**. Consultare le sezioni di installazione seguenti per tutti i dettagli.

---

## Schermate

| **Area di modifica PDF e scorrimento continuo** | **Schermata iniziale e gestione documenti** |
| :---: | :---: |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot1.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot1.png" alt="Area di modifica PDF e scorrimento continuo" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot2.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot2.png" alt="Schermata iniziale e gestione documenti" width="450"/></a> |
| **Creazione di un nuovo documento** | **Guida rapida interattiva e manuale d'uso** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot3.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot3.png" alt="Creazione di un nuovo documento" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot4.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot4.png" alt="Guida rapida interattiva e manuale d'uso" width="450"/></a> |
| **Area visuale di unione documenti** | **Schede multi-documento e barra di firma digitale verificata** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot5.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot5.png" alt="Area visuale di unione documenti" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot6.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot6.png" alt="Schede multi-documento e barra di firma digitale" width="450"/></a> |
| **Sblocco tramite password per documenti crittografati** | **Finestra di firma digitale PAdES e token hardware** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot7.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot7.png" alt="Sblocco tramite password per documenti crittografati" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot8.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot8.png" alt="Finestra di firma digitale PAdES e token hardware" width="450"/></a> |
| **Verifica crittografica della firma e dettagli certificato** | **Motore di riconoscimento ottico (OCR) e livello di testo** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot9.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot9.png" alt="Verifica crittografica della firma e dettagli" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot10.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot10.png" alt="Motore di riconoscimento ottico (OCR) e livello di testo" width="450"/></a> |

---

## Funzionalità principali

*   Scorrimento verticale continuo delle pagine con rendering ritagliato sulla viewport, prefetching direzionale e scaling frazionario (HiDPI / 4K / Retina)
*   Motore interattivo AcroForms: compilazione diretta di campi di testo, caselle di controllo, pulsanti radio e menu a discesa in modalità lettura, e appiattimento vettoriale
*   Strumento interattivo per la creazione di moduli (`B`) per progettare, allineare e configurare nuovi campi AcroForm
*   Firme digitali PAdES Baseline con certificati software PKCS#12 e token di sicurezza hardware PKCS#11 / smart card (HSM)
*   Integrazione di marcatura temporale crittografica RFC 3161 con autenticazione TSA personalizzata
*   Verifica non bloccante delle firme all'apertura del documento con barra di stato e ispettore dei certificati X.509
*   Oscuramento crittografico permanente (`Shift+R`) con rilevamento automatico di dati sensibili (carte, e-mail, telefoni, regex) e bonifica approfondita
*   Motore di riconoscimento ottico dei caratteri (OCR) multi-thread in background con avanzamento in tempo reale e 7 modelli neurali
*   Strumento regione OCR (`O`) per l'estrazione immediata del testo e ispettore del livello di confidenza (`Ctrl+Alt+O`)
*   Note adesive con colori personalizzabili, metadati dell'autore, conversazioni a thread e barra laterale annotazioni
*   Timbri vettoriali di approvazione (Approvato, Riservato, Bozza, timbri dinamici utente/data)
*   Strumenti di misurazione di precisione: Righello di distanza (`U`) con scale calibrate e misurazione dell'area poligonale (`A`)
*   Compressione PDF intelligente con risolutore di dimensione target e anteprima visiva comparativa affiancata
*   Crittografia dei documenti con password AES-256 e cassaforte locale sicura per le password
*   Strumento clona e toppa (`C`) con campionamento pulito dello sfondo e riscrittura diretta del testo (`Enter` / `T`)
*   Guida rapida interattiva e manuale con 4 schede, scorciatoie degli strumenti e filtro di ricerca in tempo reale (`F1` / `Ctrl+F`)
*   Creazione di file PDF con dimensioni pagina personalizzate e conversione automatica delle unità (mm, cm, in, pt, px)
*   Apertura e visualizzazione di file PDF
*   Unione di file PDF con riordinamento visuale tramite trascinamento
*   Selezione di blocchi di testo esistenti all'interno della pagina
*   Modifica ed eliminazione del testo selezionato
*   Aggiunta di nuovi blocchi di testo
*   Inserimento di immagini con conservazione della trasparenza alfa
*   Supporto di famiglie tipografiche e spessori con il motore Linux Fontconfig (`fc-match`)
*   Spostamento e riposizionamento degli elementi nel PDF
*   Personalizzazione di font, dimensione, colore e decorazioni
*   Selezione granulare parola per parola ed evidenziazione precisa
*   Aggiunta di forme vettoriali (Rettangoli, Ellissi, Segni di spunta, Croci)
*   Tracciamento a mano libera con Penna ed Evidenziatore con smoothing di Bézier e scalatura vettoriale
*   Caratteri speciali e simboli
*   Salvataggio dei file PDF modificati e Salvataggio rapido (`Ctrl + S`)
*   Esportazione di PDF in DOCX, PPTX, ODT, ODP e TXT con il motore nativo anyconvert
*   Salvataggio sicuro (Safe Save) e Modalità limitata (Modalità sicura)
*   Cronologia Annulla / Ripristina multilivello (`Ctrl + Z` / `Ctrl + Y`)
*   Zoom focale di precisione centrato sul puntatore (`Ctrl + Rotellina` e `Ctrl + + / - / 0`)
*   Aggiunta/rimozione di pagine e rotazione a 90 gradi nei file PDF
*   Salvataggio sicuro (Safe Save)
*   Modalità protetta (Safe Mode)
*   Cronologia completa Annulla/Ripeti multi-livello (`Ctrl + Z` / `Ctrl + Y`)
*   Zoom focale centrato sul cursore (`Ctrl + Rotella` e `Ctrl + + / - / 0`)
*   Aggiunta e rimozione di pagine nei documenti PDF

### Esportazione nativa di documenti (anyconvert)

word-sys's PDF Editor include il motore in puro Python [anyconvert](https://github.com/word-sys/anyconvert) ([PyPI](https://pypi.org/project/anyconvert/)) per esportare file PDF senza dipendenze esterne come LibreOffice.

Formati supportati:
*   **Microsoft Word (`.docx`)**
*   **Microsoft PowerPoint (`.pptx`)**
*   **Testo OpenDocument (`.odt`)**
*   **Presentazione OpenDocument (`.odp`)**
*   **Testo semplice (`.txt`)**

Modalità di conversione:
*   **Area di disegno precisa al pixel (`mode='canvas'`)**: Mantiene le esatte posizioni visive 1:1 di testo, forme e immagini. Consigliata per PDF modificati.
*   **Flusso semantico (`mode='flow'`)**: Ricostruisce titoli, paragrafi e flusso di testo scorrevole.

anyconvert può anche essere eseguito direttamente da riga di comando:
```bash
anyconvert input.pdf -f docx -m canvas -o output.docx
```

---

## Installazione

Sono disponibili diverse modalità di installazione per word-sys's PDF Editor:

### 1. Flatpak / Flathub (Metodo consigliato)

word-sys's PDF Editor è disponibile ufficialmente su [Flathub](https://flathub.org/apps/io.github.word_sys.word-sys-pdf-editor).

<a href="https://flathub.org/apps/io.github.word_sys.word-sys-pdf-editor"><img src="https://dl.flathub.org/assets/badges/flathub-badge-en.svg" alt="Download on Flathub" width="190"/></a>

Installazione tramite Flatpak:
```bash
flatpak install flathub io.github.word_sys.word-sys-pdf-editor
```

Avviare l'applicazione:
```bash
flatpak run io.github.word_sys.word-sys-pdf-editor
```

---

### 2. Pacchetto Debian / Ubuntu / Pardus (.deb)

Il metodo di installazione pacchetti più immediato per le distribuzioni basate su Debian, Ubuntu e Pardus.

1.  Scaricare il pacchetto `.deb` più recente dalla pagina [**Versioni GitHub**](https://github.com/word-sys/word-sys-pdf-editor/releases). Il nome del file è `word-sys-pdf-editor_1.12.0_amd64.deb` (oppure `_arm64.deb` per ARM64).

    > [!TIP]
    > **Utilizzare la versione 1.12.0** per garantire stabilità: cercare `word-sys-pdf-editor_1.12.0_amd64.deb` nella pagina dei rilasci.

2.  Aprire un terminale nella cartella in cui è stato salvato il pacchetto `.deb`.
3.  Eseguire il comando di installazione:
    ```bash
    sudo apt update
    sudo apt install ./word-sys-pdf-editor_1.12.0_amd64.deb
    ```
    *(Nota: sostituire `word-sys-pdf-editor_1.12.0_amd64.deb` con il nome file effettivo se differente.)*
4.  Qualora si riscontrino errori di dipendenze, eseguire il comando correttivo:
    ```bash
    sudo apt --fix-broken install
    ```
5.  Al termine dell'installazione, avviare word-sys's PDF Editor dal menu applicazioni del desktop.

---

### 3. Pacchetto AppImage e Archivio binario

Questo formato è utilizzabile universalmente su qualsiasi distribuzione Linux.

1.  Scaricare il file `.AppImage` o `*-linux-*.tar.gz` dalla pagina [**Versioni GitHub**](https://github.com/word-sys/word-sys-pdf-editor/releases) (`word-sys-pdf-editor-x86_64.AppImage` o `word-sys-pdf-editor-linux-x86_64.tar.gz`).

    > **Utilizzare la versione 1.12.0** per la migliore affidabilità: fare riferimento al tag `v1.12.0`.

#### A. Installazione AppImage

1. Aprire il terminale nella cartella contenente `word-sys-pdf-editor-x86_64.AppImage`.

2. Rendere il file eseguibile:
    ```bash
    chmod +x word-sys-pdf-editor-x86_64.AppImage
    ```

3. Fare doppio clic sul file o avviarlo da terminale:
    ```bash
    ./word-sys-pdf-editor-x86_64.AppImage
    ```

#### B. Installazione archivio binario (tar.gz)

1. Aprire il terminale nella directory in cui si trova `word-sys-pdf-editor-linux-x86_64.tar.gz`.

2. Estrarre l'archivio:
    ```bash
    tar -xzf word-sys-pdf-editor-linux-x86_64.tar.gz
    ```

3. Entrare nella cartella estratta:
    ```bash
    cd AppDir
    ```

4. Rendere eseguibile AppRun:
    ```bash
    chmod +x AppRun
    ```

5. Avviare l'applicazione:
    ```bash
    ./AppRun
    ```

---

### 4. Installazione manuale (Per sviluppatori o compilazione da codice sorgente)

Adatto agli utenti che preferiscono eseguire l'applicazione dal codice sorgente o contribuire al progetto.

> [!TIP]
> Per un ambiente stabile clonare il tag **v1.12.0**. Per testare i cambiamenti più recenti clonare il ramo `main` (potrebbe essere meno stabile).

---

#### Pardus 23.4, Debian 12 e Ubuntu < 24.04 — Installazione manuale

1.  **Installare i pacchetti richiesti:**
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip python3-venv \
                     python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libgirepository1.0-dev \
                     python3-numpy python3-cryptography \
                     python3-dev libcairo2-dev build-essential \
                     fonts-noto-core fonts-liberation2
    ```

2.  **Scaricare il codice sorgente:**

    **Consigliato (versione stabile v1.12.0):**
    ```bash
    git clone --branch v1.12.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Per test / sviluppo recente:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

3.  **Creare e attivare l'ambiente virtuale (Consigliato):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
    *(Usare `deactivate` per uscire dall'ambiente virtuale in seguito.)*

4.  **Installare le dipendenze Python:**
    ```bash
    pip install "PyMuPDF>=1.24.0,<2.0.0" numpy "anyconvert>=0.1.11" "cryptography>=41.0.0" "Pillow>=9.0.0" "pyhanko[image-support,opentype]>=0.25.0" "pyhanko-certvalidator>=0.24.0" "python-pkcs11>=0.7.0" "asn1crypto>=1.5.1" certifi pygobject==3.50.0
    ```

5.  **Avviare l'applicazione:**
    ```bash
    python3 run-editor.py
    ```

---

#### Ubuntu 24.04+, Debian 13 Trixie — Installazione manuale

1.  **Installare i pacchetti richiesti:**
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip python3-venv \
                     python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libgirepository-2.0-dev \
                     python3-numpy python3-cryptography \
                     python3-dev libcairo2-dev build-essential \
                     fonts-noto-core fonts-liberation2
    ```

2.  **Scaricare il codice sorgente:**

    **Consigliato (versione stabile v1.12.0):**
    ```bash
    git clone --branch v1.12.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Per test / sviluppo recente:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

3.  **Creare e attivare l'ambiente virtuale:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

4.  **Installare le dipendenze Python:**
    ```bash
    pip install "PyMuPDF>=1.24.0,<2.0.0" numpy "anyconvert>=0.1.11" "cryptography>=41.0.0" "Pillow>=9.0.0" "pyhanko[image-support,opentype]>=0.25.0" "pyhanko-certvalidator>=0.24.0" "python-pkcs11>=0.7.0" "asn1crypto>=1.5.1" certifi pygobject
    ```

5.  **Avviare l'applicazione:**
    ```bash
    python3 run-editor.py
    ```

---

#### Arch Linux e Derivate — Installazione manuale

1.  **Scaricare il codice sorgente:**

    **Consigliato (versione stabile v1.12.0):**
    ```bash
    git clone --branch v1.12.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Per test / sviluppo recente:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```


2.  **Creare e attivare l'ambiente virtuale:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Installare le dipendenze Python:**
    ```bash
    pip install "PyMuPDF>=1.24.0,<2.0.0" numpy "anyconvert>=0.1.11" "cryptography>=41.0.0" "Pillow>=9.0.0" "pyhanko[image-support,opentype]>=0.25.0" "pyhanko-certvalidator>=0.24.0" "python-pkcs11>=0.7.0" "asn1crypto>=1.5.1" certifi pygobject
    ```

4.  **Avviare l'applicazione:**
    ```bash
    python3 run-editor.py
    ```

---

#### Arch Linux e Derivate — Da AUR

#### QUESTI PACCHETTI NON SONO CREATI NÉ GESTITI DALL'AUTORE DEL PROGETTO. VERIFICARNE I DETTAGLI SU AUR PRIMA DELL'INSTALLAZIONE. PER QUALSIASI PROBLEMA RELATIVO AD AUR CONTATTARE I MANUTENTORI DEL RISPETTIVO PACCHETTO. I PACCHETTI UFFICIALI SONO PUBBLICATI SU GITHUB ACTIONS NELLA PAGINA RELEASES.

1.  **Scaricamento, compilazione e installazione:**

    ```bash
    git clone https://aur.archlinux.org/word-sys-pdf-editor
    cd word-sys-pdf-editor
    makepkg -sfi
    ```

    Tramite AUR helper `yay`:
    ```bash
    yay -S word-sys-pdf-editor
    ```

    Oppure con `paru`:
    ```bash
    paru -S word-sys-pdf-editor
    ```

    Oppure con il pacchetto binario compilato `-bin` su AUR:
    ```bash
    yay -S word-sys-pdf-editor-bin
    ```
    oppure
    ```bash
    paru -S word-sys-pdf-editor-bin
    ```


2.  **Avviare l'applicazione:**
    ```bash
    word-sys-pdf-editor
    ```

---

## Segnalazione bug e commenti

Per segnalare problemi, richiedere nuove funzionalità o inviare suggerimenti generali, utilizzare la sezione [**GitHub Issues**](https://github.com/word-sys/word-sys-pdf-editor/issues).

---

## Come contribuire

word-sys's PDF Editor è un progetto open source aperto ai contributi di tutti. Per partecipare:

1.  Eseguire il fork del repository.
2.  Creare un nuovo ramo (`git checkout -b feature/nuova-funzionalita` o `git checkout -b fix/risoluzione-bug`).
3.  Salvare le modifiche ed eseguire il commit (`git commit -am 'Aggiunta nuova funzionalita'`).
4.  Inviare il ramo al proprio repository GitHub (`git push origin feature/nuova-funzionalita`).
5.  Inviare una Pull Request (PR).

---

## Licenza

Questo software è distribuito con licenza [**GNU General Public License v3.0 or later**](LICENSE).
