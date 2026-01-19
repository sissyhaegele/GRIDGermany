#!/bin/bash
# Download Solace JavaScript client library

SOLCLIENT_URL="https://products.solace.com/download/SDKJS_FULL"
TARGET_DIR="$(dirname "$0")/../app/dashboard/webapp"

echo "📥 Downloading Solace JavaScript Client..."

# Try npm package first (more reliable)
cd "$TARGET_DIR" || exit 1

# Option 1: Use npm to get the library
npm pack solclientjs@latest 2>/dev/null
if [ -f solclientjs-*.tgz ]; then
    tar -xzf solclientjs-*.tgz
    cp package/lib/solclient-full.js . 2>/dev/null || cp package/lib/solclient.js ./solclient-full.js
    rm -rf package solclientjs-*.tgz
    echo "✅ Solace client downloaded via npm"
    exit 0
fi

# Option 2: Try direct download
echo "Trying direct download..."
curl -L -o solclient-full.js "$SOLCLIENT_URL" 2>/dev/null

if [ -f solclient-full.js ] && [ -s solclient-full.js ]; then
    echo "✅ Solace client downloaded directly"
    exit 0
fi

# Option 3: Fallback message
echo ""
echo "⚠️  Automatischer Download fehlgeschlagen."
echo ""
echo "Bitte manuell herunterladen:"
echo "1. Gehe zu: https://solace.com/downloads/"
echo "2. Lade 'Solace JavaScript Messaging API' herunter"
echo "3. Kopiere 'solclient-full.js' nach: $TARGET_DIR"
echo ""

exit 1
