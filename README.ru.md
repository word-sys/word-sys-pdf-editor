**Языки:** [English](README.md) | [Türkçe](README.tr.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [Italiano](README.it.md) | [Русский](README.ru.md)

# word-sys's PDF Editor
<img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/word_sys_pdf_editor/img/f-pv1.svg" width="256" height="256"/>

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPLv3+-blue.svg)](LICENSE)
[![GitHub All Releases](https://img.shields.io/github/downloads/word-sys/word-sys-pdf-editor/total)](https://github.com/word-sys/word-sys-pdf-editor/releases)
[![Flathub](https://img.shields.io/flathub/v/io.github.word_sys.word-sys-pdf-editor?logo=flathub)](https://flathub.org/apps/io.github.word_sys.word-sys-pdf-editor)

**word-sys's PDF Editor** — это простой и удобный инструмент для Pardus, Debian и других дистрибутивов Linux, предназначенный для редактирования текста, изображений и графических объектов в PDF-документах. Разработанный с нуля в рамках инициатив #MilliTeknolojiHamlesi и TEKNOFEST 2025 для удовлетворения потребности в простом, свободном и открытом PDF-редакторе для экосистемы Linux, word-sys's PDF Editor ориентирован как на корпоративных, так и на индивидуальных пользователей. Он выполняет подавляющее большинство ключевых задач коммерческих редакторов, предлагает широкий спектр интуитивно понятных функций и занял **ПЕРВОЕ МЕСТО** на конкурсе разработчиков Pardus TEKNOFEST 2025.

Разработчик: **Barın Güzeldemirci (word-sys)**  
Лицензия: **GPL-3.0-or-later**

---

> [!TIP]
> **Рекомендуемая стабильная версия: v1.12.0** — Для наиболее стабильной работы настоятельно рекомендуется использовать версию **1.12.0**. Инструкции по установке приведены ниже.

---

## Скриншоты

| **Холст редактирования PDF и непрерывная прокрутка** | **Стартовый экран и центр документов** |
| :---: | :---: |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot1.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot1.png" alt="Холст редактирования PDF и непрерывная прокрутка" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot2.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot2.png" alt="Стартовый экран и центр документов" width="450"/></a> |
| **Окно создания нового документа** | **Интерактивное руководство и справка** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot3.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot3.png" alt="Окно создания нового документа" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot4.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot4.png" alt="Интерактивное руководство и справка" width="450"/></a> |
| **Визуальное объединение документов** | **Вкладки документов и панель проверенной цифровой подписи** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot5.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot5.png" alt="Визуальное объединение документов" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot6.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot6.png" alt="Вкладки документов и панель цифровой подписи" width="450"/></a> |
| **Диалог ввода пароля для зашифрованного документа** | **Цифровая подпись PAdES и аппаратный токен** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot7.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot7.png" alt="Диалог ввода пароля для зашифрованного документа" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot8.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot8.png" alt="Цифровая подпись PAdES и аппаратный токен" width="450"/></a> |
| **Проверка криптографической подписи и сведения о сертификате** | **Распознавание текста (OCR) и инспектор текстового слоя** |
| <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot9.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot9.png" alt="Проверка криптографической подписи и сведения" width="450"/></a> | <a href="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot10.png"><img src="https://raw.githubusercontent.com/word-sys/word-sys-pdf-editor/refs/heads/main/screenshots/screenshot10.png" alt="Распознавание текста (OCR) и инспектор текстового слоя" width="450"/></a> |

---

## Основные возможности

*   Непрерывная вертикальная прокрутка страниц с оптимизированным рендерингом (viewport culling), упреждающей загрузкой и поддержкой дробного масштабирования (HiDPI / 4K / Retina)
*   Интерактивный движок AcroForms: прямое заполнение текстовых полей, флажков, радиокнопок и выпадающих списков в режиме просмотра, а также векторное уплощение (flattening)
*   Интерактивный конструктор форм (`B`) для создания, выравнивания и настройки новых полей AcroForm
*   Цифровые подписи PAdES Baseline с использованием программных сертификатов PKCS#12 и аппаратных токенов безопасности PKCS#11 / смарт-карт (HSM)
*   Интеграция криптографических меток времени RFC 3161 с поддержкой пользовательской аутентификации TSA
*   Неблокирующая проверка цифровых подписей при открытии документа с информационной панелью и инспектором сертификатов X.509
*   Постоянное криптографическое скрытие данных (`Shift+R`) с автоматическим поиском персональных данных (банковские карты, email, телефоны, регулярные выражения) и глубокой санитаризацией документов
*   Многопоточный фоновый движок оптического распознавания текста (OCR) с отображением прогресса и 7 нейросетевыми языковыми моделями
*   Инструмент области OCR (`O`) для мгновенного извлечения текста и инспектор уровня уверенности распознавания (`Ctrl+Alt+O`)
*   Заметки-стикеры с настраиваемыми цветами, метаданными авторов, цепочками ответов и боковой панелью аннотаций
*   Векторные штампы согласования (Одобрено, Конфиденциально, Черновик, динамические штампы пользователя и даты)
*   Инструменты точных измерений: линейка расстояний (`U`) с калибровкой масштаба и измерение площади полигонов (`A`)
*   Интеллектуальное сжатие PDF с подбором целевого размера и сравнительным визуальным предпросмотром качества
*   Шифрование документов паролем AES-256 и локальное защищенное хранилище паролей
*   Инструмент клонирования и заплатки (`C`) с чистым сэмплированием фона и мгновенным вводом замещающего текста (`Enter` / `T`)
*   Интерактивное руководство пользователя с 4 вкладками, горячими клавишами инструментов и живым поисковым фильтром (`F1` / `Ctrl+F`)
*   Создание PDF-документов с настраиваемыми размерами страниц и автоконвертацией единиц (мм, см, дюймы, pt, px)
*   Открытие и просмотр PDF-файлов
*   Объединение PDF-файлов с визуальным перетаскиванием страниц
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
*   Сохранение измененных PDF-документов и быстрое сохранение (`Ctrl + S`)
*   Экспорт PDF в форматы DOCX, PPTX, ODT, ODP и TXT с помощью встроенного движка anyconvert
*   Безопасное сохранение (Safe Save) и Ограниченный режим (Безопасный режим)
*   Полная многоуровневая история Отмены и Повтора (`Ctrl + Z` / `Ctrl + Y`)
*   Высокоточное фокальное масштабирование (`Ctrl + Колесо мыши` и `Ctrl + + / - / 0`)
*   Добавление, удаление страниц и поворот на 90 градусов в PDF
*   Безопасное сохранение (Safe Save)
*   Безопасный режим (Safe Mode)
*   Многоуровневая история отмены и повтора действий (`Ctrl + Z` / `Ctrl + Y`)
*   Масштабирование с фокусом на указателе мыши (`Ctrl + Колесико` и `Ctrl + + / - / 0`)
*   Добавление и удаление страниц в документе

### Встроенный экспорт документов (anyconvert)

word-sys's PDF Editor использует чистый Python-движок [anyconvert](https://github.com/word-sys/anyconvert) ([PyPI](https://pypi.org/project/anyconvert/)) для экспорта документов PDF без внешних зависимостей, таких как LibreOffice.

Поддерживаемые форматы:
*   **Microsoft Word (`.docx`)**
*   **Microsoft PowerPoint (`.pptx`)**
*   **Текст OpenDocument (`.odt`)**
*   **Презентация OpenDocument (`.odp`)**
*   **Простой текст (`.txt`)**

Режимы конвертации:
*   **Пиксельно точный холст (`mode='canvas'`)**: Сохраняет точное визуальное расположение текста, фигур и изображений 1:1. Рекомендуется для отредактированных PDF.
*   **Семантический поток (`mode='flow'`)**: Восстанавливает заголовки, абзацы и естественный поток текста.

anyconvert также можно запускать напрямую из командной строки:
```bash
anyconvert input.pdf -f docx -m canvas -o output.docx
```

---

## Установка

Существует несколько способов установки word-sys's PDF Editor в вашей системе:

### 1. Flatpak / Flathub (Рекомендуемый способ)

word-sys's PDF Editor официально доступен на [Flathub](https://flathub.org/apps/io.github.word_sys.word-sys-pdf-editor).

<a href="https://flathub.org/apps/io.github.word_sys.word-sys-pdf-editor"><img src="https://dl.flathub.org/assets/badges/flathub-badge-en.svg" alt="Download on Flathub" width="190"/></a>

Установка через Flatpak:
```bash
flatpak install flathub io.github.word_sys.word-sys-pdf-editor
```

Запуск приложения:
```bash
flatpak run io.github.word_sys.word-sys-pdf-editor
```

---

### 2. Пакет Debian / Ubuntu / Pardus (.deb)

Наиболее простой способ установки пакета для дистрибутивов на базе Debian, Ubuntu и Pardus.

1.  Скачайте свежий пакет `.deb` со страницы [**Релизы GitHub**](https://github.com/word-sys/word-sys-pdf-editor/releases). Имя файла: `word-sys-pdf-editor_1.12.0_amd64.deb` (или `_arm64.deb` для ARM64).

    > [!TIP]
    > **Используйте версию 1.12.0** для максимальной стабильности: найдите файл `word-sys-pdf-editor_1.12.0_amd64.deb` на странице релизов.

2.  Откройте терминал в папке с загруженным `.deb` пакетом.
3.  Выполните команду установки:
    ```bash
    sudo apt update
    sudo apt install ./word-sys-pdf-editor_1.12.0_amd64.deb
    ```
    *(Примечание: укажите точное имя загруженного файла, если оно отличается.)*
4.  При возникновении ошибок зависимостей выполните команду исправления:
    ```bash
    sudo apt --fix-broken install
    ```
5.  После завершения установки запустите word-sys's PDF Editor из системного меню приложений.

---

### 3. AppImage и бинарный архив

Универсальный запуск на любых дистрибутивах Linux.

1.  Скачайте пакет `.AppImage` или архив `*-linux-*.tar.gz` со страницы [**Релизы GitHub**](https://github.com/word-sys/word-sys-pdf-editor/releases) (`word-sys-pdf-editor-x86_64.AppImage` или `word-sys-pdf-editor-linux-x86_64.tar.gz`).

    > **Используйте версию 1.12.0** для максимальной надежности: ориентируйтесь на тег `v1.12.0`.

#### A. Установка AppImage

1. Откройте терминал в каталоге с файлом `word-sys-pdf-editor-x86_64.AppImage`.

2. Сделайте файл исполняемым:
    ```bash
    chmod +x word-sys-pdf-editor-x86_64.AppImage
    ```

3. Запустите AppImage двойным щелчком или из терминала:
    ```bash
    ./word-sys-pdf-editor-x86_64.AppImage
    ```

#### B. Установка бинарного архива (tar.gz)

1. Откройте терминал в каталоге с файлом `word-sys-pdf-editor-linux-x86_64.tar.gz`.

2. Распакуйте архив:
    ```bash
    tar -xzf word-sys-pdf-editor-linux-x86_64.tar.gz
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

### 4. Ручная установка (Для разработчиков и сборки из исходного кода)

Подходит для тех, кто хочет запускать приложение непосредственно из исходников или участвовать в разработке.

> [!TIP]
> Для стабильной работы используйте тег **v1.12.0** при клонировании. Для тестирования актуальных разработок клонируйте ветку `main` (может быть менее стабильной).

---

#### Pardus 23.4, Debian 12 и Ubuntu < 24.04 — Ручная установка

1.  **Установка необходимых пакетов:**
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip python3-venv \
                     python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libgirepository1.0-dev \
                     python3-numpy python3-cryptography \
                     python3-dev libcairo2-dev build-essential \
                     fonts-noto-core fonts-liberation2
    ```

2.  **Загрузка исходного кода:**

    **Рекомендуется (стабильная v1.12.0):**
    ```bash
    git clone --branch v1.12.0 https://github.com/word-sys/word-sys-pdf-editor.git
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
    pip install "PyMuPDF>=1.24.0,<2.0.0" numpy "anyconvert>=0.1.11" "cryptography>=41.0.0" "Pillow>=9.0.0" "pyhanko[image-support,opentype]>=0.25.0" "pyhanko-certvalidator>=0.24.0" "python-pkcs11>=0.7.0" "asn1crypto>=1.5.1" certifi pygobject==3.50.0
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
                     python3-numpy python3-cryptography \
                     python3-dev libcairo2-dev build-essential \
                     fonts-noto-core fonts-liberation2
    ```

2.  **Загрузка исходного кода:**

    **Рекомендуется (стабильная v1.12.0):**
    ```bash
    git clone --branch v1.12.0 https://github.com/word-sys/word-sys-pdf-editor.git
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
    pip install "PyMuPDF>=1.24.0,<2.0.0" numpy "anyconvert>=0.1.11" "cryptography>=41.0.0" "Pillow>=9.0.0" "pyhanko[image-support,opentype]>=0.25.0" "pyhanko-certvalidator>=0.24.0" "python-pkcs11>=0.7.0" "asn1crypto>=1.5.1" certifi pygobject
    ```

5.  **Запуск приложения:**
    ```bash
    python3 run-editor.py
    ```

---

#### Arch Linux и производные — Ручная установка

1.  **Загрузка исходного кода:**

    **Рекомендуется (стабильная v1.12.0):**
    ```bash
    git clone --branch v1.12.0 https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```

    **Для тестирования / разработки:**
    ```bash
    git clone https://github.com/word-sys/word-sys-pdf-editor.git
    cd word-sys-pdf-editor
    ```


2.  **Создание и активация виртуального окружения:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Установка зависимостей Python:**
    ```bash
    pip install "PyMuPDF>=1.24.0,<2.0.0" numpy "anyconvert>=0.1.11" "cryptography>=41.0.0" "Pillow>=9.0.0" "pyhanko[image-support,opentype]>=0.25.0" "pyhanko-certvalidator>=0.24.0" "python-pkcs11>=0.7.0" "asn1crypto>=1.5.1" certifi pygobject
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
