# word-sys's PDF Editor
<img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/word_sys_pdf_editor/img/f-pv1.svg" width="256" height="256"/>

**word-sys's PDF Editor** è uno strumento semplice e intuitivo sviluppato per Pardus, Debian e altre distribuzioni Linux, focalizzato sulla modifica di testo, immagini e oggetti nei documenti PDF. Sviluppato da zero nello spirito di #MilliTeknolojiHamlesi e TEKNOFEST 2025 per colmare la necessità di un editor PDF libero, semplice e open source nell'ecosistema Linux, word-sys's PDF Editor si rivolge sia a utenti aziendali sia a privati. Svolge la maggior parte delle operazioni essenziali offerte dagli editor a pagamento, include numerose funzioni di facile impiego ed è stato vincitore del **PRIMO POSTO** al concorso di sviluppo Pardus TEKNOFEST 2025.

Sviluppatore: **Barın Güzeldemirci (word-sys)**  
Licenza: **GPL-3.0-or-later**

---

> [!TIP]
> **Versione stabile consigliata: v1.11.0** — Per la massima stabilità operativa, si consiglia vivamente l'utilizzo della versione **1.11.0**. Consultare le sezioni di installazione seguenti per tutti i dettagli.

---

## Schermate

| **Area di modifica e annotazione PDF** | **Schermata iniziale e gestione documenti** |
| :---: | :---: |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot1.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot1.png" alt="Area di modifica PDF" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot2.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot2.png" alt="Schermata iniziale" width="450"/></a> |
| **Creazione di un nuovo documento** | **Guida rapida interattiva e manuale d'uso** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot3.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot3.png" alt="Nuovo documento" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot4.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot4.png" alt="Guida rapida e manuale" width="450"/></a> |

---

## Funzionalità principali

*   Creazione di file PDF con dimensioni pagina personalizzate e conversione automatica delle unità (mm, cm, in, pt, px)
*   Apertura e visualizzazione di file PDF
*   Unione di file PDF (Merge)
*   Guida rapida interattiva e prontuario scorciatoie da tastiera (`F1`)
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
*   Salvataggio dei file PDF modificati
*   Salvataggio rapido (`Ctrl + S`)
*   Esportazione di PDF in DOCX o ODT (richiede LibreOffice) e formato testo TXT
*   Interfaccia moderna con riordinamento delle pagine tramite trascinamento delle miniature
*   Salvataggio sicuro (Safe Save)
*   Modalità protetta (Safe Mode)
*   Cronologia completa Annulla/Ripeti multi-livello (`Ctrl + Z` / `Ctrl + Y`)
*   Zoom focale centrato sul cursore (`Ctrl + Rotella` e `Ctrl + + / - / 0`)
*   Aggiunta e rimozione di pagine nei documenti PDF

---

## Installazione

Sono disponibili diverse modalità di installazione per word-sys's PDF Editor:

### 1. Installazione automatica (Metodo consigliato)

Il metodo più immediato per le distribuzioni basate su Debian, Ubuntu e Pardus.

1.  Scaricare il pacchetto `.deb` più recente dalla pagina [**Versioni GitHub**](https://github.com/word-sys/word-sys-pdf-editor/releases). Il nome tipico del file è `word-sys-pdf-editor_1.11.0_all.deb`.

    > [!TIP]
    > **Utilizzare la versione 1.11.0** per garantire stabilità: cercare `word-sys-pdf-editor_1.11.0_all.deb` nella pagina dei rilasci.

2.  Aprire un terminale nella cartella in cui è stato salvato il pacchetto `.deb`.
3.  Eseguire il comando di installazione:
    ```bash
    sudo apt update
    sudo apt install ./word-sys-pdf-editor_1.11.0_all.deb
    ```
    *(Nota: sostituire `word-sys-pdf-editor_1.11.0_all.deb` con il nome file effettivo se differente.)*
4.  Qualora si riscontrino errori di dipendenze, eseguire il comando correttivo:
    ```bash
    sudo apt --fix-broken install
    ```
5.  Al termine dell'installazione, avviare word-sys's PDF Editor dal menu applicazioni del desktop.

---

### 2. Pacchetto AppImage e Archivio binario (Secondo metodo consigliato)

Questo formato è utilizzabile universalmente su qualsiasi distribuzione Linux.

1.  Scaricare il file `.AppImage` o `*-linux-x64.tar.gz` dalla pagina [**Versioni GitHub**](https://github.com/word-sys/word-sys-pdf-editor/releases).

    > **Utilizzare la versione 1.11.0** per la migliore affidabilità: fare riferimento al tag `v1.11.0`.

#### A. Installazione AppImage

1. Aprire il terminale nella cartella contenente `word-sys-pdf-editor.AppImage`.

2. Rendere il file eseguibile:
    ```bash
    chmod +x word-sys-pdf-editor.AppImage
    ```

3. Fare doppio clic sul file o avviarlo da terminale:
    ```bash
    ./word-sys-pdf-editor.AppImage
    ```

#### B. Installazione archivio binario (tar.gz)

1. Aprire il terminale nella directory in cui si trova `word-sys-pdf-editor-linux-x64.tar.gz`.

2. Estrarre l'archivio:
    ```bash
    tar -xzf word-sys-pdf-editor-linux-x64.tar.gz
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

### 3. Installazione manuale (Per sviluppatori o compilazione da codice sorgente)

Adatto agli utenti che preferiscono eseguire l'applicazione dal codice sorgente o contribuire al progetto.

> [!TIP]
> Per un ambiente stabile clonare il tag **v1.11.0**. Per testare i cambiamenti più recenti clonare il ramo `main` (potrebbe essere meno stabile).

---

#### Pardus 23.4, Debian 12 e Ubuntu < 24.04 — Installazione manuale

1.  **Installare i pacchetti richiesti:**
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip python3-venv \
                     python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libgirepository1.0-dev \
                     python3-numpy \
                     python3-dev libcairo2-dev build-essential \
                     fonts-noto-core fonts-liberation2
    ```
    *Opzionale (per esportazione in DOCX):*
    ```bash
    sudo apt install libreoffice-common
    ```

2.  **Scaricare il codice sorgente:**

    **Consigliato (versione stabile v1.11.0):**
    ```bash
    git clone --branch v1.11.0 https://github.com/word-sys/word-sys-pdf-editor.git
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
    pip install PyMuPDF numpy pygobject==3.50.0
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
                     python3-numpy \
                     python3-dev libcairo2-dev build-essential \
                     fonts-noto-core fonts-liberation2
    ```
    *Opzionale (per esportazione in DOCX):*
    ```bash
    sudo apt install libreoffice-common
    ```

2.  **Scaricare il codice sorgente:**

    **Consigliato (versione stabile v1.11.0):**
    ```bash
    git clone --branch v1.11.0 https://github.com/word-sys/word-sys-pdf-editor.git
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
    pip install PyMuPDF numpy pygobject
    ```

5.  **Avviare l'applicazione:**
    ```bash
    python3 run-editor.py
    ```

---

#### Arch Linux e Derivate — Installazione manuale

1.  **Scaricare il codice sorgente:**

    **Consigliato (versione stabile v1.11.0):**
    ```bash
    git clone --branch v1.11.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Per test / sviluppo recente:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    *Opzionale (per esportazione in DOCX):*
    ```bash
    sudo pacman -S libreoffice-fresh
    ```

2.  **Creare e attivare l'ambiente virtuale:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Installare le dipendenze Python:**
    ```bash
    pip install PyMuPDF numpy pygobject
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

    *Opzionale (per esportazione in DOCX):*
    ```bash
    sudo pacman -S libreoffice-fresh
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
