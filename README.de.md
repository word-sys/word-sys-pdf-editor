**Sprachen:** [English](README.md) | [Türkçe](README.tr.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [Italiano](README.it.md) | [Русский](README.ru.md)

# word-sys's PDF Editor
<img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/word_sys_pdf_editor/img/f-pv1.svg" width="256" height="256"/>

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPLv3+-blue.svg)](LICENSE)
[![GitHub All Releases](https://img.shields.io/github/downloads/word-sys/word-sys-pdf-editor/total)](https://github.com/word-sys/word-sys-pdf-editor/releases)
[![Flathub](https://img.shields.io/flathub/v/io.github.word_sys.word-sys-pdf-editor?logo=flathub)](https://flathub.org/apps/io.github.word_sys.word-sys-pdf-editor)

**word-sys's PDF Editor** ist ein einfaches und benutzerfreundliches Werkzeug für Pardus, Debian und andere Linux-Distributionen, das auf das Bearbeiten von Text-, Bild- und Objektinhalten in PDF-Dateien spezialisiert ist. Entwickelt von Grund auf im Geiste von #MilliTeknolojiHamlesi und TEKNOFEST 2025, um den Bedarf an einem einfachen, freien und quelloffenen PDF-Editor im Linux-Ökosystem zu decken, richtet sich word-sys's PDF Editor sowohl an Unternehmen als auch an Privatanwender. Er erledigt die meisten wichtigen und gängigen Aufgaben kostenpflichtiger PDF-Editoren, bietet zahlreiche benutzerfreundliche Funktionen und wurde mit dem **1. PLATZ** beim TEKNOFEST 2025 Pardus-Entwicklungswettbewerb ausgezeichnet.

Entwickler: **Barın Güzeldemirci (word-sys)**  
Lizenz: **GPL-3.0-or-later**

---

> [!TIP]
> **Empfohlene stabile Version: v1.12.0** — Für die bestmögliche Stabilität wird dringend empfohlen, Version **1.12.0** zu verwenden. Details zur Installation finden Sie in den nachfolgenden Abschnitten.

---

## Bildschirmfotos

| **PDF-Bearbeitungsbereich & Fortlaufendes Scrollen** | **Startbildschirm & Dokumenten-Hub** |
| :---: | :---: |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot1.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot1.png" alt="PDF-Bearbeitungsbereich & Fortlaufendes Scrollen" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot2.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot2.png" alt="Startbildschirm & Dokumenten-Hub" width="450"/></a> |
| **Dialog zum Erstellen neuer Dokumente** | **Interaktive Kurzanleitung & Handbuch** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot3.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot3.png" alt="Dialog zum Erstellen neuer Dokumente" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot4.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot4.png" alt="Interaktive Kurzanleitung & Handbuch" width="450"/></a> |
| **Visueller Bereich zum Zusammenführen** | **Multi-Dokument-Tabs & Verifizierter Signaturbalken** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot5.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot5.png" alt="Visueller Bereich zum Zusammenführen" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot6.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot6.png" alt="Multi-Dokument-Tabs & Signaturbalken" width="450"/></a> |
| **Kennwort-Entsperrdialog für verschlüsselte Dokumente** | **PAdES-Digitalsignatur & Hardware-Token-Dialog** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot7.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot7.png" alt="Kennwort-Entsperrdialog für verschlüsselte Dokumente" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot8.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot8.png" alt="PAdES-Digitalsignatur & Hardware-Token-Dialog" width="450"/></a> |
| **Kryptografische Signaturprüfung & Zertifikatsdetails** | **OCR-Texterkennung & Textebenen-Inspektor** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot9.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot9.png" alt="Kryptografische Signaturprüfung & Zertifikatsdetails" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot10.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot10.png" alt="OCR-Texterkennung & Textebenen-Inspektor" width="450"/></a> |

---

## Hauptfunktionen

*   Fortlaufendes vertikales Seitenscrollen mit Viewport-Culling, direktionalem Prefetching und fraktionaler Skalierung (HiDPI / 4K / Retina)
*   Interaktive AcroForms-Engine: Ausfüllen von Textfeldern, Kontrollkästchen, Optionsfeldern und Dropdowns im Ansichtsmodus sowie Vektor-Flattening
*   Interaktives Formular-Erstellungswerkzeug (`B`) zum Erstellen, Ausrichten und Konfigurieren neuer AcroForm-Felder
*   PAdES-Baseline-Digitalsignaturen mit PKCS#12-Zertifikaten und PKCS#11-Hardware-Sicherheits-Tokens / Smartcards (HSMs)
*   RFC 3161 kryptografischer Zeitstempeldienst mit konfigurierbarer TSA-Authentifizierung
*   Nicht-blockierende Signaturprüfung beim Öffnen mit interaktivem Statusbalken und X.509-Zertifikatsinspektor
*   Dauerhafte kryptografische Schwärzung (`Shift+R`) mit automatischer PII-Erkennung (Kreditkarten, E-Mails, Telefone, Regex) und Tiefenbereinigung
*   Multithreaded Streaming-OCR-Texterkennung mit Live-Fortschrittsanzeige und 7 neuronalen Sprachmodellen
*   OCR-Bereichswerkzeug (`O`) zur sofortigen Textextraktion und Textebenen-Zuverlässigkeitsinspektor (`Ctrl+Alt+O`)
*   Haftnotizen mit Farben, Autoren-Metadaten, Antwort-Threads und Anmerkungs-Seitenleiste
*   Vektor-Genehmigungsstempel (Genehmigt, Vertraulich, Entwurf, dynamische Benutzer-/Datumsstempel)
*   Präzisions-Messwerkzeuge: Lineal zur Abstandsmessung (`U`) mit Skalierung und Polygon-Flächenmessung (`A`)
*   PDF-Komprimierung mit Zielgrößen-Optimierer und direktem visuellen Qualitätsvergleich
*   AES-256-Dokumentenverschlüsselung und lokaler sicherer Passwort-Tresor
*   Klon- & Ausbessern-Werkzeug (`C`) mit Hintergrund-Abtastung und Sofort-Überschreiben (`Enter` / `T`)
*   Interaktive Kurzanleitung & Handbuch mit 4 Tabs, Tastaturkürzeln und Live-Suchfilter (`F1` / `Ctrl+F`)
*   PDF-Dateien mit anpassbaren Seitenabmessungen und automatischer Einheitenumrechnung erstellen (mm, cm, in, pt, px)
*   PDF-Dateien öffnen und anzeigen
*   PDF-Dateien zusammenführen mit visueller Seitenanordnung per Drag-and-Drop
*   Bestehende Textblöcke auf einer Seite auswählen
*   Ausgewählten Text bearbeiten oder löschen
*   Neue Textblöcke zu Seiten hinzufügen
*   Bilder mit Alpha-Transparenzerhaltung einfügen
*   Unterstützung von Schriftfamilien und Schriftbreiten über die Linux Fontconfig (`fc-match`)-Engine
*   Objekte innerhalb des Dokuments verschieben und neu positionieren
*   Schriftart, -größe, -farbe und Textauszeichnungen anpassen
*   Granulare Wortauswahl und präzise Textmarkierung
*   Vektorformen hinzufügen (Rechtecke, Ellipsen, Häkchen, Kreuze)
*   Freihand-Stift und Textmarker mit Bézier-Glättung und Vektorskalierung
*   Sonderzeichen und Symbole
*   Bearbeitete PDF-Dateien speichern und Schnellspeichern (`Strg + S`)
*   PDF-Export in DOCX-, PPTX-, ODT-, ODP- und TXT-Formate mit der nativen anyconvert-Engine
*   Sicheres Speichern (Safe Save) und Eingeschränkter Modus (Sicherer Modus)
*   Vollständiger mehrstufiger Rückgängig-/Wiederholen-Verlauf (`Strg + Z` / `Strg + Y`)
*   Präzises zeigerzentriertes fokales Zoomen (`Strg + Mausrad` und `Strg + + / - / 0`)
*   Seiten in PDFs hinzufügen, entfernen und um 90 Grad drehen
*   Sicheres Speichern (Safe Save)
*   Eingeschränkter Modus (Safe Mode)
*   Vollständige mehrstufige Rückgängig-/Wiederholen-Historie (`Strg + Z` / `Strg + Y`)
*   Präziser zeigerzentrierter Fokus-Zoom (`Strg + Mausrad` und `Strg + + / - / 0`)
*   Seiten in PDF-Dokumenten hinzufügen oder löschen

### Nativer Dokumentenexport (anyconvert)

word-sys's PDF Editor verwendet die reine Python-Engine [anyconvert](https://github.com/word-sys/anyconvert) ([PyPI](https://pypi.org/project/anyconvert/)) für den Dokumentenexport ohne externe Abhängigkeiten wie LibreOffice.

Unterstützte Formate:
*   **Microsoft Word (`.docx`)**
*   **Microsoft PowerPoint (`.pptx`)**
*   **OpenDocument-Text (`.odt`)**
*   **OpenDocument-Präsentation (`.odp`)**
*   **Einfacher Text (`.txt`)**

Konvertierungsmodi:
*   **Pixelgenaue Leinwand (`mode='canvas'`)**: Bewahrt die exakte visuelle 1:1-Position von Text, Formen und Bildern. Empfohlen für bearbeitete PDFs.
*   **Semantischer Fluss (`mode='flow'`)**: Rekonstruiert Überschriften, Absätze und fortlaufenden Textfluss.

anyconvert kann auch direkt über die Befehlszeile ausgeführt werden:
```bash
anyconvert input.pdf -f docx -m canvas -o output.docx
```

---

## Installation

Es gibt mehrere Möglichkeiten, word-sys's PDF Editor auf Ihrem System zu installieren:

### 1. Flatpak / Flathub (Empfohlene Methode)

word-sys's PDF Editor ist offiziell auf [Flathub](https://flathub.org/apps/io.github.word_sys.word-sys-pdf-editor) verfügbar.

<a href="https://flathub.org/apps/io.github.word_sys.word-sys-pdf-editor"><img src="https://dl.flathub.org/assets/badges/flathub-badge-en.svg" alt="Download on Flathub" width="190"/></a>

Installation über Flatpak:
```bash
flatpak install flathub io.github.word_sys.word-sys-pdf-editor
```

Anwendung starten:
```bash
flatpak run io.github.word_sys.word-sys-pdf-editor
```

---

### 2. Debian / Ubuntu / Pardus Paket (.deb)

Dies ist der einfachste Paket-Installationsweg für Debian-, Ubuntu- und Pardus-basierte Distributionen.

1.  Laden Sie das neueste `.deb`-Paket von der [**GitHub Releases**](https://github.com/word-sys/word-sys-pdf-editor/releases)-Seite herunter. Die Datei heißt üblicherweise `word-sys-pdf-editor_1.12.0_amd64.deb` (oder `_arm64.deb`).

    > [!TIP]
    > **Verwenden Sie Version 1.12.0** für die stabilste Nutzung: Suchen Sie nach `word-sys-pdf-editor_1.12.0_amd64.deb` auf der Releases-Seite.

2.  Öffnen Sie ein Terminal in dem Verzeichnis, in das Sie die `.deb`-Datei heruntergeladen haben.
3.  Führen Sie folgenden Befehl aus, um das Paket zu installieren:
    ```bash
    sudo apt update
    sudo apt install ./word-sys-pdf-editor_1.12.0_amd64.deb
    ```
    *(Hinweis: Ersetzen Sie `word-sys-pdf-editor_1.12.0_amd64.deb` durch den genauen Dateinamen, falls dieser abweicht.)*
4.  Falls während der Installation ein Abhängigkeitsfehler auftritt, führen Sie folgenden Befehl aus, um fehlende Abhängigkeiten zu beheben:
    ```bash
    sudo apt --fix-broken install
    ```
5.  Nach Abschluss der Installation können Sie word-sys's PDF Editor über Ihr Anwendungsmenü starten.

---

### 3. AppImage und Binär-Paket

Diese Methode ist sofort auf allen Linux-Distributionen einsatzbereit.

1.  Laden Sie das `.AppImage` oder `*-linux-*.tar.gz`-Paket von der [**GitHub Releases**](https://github.com/word-sys/word-sys-pdf-editor/releases)-Seite herunter (`word-sys-pdf-editor-x86_64.AppImage` oder `word-sys-pdf-editor-linux-x86_64.tar.gz`).

    > **Verwenden Sie Version 1.12.0** für die stabilste Nutzung: Achten Sie auf das Tag `v1.12.0` auf der Releases-Seite.

#### A. AppImage-Installation

1. Öffnen Sie ein Terminal im Verzeichnis mit der Datei `word-sys-pdf-editor-x86_64.AppImage`.

2. Machen Sie die Datei ausführbar:
    ```bash
    chmod +x word-sys-pdf-editor-x86_64.AppImage
    ```

3. Starten Sie das AppImage per Doppelklick oder im Terminal:
    ```bash
    ./word-sys-pdf-editor-x86_64.AppImage
    ```

#### B. Binär-Release-Installation (tar.gz)

1. Öffnen Sie ein Terminal im Verzeichnis mit der Datei `word-sys-pdf-editor-linux-x86_64.tar.gz`.

2. Entpacken Sie das Archiv:
    ```bash
    tar -xzf word-sys-pdf-editor-linux-x86_64.tar.gz
    ```

3. Wechseln Sie in das entpackte Verzeichnis:
    ```bash
    cd AppDir
    ```

4. Machen Sie AppRun ausführbar:
    ```bash
    chmod +x AppRun
    ```

5. Starten Sie die Anwendung:
    ```bash
    ./AppRun
    ```

---

### 4. Manuelle Installation (Für Entwickler oder Quelltext-Builds)

Diese Methode eignet sich für Benutzer, die die Anwendung direkt aus dem Quellcode ausführen oder zur Entwicklung beitragen möchten.

> [!TIP]
> Verwenden Sie für eine stabile Version das Tag **v1.12.0** beim Klonen. Wenn Sie neueste Änderungen testen möchten, können Sie direkt den Branch `main` klonen (dieser kann jedoch weniger stabil sein).

---

#### Pardus 23.4, Debian 12 und Ubuntu < 24.04 — Manuelle Installation

1.  **Erforderliche Abhängigkeiten installieren:**
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip python3-venv \
                     python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libgirepository1.0-dev \
                     python3-numpy python3-cryptography \
                     python3-dev libcairo2-dev build-essential \
                     fonts-noto-core fonts-liberation2
    ```

2.  **Quellcode herunterladen:**

    **Empfohlen (stabil v1.12.0):**
    ```bash
    git clone --branch v1.12.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Für Tests / neuesten Entwicklungsstand:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

3.  **Virtuelle Umgebung erstellen und aktivieren (Empfohlen):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
    *(Mit `deactivate` können Sie die virtuelle Umgebung später verlassen.)*

4.  **Python-Abhängigkeiten installieren:**
    ```bash
    pip install "PyMuPDF>=1.24.0,<2.0.0" numpy "anyconvert>=0.1.11" "cryptography>=41.0.0" "Pillow>=9.0.0" "pyhanko[image-support,opentype]>=0.25.0" "pyhanko-certvalidator>=0.24.0" "python-pkcs11>=0.7.0" "asn1crypto>=1.5.1" certifi pygobject==3.50.0
    ```

5.  **Anwendung starten:**
    ```bash
    python3 run-editor.py
    ```

---

#### Ubuntu 24.04+, Debian 13 Trixie — Manuelle Installation

1.  **Erforderliche Abhängigkeiten installieren:**
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip python3-venv \
                     python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libgirepository-2.0-dev \
                     python3-numpy python3-cryptography \
                     python3-dev libcairo2-dev build-essential \
                     fonts-noto-core fonts-liberation2
    ```

2.  **Quellcode herunterladen:**

    **Empfohlen (stabil v1.12.0):**
    ```bash
    git clone --branch v1.12.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Für Tests / neuesten Entwicklungsstand:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

3.  **Virtuelle Umgebung erstellen und aktivieren:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

4.  **Python-Abhängigkeiten installieren:**
    ```bash
    pip install "PyMuPDF>=1.24.0,<2.0.0" numpy "anyconvert>=0.1.11" "cryptography>=41.0.0" "Pillow>=9.0.0" "pyhanko[image-support,opentype]>=0.25.0" "pyhanko-certvalidator>=0.24.0" "python-pkcs11>=0.7.0" "asn1crypto>=1.5.1" certifi pygobject
    ```

5.  **Anwendung starten:**
    ```bash
    python3 run-editor.py
    ```

---

#### Arch Linux und Derivate — Manuelle Installation

1.  **Quellcode herunterladen:**

    **Empfohlen (stabil v1.12.0):**
    ```bash
    git clone --branch v1.12.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Für Tests / neuesten Entwicklungsstand:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```


2.  **Virtuelle Umgebung erstellen und aktivieren:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Python-Abhängigkeiten installieren:**
    ```bash
    pip install "PyMuPDF>=1.24.0,<2.0.0" numpy "anyconvert>=0.1.11" "cryptography>=41.0.0" "Pillow>=9.0.0" "pyhanko[image-support,opentype]>=0.25.0" "pyhanko-certvalidator>=0.24.0" "python-pkcs11>=0.7.0" "asn1crypto>=1.5.1" certifi pygobject
    ```

4.  **Anwendung starten:**
    ```bash
    python3 run-editor.py
    ```

---

#### Arch Linux und Derivate — Über AUR

#### DIESE PAKETE WERDEN NICHT VOM PROJEKTAUTOR ERSTELLT ODER GEPFLEGT. BITTE ÜBERPRÜFEN SIE DIE PAKETE IM AUR VOR DER INSTALLATION. BEI FRAGEN ODER PROBLEMEN MIT DEM AUR-PAKET WENDEN SIE SICH BITTE AN DIE JEWEILIGEN AUR-BETREUER. OFFIZIELLE PAKETE WERDEN ÜBER GITHUB ACTIONS AUF DER RELEASES-SEITE VERÖFFENTLICHT.

1.  **Herunterladen, bauen und installieren:**

    ```bash
    git clone https://aur.archlinux.org/word-sys-pdf-editor
    cd word-sys-pdf-editor
    makepkg -sfi
    ```

    Mit dem AUR-Hilfsprogramm `yay`:
    ```bash
    yay -S word-sys-pdf-editor
    ```

    Oder mit `paru`:
    ```bash
    paru -S word-sys-pdf-editor
    ```

    Oder mit dem vorkompilierten `-bin`-Paket aus dem AUR:
    ```bash
    yay -S word-sys-pdf-editor-bin
    ```
    oder
    ```bash
    paru -S word-sys-pdf-editor-bin
    ```


2.  **Anwendung starten:**
    ```bash
    word-sys-pdf-editor
    ```

---

## Fehlerberichte und Feedback

Wenn Sie auf Fehler stoßen, Vorschläge für neue Funktionen haben oder Feedback geben möchten, nutzen Sie bitte den Bereich [**GitHub Issues**](https://github.com/word-sys/word-sys-pdf-editor/issues).

---

## Mitwirken (Contributing)

word-sys's PDF Editor ist ein Open-Source-Projekt und freut sich über Beiträge! So können Sie mitwirken:

1.  Forken Sie dieses Repository.
2.  Erstellen Sie einen eigenen Branch für eine neue Funktion oder Fehlerbehebung (`git checkout -b feature/neue-funktion` oder `git checkout -b fix/fehlername`).
3.  Nehmen Sie Ihre Änderungen vor und committen Sie diese (`git commit -am 'Neue Funktion hinzugefuegt'`).
4.  Pushen Sie den Branch zu GitHub (`git push origin feature/neue-funktion`).
5.  Erstellen Sie einen Pull Request (PR).

---

## Lizenz

Dieses Projekt ist unter der [**GNU General Public License v3.0 or later**](LICENSE) lizenziert.
