**Языки:** [English](README.md) | [Türkçe](README.tr.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [Italiano](README.it.md) | [Русский](README.ru.md)

# word-sys's PDF Editor
<img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/word_sys_pdf_editor/img/f-pv1.svg" width="256" height="256"/>

**word-sys's PDF Editor** — это простой и удобный инструмент для Pardus, Debian и других дистрибутивов Linux, предназначенный для редактирования текста, изображений и графических объектов в PDF-документах. Разработанный с нуля в рамках инициатив #MilliTeknolojiHamlesi и TEKNOFEST 2025 для удовлетворения потребности в простом, свободном и открытом PDF-редакторе для экосистемы Linux, word-sys's PDF Editor ориентирован как на корпоративных, так и на индивидуальных пользователей. Он выполняет подавляющее большинство ключевых задач коммерческих редакторов, предлагает широкий спектр интуитивно понятных функций и занял **ПЕРВОЕ МЕСТО** на конкурсе разработчиков Pardus TEKNOFEST 2025.

Разработчик: **Barın Güzeldemirci (word-sys)**  
Лицензия: **GPL-3.0-or-later**

---

> [!TIP]
> **Рекомендуемая стабильная версия: v1.11.0** — Для наиболее стабильной работы настоятельно рекомендуется использовать версию **1.11.0**. Инструкции по установке приведены ниже.

---

## Скриншоты

| **Холст редактирования и аннотаций PDF** | **Стартовый экран и центр документов** |
| :---: | :---: |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot1.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot1.png" alt="Холст редактирования PDF" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot2.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot2.png" alt="Стартовый экран" width="450"/></a> |
| **Окно создания нового документа** | **Интерактивное руководство и справка** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot3.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot3.png" alt="Создание нового документа" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot4.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot4.png" alt="Интерактивное руководство" width="450"/></a> |

---

## Основные возможности

*   Создание PDF-документов с настраиваемыми размерами страниц и автоконвертацией единиц (мм, см, дюймы, pt, px)
*   Открытие и просмотр PDF-файлов
*   Объединение PDF-файлов
*   Интерактивное руководство пользователя и памятка горячих клавиш (`F1`)
*   Выделение существующих текстовых блоков на странице
*   Редактирование и удаление выбранного текста
*   Добавление новых текстовых блоков на страницы
*   Вставка изображений с сохранением альфа-прозрачности
*   Поддержка системных шрифтов и начертаний через движок Linux Fontconfig (`fc-match`)
*   Перемещение и позиционирование объектов в документе
*   Настройка гарнитуры, размера, цвета и оформления текста
*   Точное пословное выделение текста и маркировка
*   Добавление векторных фигур (Прямоугольники, Эллипсы, Галочки, Крестики)
*   Свободное рисование пером и маркером со сглаживанием Безье и векторным масштабированием
*   Специальные символы и знаки
*   Сохранение измененных PDF-документов
*   Быстрое сохранение (`Ctrl + S`)
*   Экспорт PDF в форматы DOCX или ODT (требуется LibreOffice) и простой текст TXT
*   Интуитивный интерфейс с перетаскиванием миниатюр страниц (drag-and-drop)
*   Безопасное сохранение (Safe Save)
*   Безопасный режим (Safe Mode)
*   Многоуровневая история отмены и повтора действий (`Ctrl + Z` / `Ctrl + Y`)
*   Масштабирование с фокусом на указателе мыши (`Ctrl + Колесико` и `Ctrl + + / - / 0`)
*   Добавление и удаление страниц в документе

---

## Установка

Существует несколько способов установки word-sys's PDF Editor в вашей системе:

### 1. Автоматическая установка (Рекомендуемый способ)

Наиболее простой способ для дистрибутивов на базе Debian, Ubuntu и Pardus.

1.  Скачайте свежий пакет `.deb` со страницы [**Релизы GitHub**](https://github.com/word-sys/word-sys-pdf-editor/releases). Имя файла обычно выглядит как `word-sys-pdf-editor_1.11.0_all.deb`.

    > [!TIP]
    > **Используйте версию 1.11.0** для максимальной стабильности: найдите файл `word-sys-pdf-editor_1.11.0_all.deb` на странице релизов.

2.  Откройте терминал в папке с загруженным `.deb` пакетом.
3.  Выполните команду установки:
    ```bash
    sudo apt update
    sudo apt install ./word-sys-pdf-editor_1.11.0_all.deb
    ```
    *(Примечание: укажите точное имя загруженного файла, если оно отличается.)*
4.  При возникновении ошибок зависимостей выполните команду исправления:
    ```bash
    sudo apt --fix-broken install
    ```
5.  После завершения установки запустите word-sys's PDF Editor из системного меню приложений.

---

### 2. AppImage и бинарный архив (Второй рекомендуемый способ)

Универсальный запуск на любых дистрибутивах Linux.

1.  Скачайте пакет `.AppImage` или архив `*-linux-x64.tar.gz` со страницы [**Релизы GitHub**](https://github.com/word-sys/word-sys-pdf-editor/releases).

    > **Используйте версию 1.11.0** для максимальной надежности: ориентируйтесь на тег `v1.11.0`.

#### A. Установка AppImage

1. Откройте терминал в каталоге с файлом `word-sys-pdf-editor.AppImage`.

2. Сделайте файл исполняемым:
    ```bash
    chmod +x word-sys-pdf-editor.AppImage
    ```

3. Запустите AppImage двойным щелчком или из терминала:
    ```bash
    ./word-sys-pdf-editor.AppImage
    ```

#### B. Установка бинарного архива (tar.gz)

1. Откройте терминал в каталоге с файлом `word-sys-pdf-editor-linux-x64.tar.gz`.

2. Распакуйте архив:
    ```bash
    tar -xzf word-sys-pdf-editor-linux-x64.tar.gz
    ```

3. Перейдите в распакованный каталог:
    ```bash
    cd AppDir
    ```

4. Сделайте исполняемым AppRun:
    ```bash
    chmod +x AppRun
    ```

5. Запустите приложение:
    ```bash
    ./AppRun
    ```

---

### 3. Ручная установка (Для разработчиков и сборки из исходного кода)

Подходит для тех, кто хочет запускать приложение непосредственно из исходников или участвовать в разработке.

> [!TIP]
> Для стабильной работы используйте тег **v1.11.0** при клонировании. Для тестирования актуальных разработок клонируйте ветку `main` (может быть менее стабильной).

---

#### Pardus 23.4, Debian 12 и Ubuntu < 24.04 — Ручная установка

1.  **Установка необходимых пакетов:**
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip python3-venv \
                     python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libgirepository1.0-dev \
                     python3-numpy \
                     python3-dev libcairo2-dev build-essential \
                     fonts-noto-core fonts-liberation2
    ```
    *Опционально (для экспорта в DOCX):*
    ```bash
    sudo apt install libreoffice-common
    ```

2.  **Загрузка исходного кода:**

    **Рекомендуется (стабильная v1.11.0):**
    ```bash
    git clone --branch v1.11.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Для тестирования / разработки:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

3.  **Создание и активация виртуального окружения (Рекомендуется):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
    *(Команда `deactivate` используется для выхода из виртуального окружения.)*

4.  **Установка зависимостей Python:**
    ```bash
    pip install PyMuPDF numpy pygobject==3.50.0
    ```

5.  **Запуск приложения:**
    ```bash
    python3 run-editor.py
    ```

---

#### Ubuntu 24.04+, Debian 13 Trixie — Ручная установка

1.  **Установка необходимых пакетов:**
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip python3-venv \
                     python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libgirepository-2.0-dev \
                     python3-numpy \
                     python3-dev libcairo2-dev build-essential \
                     fonts-noto-core fonts-liberation2
    ```
    *Опционально (для экспорта в DOCX):*
    ```bash
    sudo apt install libreoffice-common
    ```

2.  **Загрузка исходного кода:**

    **Рекомендуется (стабильная v1.11.0):**
    ```bash
    git clone --branch v1.11.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Для тестирования / разработки:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

3.  **Создание и активация виртуального окружения:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

4.  **Установка зависимостей Python:**
    ```bash
    pip install PyMuPDF numpy pygobject
    ```

5.  **Запуск приложения:**
    ```bash
    python3 run-editor.py
    ```

---

#### Arch Linux и производные — Ручная установка

1.  **Загрузка исходного кода:**

    **Рекомендуется (стабильная v1.11.0):**
    ```bash
    git clone --branch v1.11.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Для тестирования / разработки:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    *Опционально (для экспорта в DOCX):*
    ```bash
    sudo pacman -S libreoffice-fresh
    ```

2.  **Создание и активация виртуального окружения:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Установка зависимостей Python:**
    ```bash
    pip install PyMuPDF numpy pygobject
    ```

4.  **Запуск приложения:**
    ```bash
    python3 run-editor.py
    ```

---

#### Arch Linux и производные — Из AUR

#### ЭТИ ПАКЕТЫ НЕ СОЗДАЮТСЯ И НЕ ПОДДЕРЖИВАЮТСЯ АВТОРОМ ПРОЕКТА. ПРОВЕРЯЙТЕ ИХ СОДЕРЖИМОЕ В AUR ПЕРЕД УСТАНОВКОЙ. ПО ВСЕМ ВОПРОСАМ РАБОТЫ ПАКЕТОВ AUR ОБРАЩАЙТЕСЬ К ИХ СООТВЕТСТВУЮЩИМ МЕЙНТЕЙНЕРАМ. ОФИЦИАЛЬНЫЕ ПАКЕТЫ ПУБЛИКУЮТСЯ ЧЕРЕЗ GITHUB ACTIONS НА СТРАНИЦЕ РЕЛИЗОВ.

1.  **Загрузка, сборка и установка:**

    ```bash
    git clone https://aur.archlinux.org/word-sys-pdf-editor
    cd word-sys-pdf-editor
    makepkg -sfi
    ```

    С помощью AUR-хелпера `yay`:
    ```bash
    yay -S word-sys-pdf-editor
    ```

    Или через `paru`:
    ```bash
    paru -S word-sys-pdf-editor
    ```

    Или используя готовый бинарный пакет `-bin` из AUR:
    ```bash
    yay -S word-sys-pdf-editor-bin
    ```
    или
    ```bash
    paru -S word-sys-pdf-editor-bin
    ```

    *Опционально (для экспорта в DOCX):*
    ```bash
    sudo pacman -S libreoffice-fresh
    ```

2.  **Запуск приложения:**
    ```bash
    word-sys-pdf-editor
    ```

---

## Сообщения об ошибках и обратная связь

Если вы обнаружили ошибку, хотите предложить новую функцию или оставить отзыв, пожалуйста, создайте обращение в разделе [**GitHub Issues**](https://github.com/word-sys/word-sys-pdf-editor/issues).

---

## Участие в разработке

word-sys's PDF Editor — это проект с открытым исходным кодом. Чтобы внести вклад:

1.  Сделайте форк репозитория.
2.  Создайте новую ветку (`git checkout -b feature/novaya-funktsiya` или `git checkout -b fix/ispravlenie-oshibki`).
3.  Внесите изменения и зафиксируйте их (`git commit -am 'Dobavlena novaya funktsiya'`).
4.  Отправьте ветку в свой репозиторий GitHub (`git push origin feature/novaya-funktsiya`).
5.  Создайте Pull Request (PR).

---

## Лицензия

Этот проект лицензирован на условиях [**GNU General Public License v3.0 or later**](LICENSE).
