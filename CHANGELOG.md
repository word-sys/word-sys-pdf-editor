# Changelog

All notable changes to this project will be documented in this file.

## [1.11.0] - 2026-09-15

### Added
- **Modern Libadwaita Customizable "New Document" Dialog**: Completely redesigned document creation dialog with 18 international paper and screen presets (A0–A6, B4–B5, US Letter/Legal/Executive, Tabloid/Ledger, 16:9/16:10/4:3 Widescreen Slides, 1:1 Square, and Custom), linked Portrait/Landscape orientation swapping, real-time unit auto-conversion (`mm`, `cm`, `in`, `pt`, `px`), and blank page count configuration (1 to 500 pages).
- **Interactive Quick Start Guide & Manual**: Modern Libadwaita window (`Adw.Window` and `Adw.ViewSwitcher`) accessible from the Welcome screen, primary hamburger menu, and `F1` key. Categorized into Tools & Editing, Canvas & Pages, and Keyboard Shortcuts Cheatsheet with native keycap styling (`.keycap`).
- **Global Actions & Keyboard Shortcuts**: Fully wired `Ctrl + N` (New Document), `Ctrl + O` (Open PDF), and `F1` (Help/Guide) across edit and view modes with descriptive button tooltips on both the header bar and Welcome screen.
- **Decoupled Zoom & Precision Pointer Focal Zoom**: Smooth, instantaneous zooming centered precisely around the mouse pointer with `Ctrl + Scroll` and `Ctrl + + / - / 0`, decoupled from destructive page reloads and backed by Cairo surface memory caching for lag-free canvas redrawing.
- **Vector Stroke Scaling & Live Previews**: Proportional resizing (`scale_to_bbox`) for freehand drawing strokes and polylines, retaining natural geometry without morphing into boxes, with full undo/redo snapshot preservation.
- **High-Performance Linux Font Engine**: Direct font family matching via Linux Fontconfig (`fc-match`) with in-memory caching (`FONT_MATCH_CACHE`), preventing startup timeouts while preserving distinct font identities and monospace/serif attributes.
- **Multi-Style & Multi-Colored Text Segmentation**: Intelligent line segmentation into distinct style runs based on normalized style signatures, allowing independent formatting and recoloring of individual text spans without destroying sentence flow.

### Changed
- **PyMuPDF Modernization**: Updated core PDF engine import to `import pymupdf as fitz` with graceful fallback, fully silencing deprecation warnings while retaining 100% backward compatibility.
- **Console Logging Clean-up**: Silenced noisy startup debug prints, eliminated repetitive font scan logs, and standardized console messages to English.
- **Calibrated Resize Handle Hitbox**: Refined handle hit tolerance to 4.0pt for drawing tools to match the visual 8x8pt square boundary, eliminating accidental handle grabbing when handwriting letters or drawing adjacent strokes.
- **Highlighter Quality Calibration**: Square line caps (`cairo.LINE_CAP_SQUARE`, `lineCap=2`) and bevel joins keep highlighters neatly bounded within text line heights without spilling onto adjacent lines. Default width synchronized with toolbar controls.

### Fixed
- **Transparent PNG Alpha Channel Preservation**: Full soft-mask (`smask`) alpha compositing during image extraction and embedding, ensuring transparent PNGs retain full transparency without turning black.
- **Text & Stroke Preservation on Object Deletion/Redaction**: Targeted graphics and stroke-aware redactions prevent underlying or intersecting text characters and handwriting strokes from being erased when deleting shapes or strokes.
- **Underline Vector Detection & Clean Ghost Erasing**: Detects and aligns baseline underline drawings, erases old vector underlines cleanly during text movement without duplicating them or cutting into neighboring glyphs.
- **Unsaved Changes Navigation Fix**: Clicking "Cancel" on the unsaved changes dialog when navigating to the homepage now cleanly aborts navigation and keeps the active document open.
- **Turkish Localization Polish**: Localized About dialog topic tabs ("Hakkında", "Emeği Geçenler", "Lisans") and Cancel buttons, and added comprehensive bilingual translation tables.

---

## [1.10.0-beta1] - 2026-08-30

### Added
- **Quick Save (Ctrl+S)**: Direct quick saving with `Ctrl+S` shortcut and toolbar button, including atomic temporary file swapping to ensure original PDF files are protected against corruption.
- **Manual Freehand Pen & Highlighter Tools**: Added freehand drawing tools with customizable colors, stroke widths, and opacity. Features live Cairo drawing previews and native PyMuPDF vector path embedding.
- **Quick Checkmark (✓) & Cross (✗) Tools**: Dedicated 1-click sidebar tools for adding resizable, vector-crisp checkmarks and crosses for fast form review and document markup.
- **Special Characters, Symbols & Emojis Palette**: New popover palette with categorized tabs for form review symbols and emojis. Emojis are stamped as high-resolution, full-color movable annotations, and text symbols feature automatic `DejaVu Sans` font fallback to eliminate missing glyph tofu boxes.
- **Single-Key Keyboard Shortcuts**: Quick tool selection shortcuts (`V` for Checkmark, `X` for Cross, `P` for Pen, `H` for Highlighter, `S` for Select, `T` for Text, `I` for Image, `M` for Move, `C` for Ellipse, `R` for Rectangle) with updated sidebar tool button label hints.
- **Arrow Key Nudge Movement**: Move any selected object with pixel-precision using Arrow keys (1.0 pt fine alignment) and `Shift + Arrow keys` (10.0 pt step) with complete Undo/Redo tracking.
- **Direct Creation Tool Resizing**: Resize handles on newly created objects can now be directly grabbed and dragged without requiring a manual switch back to the "Select" tool.

