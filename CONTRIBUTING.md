# Contributing to word-sys's PDF Editor

Thank you for contributing to word-sys's PDF Editor.

## Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to baringuzeldemir@gmail.com.

## Development Setup

### Dependencies

#### Debian / Ubuntu / Pardus
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv \
                 python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
                 libgirepository1.0-dev python3-numpy python3-dev \
                 libcairo2-dev build-essential \
                 fonts-noto-core fonts-liberation2
```

Optional (for DOCX/ODT conversion testing):
```bash
sudo apt install libreoffice-common libreoffice-writer
```

#### Fedora
```bash
sudo dnf install python3 python3-pip python3-devel \
                 gtk4 libadwaita gobject-introspection \
                 cairo-gobject-devel gcc
```

#### Arch Linux
```bash
sudo pacman -S python python-pip python-gobject gtk4 libadwaita \
               python-numpy cairo base-devel
```

### Running from Source

1. Clone your fork:
   ```bash
   git clone https://github.com/<your-username>/word-sys-pdf-editor.git
   cd word-sys-pdf-editor
   ```

2. Create a virtual environment using system site packages (required for PyGObject bindings):
   ```bash
   python3 -m venv --system-site-packages venv
   source venv/bin/activate
   ```

3. Install required Python packages:
   ```bash
   pip install PyMuPDF numpy
   ```

4. Run the editor:
   ```bash
   python3 run-editor.py
   ```

### VS Code

Open `word-sys-pdf-editor.code-workspace` to load the recommended Python,
Pylance, YAML, and TOML extensions and enable pytest discovery automatically.

### Tests and coverage

Install the test dependencies and run the suite from the repository root:

```bash
pip install -e '.[test]'
pytest --cov=word_sys_pdf_editor --cov-report=term-missing
```

Pull requests run the same tests on GitHub Actions. The generated XML coverage
report is attached to each workflow run as the `coverage-report` artifact.

## Project Structure

All core logic resides inside the `word_sys_pdf_editor/` package:

- `main.py`: Application entry point (`Adw.Application`), D-Bus setup, startup actions.
- `window.py`: Main window (`Adw.ApplicationWindow`), toolbar controls, edit/view switching.
- `pdf_view.py`: Custom Cairo canvas widget, page rendering, zoom handling, object selection and manipulation.
- `pdf_handler.py`: PyMuPDF operations (loading, saving, rendering surfaces, text manipulation, redaction, exports).
- `models.py`: Data models for editable canvas objects (`EditableText`, `EditableImage`, `EditableDrawing`, `EditableShape`).
- `commands.py`: Command pattern implementations for undo/redo actions.
- `undo_manager.py`: Undo/redo stack management.
- `dialogs.py`: Dialog implementations (New Document Creator, page settings, alerts).
- `quick_start_guide.py`: Interactive manual and keyboard shortcuts cheatsheet window (F1).
- `welcome_view.py`: Start screen and recent files hub.
- `i18n.py`: UI translations dictionary (English and Turkish).
- `constants.py`: Version string and application constants.

## Submitting Changes

1. Create a branch for your change:
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/issue-description
   ```

2. Test your changes:
   - Run `python3 run-editor.py` and verify your changes work as intended.
   - Test both View and Edit modes.
   - Verify that existing documents open, edit, and save without regressions.
   - Ensure Undo (`Ctrl+Z`) and Redo (`Ctrl+Y`) work properly with your changes.

3. Commit your changes with clear, descriptive commit messages.

4. Push your branch and open a Pull Request against the `main` branch of `word-sys/word-sys-pdf-editor`.

5. Provide a summary of the change in the PR description, referencing any relevant issue numbers (e.g., `Fixes #12`).

## Translations

UI strings and translations are stored in `word_sys_pdf_editor/i18n.py`.
- To fix or add a translation, update the corresponding key in the `TRANSLATIONS` dictionary.
- If adding a new UI string, add it to both the English (`en`) and Turkish (`tr`) dictionaries.
