**Langues:** [English](README.md) | [Türkçe](README.tr.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [Italiano](README.it.md) | [Русский](README.ru.md)

# word-sys's PDF Editor
<img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/word_sys_pdf_editor/img/f-pv1.svg" width="256" height="256"/>

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPLv3+-blue.svg)](LICENSE)
[![GitHub All Releases](https://img.shields.io/github/downloads/word-sys/word-sys-pdf-editor/total)](https://github.com/word-sys/word-sys-pdf-editor/releases)

**word-sys's PDF Editor** est un outil simple et convivial développé pour Pardus, Debian et d'autres distributions Linux, dédié à l'édition de texte, d'images et d'objets dans les fichiers PDF. Développé à partir de zéro dans l'esprit de #MilliTeknolojiHamlesi et du TEKNOFEST 2025 pour répondre au besoin d'un éditeur PDF simple, libre et open source dans l'écosystème Linux, word-sys's PDF Editor s'adresse aussi bien aux utilisateurs professionnels qu'aux particuliers. Il prend en charge la plupart des tâches majeures et courantes proposées par les éditeurs PDF payants et offre de nombreuses fonctionnalités faciles à utiliser, tout en étant le lauréat de la **PREMIERE PLACE** au concours de développement Pardus TEKNOFEST 2025.

Développeur : **Barın Güzeldemirci (word-sys)**  
Licence : **GPL-3.0-or-later**

---

> [!TIP]
> **Version stable recommandée : v1.11.0** — Pour une expérience optimale et stable, il est fortement recommandé d'utiliser la version **1.11.0**. Consultez les sections d'installation ci-dessous pour plus de détails.

---

## Captures d'écran

| **Zone d'édition et d'annotation PDF** | **Écran d'accueil et gestionnaire de documents** |
| :---: | :---: |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot1.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot1.png" alt="Zone d'édition PDF" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot2.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot2.png" alt="Écran d'accueil" width="450"/></a> |
| **Création d'un nouveau document** | **Guide interactif et manuel d'utilisation** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot3.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot3.png" alt="Création d'un nouveau document" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot4.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot4.png" alt="Guide interactif et manuel" width="450"/></a> |

---

## Fonctionnalités principales

*   Création de fichiers PDF avec dimensions de page personnalisées et conversion automatique d'unités (mm, cm, in, pt, px)
*   Ouverture et visualisation de fichiers PDF
*   Fusion de documents PDF
*   Guide interactif de prise en main et aide-mémoire des raccourcis clavier (`F1`)
*   Sélection de blocs de texte existants sur une page
*   Modification et suppression du texte sélectionné
*   Ajout de nouveaux blocs de texte sur une page
*   Ajout d'images avec préservation du canal alpha (transparence)
*   Support des polices système et variantes via le moteur Linux Fontconfig (`fc-match`)
*   Déplacement et repositionnement des objets sur le PDF
*   Personnalisation de la police, taille, couleur et décorations (soulignement, etc.)
*   Sélection granulaire au mot près et surlignage précis
*   Ajout de formes vectorielles (Rectangles, Ellipses, Coches de validation, Croix)
*   Tracé à main levée au stylo et surligneur avec lissage de Bézier et mise à l'échelle vectorielle
*   Caractères spéciaux et symboles
*   Enregistrement des PDF modifiés
*   Enregistrement rapide (`Ctrl + S`)
*   Export des PDF vers DOCX ou ODT (nécessite LibreOffice) et formats texte brut TXT
*   Interface intuitive avec réorganisation des pages par glisser-déposer de vignettes
*   Enregistrement sécurisé (Safe Save)
*   Mode restreint (Safe Mode)
*   Système complet d'annulation et de rétablissement multi-niveaux (`Ctrl + Z` / `Ctrl + Y`)
*   Zoom focal centré sur le curseur (`Ctrl + Molette` et `Ctrl + + / - / 0`)
*   Ajout et suppression de pages dans les documents PDF

---

## Installation

Plusieurs méthodes permettent d'installer word-sys's PDF Editor sur votre système :

### 1. Installation automatique (Méthode recommandée)

Cette méthode est la plus simple pour les distributions basées sur Debian/Ubuntu/Pardus.

1.  Téléchargez le dernier paquet `.deb` depuis la page des [**Versions GitHub**](https://github.com/word-sys/word-sys-pdf-editor/releases). Le fichier se nomme généralement `word-sys-pdf-editor_1.11.0_all.deb`.

    > [!TIP]
    > **Utilisez la version 1.11.0** pour une expérience stable : recherchez `word-sys-pdf-editor_1.11.0_all.deb` sur la page des versions.

2.  Ouvrez un terminal dans le dossier où vous avez téléchargé le fichier `.deb`.
3.  Exécutez la commande suivante pour installer le paquet :
    ```bash
    sudo apt update
    sudo apt install ./word-sys-pdf-editor_1.11.0_all.deb
    ```
    *(Remarque : remplacez `word-sys-pdf-editor_1.11.0_all.deb` par le nom exact du fichier téléchargé si différent.)*
4.  Si vous rencontrez une erreur de dépendance, exécutez la commande suivante pour corriger les dépendances manquantes :
    ```bash
    sudo apt --fix-broken install
    ```
5.  Une fois l'installation terminée, vous pouvez lancer word-sys's PDF Editor depuis votre menu d'applications.

---

### 2. Version AppImage et Archive binaire (Deuxième méthode recommandée)

Cette méthode est prête à l'emploi pour toutes les distributions Linux.

1.  Téléchargez le paquet `.AppImage` ou `*-linux-x64.tar.gz` depuis la page des [**Versions GitHub**](https://github.com/word-sys/word-sys-pdf-editor/releases).

    > **Utilisez la version 1.11.0** pour une stabilité optimale : vérifiez l'étiquette `v1.11.0` sur la page des versions.

#### A. Installation AppImage

1. Ouvrez un terminal dans le répertoire contenant le fichier `word-sys-pdf-editor.AppImage`.

2. Rendez-le exécutable :
    ```bash
    chmod +x word-sys-pdf-editor.AppImage
    ```

3. Double-cliquez sur le fichier AppImage ou lancez-le dans le terminal :
    ```bash
    ./word-sys-pdf-editor.AppImage
    ```

#### B. Installation binaire (tar.gz)

1. Ouvrez un terminal dans le répertoire contenant le fichier `word-sys-pdf-editor-linux-x64.tar.gz`.

2. Décompressez l'archive :
    ```bash
    tar -xzf word-sys-pdf-editor-linux-x64.tar.gz
    ```

3. Rendez-vous dans le répertoire extrait :
    ```bash
    cd AppDir
    ```

4. Rendez le script AppRun exécutable :
    ```bash
    chmod +x AppRun
    ```

5. Lancez l'application :
    ```bash
    ./AppRun
    ```

---

### 3. Installation manuelle (Pour développeurs et compilation depuis les sources)

Cette méthode convient aux personnes souhaitant exécuter l'application directement depuis le code source ou contribuer au projet.

> [!TIP]
> Pour une version stable, utilisez l'étiquette **v1.11.0** lors du clonage. Si vous souhaitez tester les dernières modifications de développement, vous pouvez cloner directement la branche `main` (qui peut être moins stable).

---

#### Pardus 23.4, Debian 12, et Ubuntu < 24.04 — Installation manuelle

1.  **Installer les dépendances requises :**
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip python3-venv \
                     python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libgirepository1.0-dev \
                     python3-numpy \
                     python3-dev libcairo2-dev build-essential \
                     fonts-noto-core fonts-liberation2
    ```
    *Optionnel (pour l'export DOCX) :*
    ```bash
    sudo apt install libreoffice-common
    ```

2.  **Télécharger le code source :**

    **Recommandé (stable v1.11.0) :**
    ```bash
    git clone --branch v1.11.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Pour les tests / dernière version de développement :**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

3.  **Créer et activer un environnement virtuel (Recommandé) :**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
    *(Vous pouvez utiliser `deactivate` plus tard pour quitter l'environnement virtuel.)*

4.  **Installer les dépendances Python :**
    ```bash
    pip install PyMuPDF numpy pygobject==3.50.0
    ```

5.  **Lancer l'application :**
    ```bash
    python3 run-editor.py
    ```

---

#### Ubuntu 24.04+, Debian 13 Trixie — Installation manuelle

1.  **Installer les dépendances requises :**
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip python3-venv \
                     python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libgirepository-2.0-dev \
                     python3-numpy \
                     python3-dev libcairo2-dev build-essential \
                     fonts-noto-core fonts-liberation2
    ```
    *Optionnel (pour l'export DOCX) :*
    ```bash
    sudo apt install libreoffice-common
    ```

2.  **Télécharger le code source :**

    **Recommandé (stable v1.11.0) :**
    ```bash
    git clone --branch v1.11.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Pour les tests / dernière version de développement :**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

3.  **Créer et activer un environnement virtuel :**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

4.  **Installer les dépendances Python :**
    ```bash
    pip install PyMuPDF numpy pygobject
    ```

5.  **Lancer l'application :**
    ```bash
    python3 run-editor.py
    ```

---

#### Arch Linux et Dérivées — Installation manuelle

1.  **Télécharger le code source :**

    **Recommandé (stable v1.11.0) :**
    ```bash
    git clone --branch v1.11.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Pour les tests / dernière version de développement :**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    *Optionnel (pour l'export DOCX) :*
    ```bash
    sudo pacman -S libreoffice-fresh
    ```

2.  **Créer et activer un environnement virtuel :**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Installer les dépendances Python :**
    ```bash
    pip install PyMuPDF numpy pygobject
    ```

4.  **Lancer l'application :**
    ```bash
    python3 run-editor.py
    ```

---

#### Arch Linux et Dérivées — Depuis AUR

#### CES PAQUETS NE SONT PAS CRÉÉS NI MAINTENUS PAR L'AUTEUR DU PROJET. VÉRIFIEZ LEUR CONTENU SUR AUR AVANT INSTALLATION. POUR TOUT PROBLÈME LIÉ À AUR, CONTACTEZ LES MAINTENEURS DU PAQUET AUR. LES PAQUETS OFFICIELS SONT DISPONIBLES SUR LA PAGE DES VERSIONS GITHUB.

1.  **Téléchargement, compilation et installation :**

    ```bash
    git clone https://aur.archlinux.org/word-sys-pdf-editor
    cd word-sys-pdf-editor
    makepkg -sfi
    ```

    Avec l'assistant AUR `yay` :
    ```bash
    yay -S word-sys-pdf-editor
    ```

    Ou avec `paru` :
    ```bash
    paru -S word-sys-pdf-editor
    ```

    Ou avec le paquet binaire précompilé `-bin` sur AUR :
    ```bash
    yay -S word-sys-pdf-editor-bin
    ```
    ou
    ```bash
    paru -S word-sys-pdf-editor-bin
    ```

    *Optionnel (pour l'export DOCX) :*
    ```bash
    sudo pacman -S libreoffice-fresh
    ```

2.  **Lancer l'application :**
    ```bash
    word-sys-pdf-editor
    ```

---

## Rapports de bogues et retours d'expérience

Si vous rencontrez un bogue, avez une suggestion de fonctionnalité ou souhaitez partager vos retours, veuillez utiliser l'espace [**GitHub Issues**](https://github.com/word-sys/word-sys-pdf-editor/issues).

---

## Contribution

word-sys's PDF Editor est un projet open source et accueille volontiers les contributions. Pour participer :

1.  Forkez ce dépôt.
2.  Créez votre branche de fonctionnalité ou correction (`git checkout -b feature/nouvelle-fonctionnalite` ou `git checkout -b fix/nom-du-bogue`).
3.  Effectuez vos modifications et validez-les (`git commit -am 'Ajout de la nouvelle fonctionnalite'`).
4.  Poussez votre branche sur GitHub (`git push origin feature/nouvelle-fonctionnalite`).
5.  Ouvrez une Pull Request (PR).

---

## Licence

Ce projet est sous licence [**GNU General Public License v3.0 or later**](LICENSE).
