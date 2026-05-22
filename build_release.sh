#!/bin/bash
set -e

echo "=== Starting word-sys PDF Editor build process ==="

rm -rf build dist AppDir *.zip *.AppImage

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is not installed."
    exit 1
fi

if ! python3 -c "import PyInstaller" >/dev/null 2>&1; then
    echo "PyInstaller not found. Installing PyInstaller via pip..."
    python3 -m pip install --upgrade pip
    python3 -m pip install pyinstaller
fi

echo "=== Compiling application with PyInstaller ==="
pyinstaller pardf.spec

echo "=== Creating Standalone Zip Release ==="
if [ -d "dist/word-sys-pdf-editor" ]; then
    cd dist
    zip -q -r ../word-sys-pdf-editor-linux-x86_64.zip word-sys-pdf-editor
    cd ..
    echo "Successfully created standalone zip release: word-sys-pdf-editor-linux-x86_64.zip"
else
    echo "ERROR: PyInstaller build failed. dist/word-sys-pdf-editor not found."
    exit 1
fi

echo "=== Preparing AppDir for AppImage ==="
mkdir -p AppDir/usr/bin
cp -r dist/word-sys-pdf-editor/* AppDir/usr/bin/

cp debian/word-sys-pdf-editor.desktop AppDir/
cp word_sys_pdf_editor/img/f-pv1.svg AppDir/
cp word_sys_pdf_editor/img/f-pv1.png AppDir/
cat << 'EOF' > AppDir/AppRun
#!/bin/sh
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}/usr/bin:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/bin:${LD_LIBRARY_PATH}"
export XDG_DATA_DIRS="${HERE}/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
exec "${HERE}/usr/bin/word-sys-pdf-editor" "$@"
EOF
chmod +x AppDir/AppRun

echo "=== Downloading and Running appimagetool ==="
if ! command -v appimagetool >/dev/null 2>&1; then
    echo "appimagetool not found on system. Downloading portable version..."
    wget -q https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage -O appimagetool
    chmod +x appimagetool
    APPIMAGE_TOOL="./appimagetool"
else
    echo "Using system appimagetool..."
    APPIMAGE_TOOL="appimagetool"
fi

export ARCH=x86_64

if [ "$APPIMAGE_TOOL" = "./appimagetool" ]; then
    $APPIMAGE_TOOL AppDir word-sys-pdf-editor-x86_64.AppImage || \
    ./appimagetool --appimage-extract-and-run AppDir word-sys-pdf-editor-x86_64.AppImage
else
    $APPIMAGE_TOOL AppDir word-sys-pdf-editor-x86_64.AppImage
fi

echo "Successfully created AppImage: word-sys-pdf-editor-x86_64.AppImage"

if command -v dpkg-buildpackage >/dev/null 2>&1; then
    echo "=== Building Debian Package ==="
    dpkg-buildpackage -us -uc -b
    mv ../word-sys-pdf-editor_*.deb ./ || true
    echo "Successfully created Debian package!"
else
    echo "dpkg-buildpackage not found, skipping Debian package build."
fi

echo "=== Build process complete! ==="
