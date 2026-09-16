#!/bin/bash
set -e

ARCH="$(uname -m)"
echo "=== Building word-sys's PDF Editor for architecture: $ARCH ==="

case "$ARCH" in
    x86_64|amd64)
        ARCH_NAME="x86_64"
        DEB_ARCH="amd64"
        PYTHON_ARCH="x86_64"
        LINUXDEPLOY_ARCH="x86_64"
        LIB_DIR="/usr/lib/x86_64-linux-gnu"
        ;;
    aarch64|arm64)
        ARCH_NAME="aarch64"
        DEB_ARCH="arm64"
        PYTHON_ARCH="aarch64"
        LINUXDEPLOY_ARCH="aarch64"
        LIB_DIR="/usr/lib/aarch64-linux-gnu"
        ;;
    *)
        echo "Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

rm -rf AppDir build_tmp
mkdir -p AppDir/usr build_tmp

echo "--- Downloading standalone Python 3.10 for $PYTHON_ARCH ---"
curl -L -s "https://github.com/indygreg/python-build-standalone/releases/download/20240107/cpython-3.10.13+20240107-${PYTHON_ARCH}-unknown-linux-gnu-install_only.tar.gz" -o build_tmp/python.tar.gz
tar -xzf build_tmp/python.tar.gz -C AppDir/usr --strip-components=1

echo "--- Installing Python dependencies ---"
AppDir/usr/bin/python3 -m pip install --upgrade pip
AppDir/usr/bin/python3 -m pip install pygobject==3.50.0
AppDir/usr/bin/python3 -m pip install PyMuPDF numpy
AppDir/usr/bin/python3 -m pip install .

echo "--- Configuring application entry point ---"
cat << 'EOF' > AppDir/usr/bin/word-sys-pdf-editor.py
import sys
from word_sys_pdf_editor.main import main
sys.exit(main())
EOF

cat << 'EOF' > AppDir/usr/bin/word-sys-pdf-editor
#!/bin/bash
unset GTK_THEME
SELF_DIR="$(dirname "$(readlink -f "$0")")"
export GDK_PIXBUF_MODULEDIR="$SELF_DIR/../lib/gdk-pixbuf-2.0/2.10.0/loaders"
export GDK_PIXBUF_MODULE_FILE="$SELF_DIR/../lib/gdk-pixbuf-2.0/2.10.0/loaders.cache"
export LD_LIBRARY_PATH="$SELF_DIR/../lib:$SELF_DIR/../lib/gdk-pixbuf-2.0/2.10.0/loaders:$LD_LIBRARY_PATH"
exec "$SELF_DIR/python3" "$SELF_DIR/word-sys-pdf-editor.py" "$@"
EOF
chmod +x AppDir/usr/bin/word-sys-pdf-editor

mkdir -p AppDir/usr/share/applications
cp word-sys-pdf-editor.desktop AppDir/usr/share/applications/

mkdir -p AppDir/usr/share/icons/hicolor/scalable/apps
cp word_sys_pdf_editor/img/f-pv1.svg AppDir/usr/share/icons/hicolor/scalable/apps/

mkdir -p AppDir/usr/share/icons/hicolor/256x256/apps
cp word_sys_pdf_editor/img/f-pv1.png AppDir/usr/share/icons/hicolor/256x256/apps/

if [ -d "/usr/share/icons/Adwaita" ]; then
    cp -r /usr/share/icons/Adwaita AppDir/usr/share/icons/
fi

echo "--- Downloading linuxdeploy ($LINUXDEPLOY_ARCH) ---"
curl -L -s "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-${LINUXDEPLOY_ARCH}.AppImage" -o build_tmp/linuxdeploy
curl -L -s https://raw.githubusercontent.com/linuxdeploy/linuxdeploy-plugin-gtk/master/linuxdeploy-plugin-gtk.sh -o build_tmp/linuxdeploy-plugin-gtk.sh
curl -L -s "https://github.com/linuxdeploy/linuxdeploy-plugin-appimage/releases/download/continuous/linuxdeploy-plugin-appimage-${LINUXDEPLOY_ARCH}.AppImage" -o build_tmp/linuxdeploy-plugin-appimage
chmod +x build_tmp/linuxdeploy build_tmp/linuxdeploy-plugin-gtk.sh build_tmp/linuxdeploy-plugin-appimage

