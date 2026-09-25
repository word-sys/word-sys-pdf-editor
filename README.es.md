**Idiomas:** [English](README.md) | [Türkçe](README.tr.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [Italiano](README.it.md) | [Русский](README.ru.md)

# word-sys's PDF Editor
<img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/word_sys_pdf_editor/img/f-pv1.svg" width="256" height="256"/>

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPLv3+-blue.svg)](LICENSE)
[![GitHub All Releases](https://img.shields.io/github/downloads/word-sys/word-sys-pdf-editor/total)](https://github.com/word-sys/word-sys-pdf-editor/releases)

**word-sys's PDF Editor** es una herramienta sencilla e intuitiva desarrollada para Pardus, Debian y otras distribuciones Linux, enfocada en la edición de texto, imágenes y objetos en archivos PDF. Desarrollado desde cero con el espíritu de #MilliTeknolojiHamlesi y TEKNOFEST 2025 para cubrir la necesidad de un editor de PDF sencillo, libre y de código abierto en el ecosistema Linux, word-sys's PDF Editor está diseñado tanto para entornos corporativos como individuales. Realiza la gran mayoría de las funciones esenciales que ofrecen los editores comerciales de pago, ofrece una amplia gama de opciones fáciles de usar y ha sido galardonado con el **PRIMER PUESTO** en la Competencia de Desarrollo Pardus TEKNOFEST 2025.

Desarrollador: **Barın Güzeldemirci (word-sys)**  
Licencia: **GPL-3.0-or-later**

---

> [!TIP]
> **Versión estable recomendada: v1.11.0** — Para disfrutar de la mayor estabilidad, se recomienda encarecidamente utilizar la versión **1.11.0**. Consulte las secciones de instalación a continuación para obtener más información.

---

## Capturas de pantalla

| **Lienzo de edición y anotación PDF** | **Pantalla de bienvenida y gestión documental** |
| :---: | :---: |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot1.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot1.png" alt="Lienzo de edición PDF" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot2.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot2.png" alt="Pantalla de bienvenida" width="450"/></a> |
| **Diálogo de creación de nuevo documento** | **Guía interactiva y manual de usuario** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot3.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot3.png" alt="Creación de nuevo documento" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot4.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot4.png" alt="Guía interactiva y manual" width="450"/></a> |

---

## Características principales

*   Crear archivos PDF con dimensiones de página personalizadas y conversión automática de unidades (mm, cm, in, pt, px)
*   Abrir y visualizar documentos PDF
*   Combinar y unir archivos PDF
*   Guía interactiva de inicio rápido y tabla de atajos de teclado (`F1`)
*   Seleccionar bloques de texto existentes en una página
*   Editar o eliminar texto seleccionado
*   Añadir nuevos bloques de texto en cualquier página
*   Insertar imágenes preservando la transparencia alfa
*   Soporte de familias y grosores tipográficos mediante el motor Linux Fontconfig (`fc-match`)
*   Mover y reposicionar objetos en el documento
*   Modificar tipografía, tamaño, color y decoración de texto
*   Selección granular de palabras y resaltado preciso
*   Añadir formas vectoriales (Rectángulos, Elipses, Marcas de verificación, Cruces)
*   Trazado libre de lápiz y resaltador con suavizado de Bézier y escalado vectorial
*   Caracteres especiales y símbolos
*   Guardar documentos PDF modificados
*   Guardado rápido (`Ctrl + S`)
*   Exportar PDF a DOCX o ODT (requiere LibreOffice) y texto plano TXT
*   Interfaz intuitiva con reordenación de páginas por arrastrar y soltar miniaturas en tiempo real
*   Guardado seguro (Safe Save)
*   Modo restringido (Safe Mode)
*   Historial multinivel completo de Deshacer/Rehacer (`Ctrl + Z` / `Ctrl + Y`)
*   Zoom focal centrado en el puntero (`Ctrl + Rueda` y `Ctrl + + / - / 0`)
*   Añadir y eliminar páginas en archivos PDF

---

## Instalación

Existen varios métodos para instalar word-sys's PDF Editor en su sistema:

### 1. Instalación automática (Método recomendado)

Es la vía más sencilla para distribuciones basadas en Debian, Ubuntu y Pardus.

1.  Descargue el paquete `.deb` más reciente desde la página de [**Versiones de GitHub**](https://github.com/word-sys/word-sys-pdf-editor/releases). Por lo general el archivo se llama `word-sys-pdf-editor_1.11.0_all.deb`.

    > [!TIP]
    > **Utilice la versión 1.11.0** para la mejor estabilidad: busque `word-sys-pdf-editor_1.11.0_all.deb` en la página de versiones.

2.  Abra un terminal en el directorio donde descargó el paquete `.deb`.
3.  Ejecute el siguiente comando para instalarlo:
    ```bash
    sudo apt update
    sudo apt install ./word-sys-pdf-editor_1.11.0_all.deb
    ```
    *(Nota: Sustituya `word-sys-pdf-editor_1.11.0_all.deb` por el nombre exacto del archivo que haya descargado si difiere.)*
4.  Si se presenta un error de dependencias, ejecute el siguiente comando para solucionarlo:
    ```bash
    sudo apt --fix-broken install
    ```
5.  Una vez completada la instalación, puede iniciar word-sys's PDF Editor desde el menú de aplicaciones de su sistema.

---

### 2. AppImage y Paquete binario (Segundo método recomendado)

Este método funciona de inmediato en prácticamente cualquier distribución Linux.

1.  Descargue el paquete `.AppImage` o `*-linux-x64.tar.gz` desde la página de [**Versiones de GitHub**](https://github.com/word-sys/word-sys-pdf-editor/releases).

    > **Utilice la versión 1.11.0** para máxima estabilidad: busque la etiqueta `v1.11.0` en la página de lanzamientos.

#### A. Instalación de AppImage

1. Abra un terminal en la carpeta donde descargó `word-sys-pdf-editor.AppImage`.

2. Asigne permisos de ejecución:
    ```bash
    chmod +x word-sys-pdf-editor.AppImage
    ```

3. Haga doble clic en el archivo AppImage o ejecútelo en el terminal:
    ```bash
    ./word-sys-pdf-editor.AppImage
    ```

#### B. Instalación del paquete binario (tar.gz)

1. Abra un terminal en el directorio donde descargó `word-sys-pdf-editor-linux-x64.tar.gz`.

2. Descomprima el archivo:
    ```bash
    tar -xzf word-sys-pdf-editor-linux-x64.tar.gz
    ```

3. Acceda al directorio extraído:
    ```bash
    cd AppDir
    ```

4. Dé permisos de ejecución a AppRun:
    ```bash
    chmod +x AppRun
    ```

5. Inicie la aplicación:
    ```bash
    ./AppRun
    ```

---

### 3. Instalación manual (Para desarrolladores o compilación desde código fuente)

Este método es ideal para quienes deseen ejecutar la aplicación directamente desde el código fuente o contribuir al desarrollo.

> [!TIP]
> Para una versión estable, clone la etiqueta **v1.11.0**. Si desea probar los cambios de desarrollo más recientes, clone la rama `main` (que puede presentar menor estabilidad).

---

#### Pardus 23.4, Debian 12 y Ubuntu < 24.04 — Instalación manual

1.  **Instalar dependencias necesarias:**
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip python3-venv \
                     python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libgirepository1.0-dev \
                     python3-numpy \
                     python3-dev libcairo2-dev build-essential \
                     fonts-noto-core fonts-liberation2
    ```
    *Opcional (para exportación a DOCX):*
    ```bash
    sudo apt install libreoffice-common
    ```

2.  **Descargar el código fuente:**

    **Recomendado (versión estable v1.11.0):**
    ```bash
    git clone --branch v1.11.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Para pruebas / desarrollo más reciente:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

3.  **Crear y activar un entorno virtual (Recomendado):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
    *(Puede usar `deactivate` más adelante para salir del entorno virtual.)*

4.  **Instalar dependencias de Python:**
    ```bash
    pip install PyMuPDF numpy pygobject==3.50.0
    ```

5.  **Iniciar la aplicación:**
    ```bash
    python3 run-editor.py
    ```

---

#### Ubuntu 24.04+, Debian 13 Trixie — Instalación manual

1.  **Instalar dependencias necesarias:**
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip python3-venv \
                     python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libgirepository-2.0-dev \
                     python3-numpy \
                     python3-dev libcairo2-dev build-essential \
                     fonts-noto-core fonts-liberation2
    ```
    *Opcional (para exportación a DOCX):*
    ```bash
    sudo apt install libreoffice-common
    ```

2.  **Descargar el código fuente:**

    **Recomendado (versión estable v1.11.0):**
    ```bash
    git clone --branch v1.11.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Para pruebas / desarrollo más reciente:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

3.  **Crear y activar un entorno virtual:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

4.  **Instalar dependencias de Python:**
    ```bash
    pip install PyMuPDF numpy pygobject
    ```

5.  **Iniciar la aplicación:**
    ```bash
    python3 run-editor.py
    ```

---

#### Arch Linux y Derivadas — Instalación manual

1.  **Descargar el código fuente:**

    **Recomendado (versión estable v1.11.0):**
    ```bash
    git clone --branch v1.11.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Para pruebas / desarrollo más reciente:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    *Opcional (para exportación a DOCX):*
    ```bash
    sudo pacman -S libreoffice-fresh
    ```

2.  **Crear y activar un entorno virtual:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Instalar dependencias de Python:**
    ```bash
    pip install PyMuPDF numpy pygobject
    ```

4.  **Iniciar la aplicación:**
    ```bash
    python3 run-editor.py
    ```

---

#### Arch Linux y Derivadas — Desde AUR

#### ESTOS PAQUETES NO SON CREADOS NI MANTENIDOS POR EL AUTOR DEL PROYECTO. REVISE SU CONTENIDO EN AUR ANTES DE INSTALAR. ANTE CUALQUIER PROBLEMA CON LOS PAQUETES DE AUR, CONTACTE A LOS RESPECTIVOS MANTENEDORES DE AUR. LOS PAQUETES OFICIALES SON GENERADOS POR GITHUB ACTIONS EN LA PÁGINA DE VERSIONES.

1.  **Descarga, compilación e instalación:**

    ```bash
    git clone https://aur.archlinux.org/word-sys-pdf-editor
    cd word-sys-pdf-editor
    makepkg -sfi
    ```

    Con el gestor AUR `yay`:
    ```bash
    yay -S word-sys-pdf-editor
    ```

    O con `paru`:
    ```bash
    paru -S word-sys-pdf-editor
    ```

    O utilizando el paquete binario precompilado `-bin` en AUR:
    ```bash
    yay -S word-sys-pdf-editor-bin
    ```
    o
    ```bash
    paru -S word-sys-pdf-editor-bin
    ```

    *Opcional (para exportación a DOCX):*
    ```bash
    sudo pacman -S libreoffice-fresh
    ```

2.  **Iniciar la aplicación:**
    ```bash
    word-sys-pdf-editor
    ```

---

## Reportes de errores y sugerencias

Si encuentra algún error, tiene una sugerencia de mejora o desea enviar comentarios, utilice la sección [**GitHub Issues**](https://github.com/word-sys/word-sys-pdf-editor/issues).

---

## Contribuciones

word-sys's PDF Editor es un proyecto de código abierto y agradece las colaboraciones. Para contribuir:

1.  Haga un fork de este repositorio.
2.  Cree una nueva rama para su función o corrección (`git checkout -b feature/nueva-funcion` o `git checkout -b fix/nombre-del-fallo`).
3.  Realice sus cambios y confírmelos (`git commit -am 'Agregada nueva funcion'`).
4.  Suba la rama a su fork en GitHub (`git push origin feature/nueva-funcion`).
5.  Abra una Pull Request (PR).

---

## Licencia

Este proyecto está bajo la licencia [**GNU General Public License v3.0 or later**](LICENSE).
