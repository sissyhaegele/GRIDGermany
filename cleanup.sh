#!/bin/bash
# ============================================
# BS GRID - Project Cleanup Script
# ============================================
# Räumt die Projektstruktur auf
# 
# Usage: ./cleanup.sh
# ============================================

echo "🧹 BS GRID - Project Cleanup"
echo ""

# Safety check
if [ ! -f "remote_controlled_sensor.py" ]; then
    echo "❌ Bitte im GRIDGermany Ordner ausführen!"
    exit 1
fi

# Create new directories
echo "📁 Erstelle neue Ordnerstruktur..."
mkdir -p dashboards
mkdir -p docs
mkdir -p btp-deployment
mkdir -p scripts

# Move dashboards
echo "📊 Verschiebe Dashboards..."
[ -f "dashboard-multi.html" ] && mv dashboard-multi.html dashboards/
[ -f "dashboard-fiori.html" ] && mv dashboard-fiori.html dashboards/
[ -f "fleet-control.html" ] && mv fleet-control.html dashboards/

# Move documentation
echo "📚 Verschiebe Dokumentation..."
[ -f "BS_GRID_POC_DOKUMENTATION.md" ] && mv BS_GRID_POC_DOKUMENTATION.md docs/
[ -f "SETUP_COMMANDS.sh" ] && mv SETUP_COMMANDS.sh docs/

# Move BTP deployment files
echo "☁️ Verschiebe BTP Deployment Dateien..."
[ -f "mta.yaml" ] && mv mta.yaml btp-deployment/
[ -f "xs-security.json" ] && mv xs-security.json btp-deployment/
[ -f "deploy.sh" ] && mv deploy.sh btp-deployment/
[ -d "app" ] && mv app btp-deployment/
[ -d "approuter" ] && mv approuter btp-deployment/

# Move scripts
echo "📜 Verschiebe Scripts..."
[ -f "start.sh" ] && mv start.sh scripts/
[ -f "stop-sensors.sh" ] && mv stop-sensors.sh scripts/

# Move backup into archive
echo "📦 Verschiebe Backup in Archive..."
[ -d "backup" ] && mv backup archive/

# Clean up Python cache
echo "🗑️ Lösche __pycache__..."
rm -rf __pycache__

# Clean up .DS_Store
echo "🗑️ Lösche .DS_Store..."
find . -name ".DS_Store" -delete

echo ""
echo "✅ Aufräumen abgeschlossen!"
echo ""
echo "Neue Struktur:"
echo ""
ls -la
echo ""
echo "📁 dashboards/"
ls dashboards/ 2>/dev/null
echo ""
echo "📁 docs/"
ls docs/ 2>/dev/null
echo ""
echo "📁 scripts/"
ls scripts/ 2>/dev/null
echo ""
echo "📁 btp-deployment/"
ls btp-deployment/ 2>/dev/null