---

## [1.9.4] - 2026-07-31

### Fixed
- **GTK File Dialog & Flatpak Compatibility**: Fixed `AttributeError` for `Gtk.FileDialog` on GTK < 4.10 by introducing fallback support for `Gtk.FileChooserDialog` with explicit parent window modal binding.
- **Export Format Detection**: Fixed "Export As" format resolution when selecting export target filters in file dialogs.
- **Pango Markup Formatting**: Escaped recent file names and paths in the welcome view to prevent markup parsing errors.

---

## [1.9.3] - 2026-06-05

### Added
- **Hyperlink Annotation Support**: Blue styling and underlines for URL text. Clickable link annotations are embedded in the PDF page and saved natively.
- **Link De-duplication**: Tracks original page links to prevent annotations from multiplying during page rebuilds or undo/redo actions.

### Fixed
- **Localizations**: Localized hardcoded strings for View/Edit modes, sidebar "Tools" title, Highlight button tooltips, and file chooser filters.
- **Bold Underline Length**: Resolved the bold underline bug by dynamically resolving the styled Base 14 font variant (e.g. `Helvetica-Bold`) for accurate text length calculation during PDF rendering.

---

## [1.9.2] - 2026-05-23

### Added
- **Scroll Wheel to Welcome Page**: Added scrool wheel to PDF's that on Welcome Page to see all of them at same time while fixing the "Oversized Unsizable Screen Issue"
- **AppImage and Binary Release**: Added universal appimage and binary releases that works on old and bleeding edge distros without installing any depency, easy use for last-user

### Fixed
- **Oversized Unsizable Screen Issue**: Fixed by adding "Scroll Wheel to Welcome Page" update that fixes PDF file directory listings getting stuck top to top that blocks screen to be resized again, fixed issue.
- **Localizations**: Welcome page screen PDF's thats now shows "PDF's on System" that scans places to find PDF Files for easy access
- **Icon Assets**: Fixed icon issue on AppImage and Binary Release

---

## [1.9.1] - 2026-05-22

### Added
- **System Integration**: Integrated native XDG file picker via `Gtk.FileChooserNative`.

### Fixed
- **Oversized Layout**: Split the top toolbar into a two-line layout in Edit mode to reduce minimum window width to ~500px, resolving the PDF page centering issue when resizing
- **Context Menu Popover**: Corrected spawning coordinate calculations so the right-click context menu points directly to the mouse cursor
- **Localizations**: Localized all previously hardcoded Turkish error/status messages into English and Turkish using the `i18n` translation tables
- **Icon Assets**: Removed obsolete files (`icon.png`, `icon.svg`, `icon256.png`, `icon256.svg`) from the repository, while preserving `f-pv1.svg` for system integration

---

## [1.9.0] - 2026-05-06

### Added
- **Text Decoration Support**: Implemented Underline support across the entire application (UI, PDF export, and formatting tools).
- **Word-Level Selection**: Enhanced selection engine to support granular word selection (Middle-Click) in addition to block-level selection.
- **Improved Highlighting**: Highlight and Remove Highlight tools now respect word-level selection for precise annotations.
- **Top Toolbar Integration**: Added Underline toggle button to the main formatting toolbar with full property synchronization.
- **Internationalization**: Full localization for new features in both English and Turkish.

### Fixed
- **Stability Fixes**: Resolved multiple `UnboundLocalError` and `TypeError` crashes occurring during text formatting and object manipulation.
- **Rendering Alignment**: Fixed "jumbled" or overlapping text bug when splitting sentences for partial formatting (e.g., coloring a single word).
- **Font Width Estimation**: Added safe fallbacks for font width calculation to prevent `ValueError` crashes with custom system fonts.
- **Link Styling**: Fixed bug where web links were losing their blue color and underline state in the editor view.
- **UI Synchronization**: Resolved issues where the toolbar buttons (Bold, Italic, Underline) would occasionally become unresponsive or show incorrect states.

---

## [1.8.3] - 2026-04-24
- Renamed project branding to word-sys's PDF Editor.
- Fixed language support for the About page.
- Improved multi-distro compatibility for the .deb package.
- Architecture changed to `all` to support arm64 and x86_64.
