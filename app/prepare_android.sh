#!/usr/bin/env bash
# Создаёт android/ и готовит манифест. Запускать из папки app/.
# Использование: API_URL=https://api.example.uz bash prepare_android.sh
set -euo pipefail
API_URL="${API_URL:-}"

if [ ! -d android ]; then
  flutter create --platforms=android --org uz.swap --project-name swap_app .
fi

M=android/app/src/main/AndroidManifest.xml

# Без этого релизный APK не выходит в интернет
if ! grep -q 'android.permission.INTERNET' "$M"; then
  sed -i 's#<application#<uses-permission android:name="android.permission.INTERNET"/>\n    <application#' "$M"
fi

# Адрес на http:// (без https) Android 9+ блокирует, разрешаем
case "$API_URL" in
  http://*)
    if ! grep -q usesCleartextTraffic "$M"; then
      sed -i 's#<application#<application android:usesCleartextTraffic="true"#' "$M"
    fi;;
esac

sed -i 's#android:label="[^"]*"#android:label="SWAP"#' "$M"
echo "OK: android готов"
