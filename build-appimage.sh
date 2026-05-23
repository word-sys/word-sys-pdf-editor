#!/bin/bash
set -e
rm -rf AppDir build_tmp
mkdir -p AppDir/usr build_tmp
curl -L -s https://github.com/indygreg/python-build-standalone/releases/download/20240107/cpython-3.10.13+20240107-x86_64-unknown-linux-gnu-install_only.tar.gz -o build_tmp/python.tar.gz
tar -xzf build_tmp/python.tar.gz -C AppDir/usr --strip-components=1
AppDir/usr/bin/python3 -m pip install --upgrade pip
AppDir/usr/bin/python3 -m pip install pygobject==3.50.0
AppDir/usr/bin/python3 -m pip install PyMuPDF numpy
AppDir/usr/bin/python3 -m pip install .
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
cp -r /usr/share/icons/Adwaita AppDir/usr/share/icons/
curl -L -s https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage -o build_tmp/linuxdeploy
curl -L -s https://raw.githubusercontent.com/linuxdeploy/linuxdeploy-plugin-gtk/master/linuxdeploy-plugin-gtk.sh -o build_tmp/linuxdeploy-plugin-gtk.sh
curl -L -s https://github.com/linuxdeploy/linuxdeploy-plugin-appimage/releases/download/continuous/linuxdeploy-plugin-appimage-x86_64.AppImage -o build_tmp/linuxdeploy-plugin-appimage
chmod +x build_tmp/linuxdeploy build_tmp/linuxdeploy-plugin-gtk.sh build_tmp/linuxdeploy-plugin-appimage
export PATH="$(pwd)/build_tmp:$PATH"
export DEPLOY_GTK_VERSION=4
build_tmp/linuxdeploy --appdir AppDir --plugin gtk --desktop-file=word-sys-pdf-editor.desktop --icon-file=word_sys_pdf_editor/img/f-pv1.png -l /usr/lib/x86_64-linux-gnu/libadwaita-1.so.0
cp AppDir/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders/*.so AppDir/usr/lib/gdk-pixbuf-2.0/2.10.0/
cp AppDir/usr/lib/librsvg-2.so* AppDir/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders/
build_tmp/linuxdeploy --appdir AppDir --output appimage --desktop-file=word-sys-pdf-editor.desktop --icon-file=word_sys_pdf_editor/img/f-pv1.png
mv *x86_64.AppImage word-sys-pdf-editor.AppImage
tar -czf word-sys-pdf-editor-linux-x64.tar.gz AppDir
rm -rf build_tmp