export PATH="$(pwd)/build_tmp:$PATH"
export DEPLOY_GTK_VERSION=4
export APPIMAGE_EXTRACT_AND_RUN=1

# Detect libadwaita-1 location dynamically
ADWAITA_SO="$(find /usr/lib -name "libadwaita-1.so.0" 2>/dev/null | head -n 1)"
if [ -z "$ADWAITA_SO" ]; then
    ADWAITA_SO="${LIB_DIR}/libadwaita-1.so.0"
fi

echo "--- Running linuxdeploy ---"
build_tmp/linuxdeploy --appdir AppDir --plugin gtk --desktop-file=word-sys-pdf-editor.desktop --icon-file=word_sys_pdf_editor/img/f-pv1.png -l "$ADWAITA_SO"

cp AppDir/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders/*.so AppDir/usr/lib/gdk-pixbuf-2.0/2.10.0/ 2>/dev/null || true
cp AppDir/usr/lib/librsvg-2.so* AppDir/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders/ 2>/dev/null || true

echo "--- Generating AppImage ---"
build_tmp/linuxdeploy --appdir AppDir --output appimage --desktop-file=word-sys-pdf-editor.desktop --icon-file=word_sys_pdf_editor/img/f-pv1.png

# Standardized AppImage naming for architecture
GENERATED_APPIMAGE="$(ls word*${LINUXDEPLOY_ARCH}.AppImage 2>/dev/null || ls *.AppImage 2>/dev/null | head -n 1)"
if [ -f "$GENERATED_APPIMAGE" ]; then
    mv "$GENERATED_APPIMAGE" "word-sys-pdf-editor-${ARCH_NAME}.AppImage"
    # Keep legacy symlink / copy for x86_64 compatibility
    if [ "$ARCH_NAME" = "x86_64" ]; then
        cp "word-sys-pdf-editor-${ARCH_NAME}.AppImage" word-sys-pdf-editor.AppImage
    fi
fi

echo "--- Packaging portable distribution archives ---"
# 1. tar.gz
tar -czf "word-sys-pdf-editor-linux-${ARCH_NAME}.tar.gz" AppDir
if [ "$ARCH_NAME" = "x86_64" ]; then
    cp "word-sys-pdf-editor-linux-${ARCH_NAME}.tar.gz" word-sys-pdf-editor-linux-x64.tar.gz
fi

# 2. tar.xz
tar -cJf "word-sys-pdf-editor-linux-${ARCH_NAME}.tar.xz" AppDir

# 3. zip
if command -v zip >/dev/null 2>&1; then
    zip -q -r9 "word-sys-pdf-editor-linux-${ARCH_NAME}.zip" AppDir
fi

# 4. 7z
if command -v 7z >/dev/null 2>&1; then
    7z a -mx=9 "word-sys-pdf-editor-linux-${ARCH_NAME}.7z" AppDir >/dev/null
fi

echo "--- Building Debian package ---"
mkdir -p debian_build
rsync -a --exclude=debian_build --exclude=AppDir --exclude=build_tmp . debian_build/
cd debian_build
dpkg-buildpackage -us -uc 2>&1 || true
cd ..

# Collect debian artifacts: .deb, .buildinfo, .changes, .dsc, .tar.xz
mv debian_build/../*.deb ./ 2>/dev/null || true
mv debian_build/../*.buildinfo ./ 2>/dev/null || true
mv debian_build/../*.changes ./ 2>/dev/null || true
mv debian_build/../*.dsc ./ 2>/dev/null || true
mv debian_build/../*.tar.xz ./ 2>/dev/null || true
mv word-sys-pdf-editor_* ./ 2>/dev/null || true

rm -rf debian_build build_tmp
echo "=== Build completed for $ARCH_NAME ==="
