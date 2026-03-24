#!/bin/bash
# ============================================
# GRIDGermany - BTP Deployment Script
# ============================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

print_step() {
    echo -e "${GREEN}▶ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# ============================================
# Check Prerequisites
# ============================================
check_prerequisites() {
    print_header "Prüfe Voraussetzungen"
    
    local missing=0
    
    # Check cf CLI
    if command -v cf &> /dev/null; then
        print_step "Cloud Foundry CLI: $(cf version)"
    else
        print_error "Cloud Foundry CLI nicht gefunden"
        echo "  Installieren: brew install cloudfoundry/tap/cf-cli@8"
        missing=1
    fi
    
    # Check mbt
    if command -v mbt &> /dev/null; then
        print_step "MTA Build Tool: $(mbt --version)"
    else
        print_error "MTA Build Tool nicht gefunden"
        echo "  Installieren: npm install -g mbt"
        missing=1
    fi
    
    # Check Node.js
    if command -v node &> /dev/null; then
        print_step "Node.js: $(node --version)"
    else
        print_error "Node.js nicht gefunden"
        missing=1
    fi
    
    # Check npm
    if command -v npm &> /dev/null; then
        print_step "npm: $(npm --version)"
    else
        print_error "npm nicht gefunden"
        missing=1
    fi
    
    if [ $missing -eq 1 ]; then
        echo ""
        print_error "Bitte fehlende Tools installieren und erneut ausführen"
        exit 1
    fi
    
    echo ""
    print_step "Alle Voraussetzungen erfüllt ✓"
}

# ============================================
# Install Dependencies
# ============================================
install_dependencies() {
    print_header "Installiere Dependencies"
    
    # Approuter
    print_step "Installing approuter dependencies..."
    cd approuter && npm install && cd ..
    
    # Dashboard
    print_step "Installing dashboard dependencies..."
    cd app/dashboard && npm install && cd ../..
    
    # Fleet Control
    print_step "Installing fleet-control dependencies..."
    cd app/fleet-control && npm install && cd ../..
    
    print_step "Dependencies installiert ✓"
}

# ============================================
# Download Solace Library
# ============================================
download_solclient() {
    print_header "Lade Solace Client Library"
    
    chmod +x scripts/download-solclient.sh
    ./scripts/download-solclient.sh
}

# ============================================
# Build MTA
# ============================================
build_mta() {
    print_header "Baue MTA Archive"
    
    print_step "Running mbt build..."
    mbt build
    
    if [ -f mta_archives/grid-germany_1.0.0.mtar ]; then
        print_step "MTA Archive erstellt: mta_archives/grid-germany_1.0.0.mtar ✓"
    else
        print_error "MTA Build fehlgeschlagen"
        exit 1
    fi
}

# ============================================
# CF Login
# ============================================
cf_login() {
    print_header "Cloud Foundry Login"
    
    echo "Verfügbare API Endpoints:"
    echo "  - EU10 Trial: https://api.cf.eu10.hana.ondemand.com"
    echo "  - US10 Trial: https://api.cf.us10.hana.ondemand.com"
    echo "  - EU20:       https://api.cf.eu20.hana.ondemand.com"
    echo ""
    
    read -p "API Endpoint eingeben: " API_ENDPOINT
    
    cf login -a "$API_ENDPOINT"
}

# ============================================
# Deploy to BTP
# ============================================
deploy() {
    print_header "Deploye nach SAP BTP"
    
    if [ ! -f mta_archives/grid-germany_1.0.0.mtar ]; then
        print_error "MTA Archive nicht gefunden. Bitte zuerst 'build' ausführen."
        exit 1
    fi
    
    print_step "Deploying grid-germany_1.0.0.mtar..."
    cf deploy mta_archives/grid-germany_1.0.0.mtar
    
    print_step "Deployment abgeschlossen ✓"
    
    echo ""
    echo "Nächste Schritte:"
    echo "1. BTP Cockpit öffnen"
    echo "2. Role Collections 'GRIDGermany_Viewer' / 'GRIDGermany_Operator' zuweisen"
    echo "3. App URLs in der Space-Übersicht finden"
}

# ============================================
# Show App URLs
# ============================================
show_urls() {
    print_header "App URLs"
    
    cf apps
    
    echo ""
    echo "Dashboard:     https://<approuter-url>/dashboard/"
    echo "Fleet Control: https://<approuter-url>/fleet-control/"
}

# ============================================
# Undeploy
# ============================================
undeploy() {
    print_header "Undeploy GRIDGermany"
    
    print_warning "Dies löscht alle GRIDGermany Ressourcen!"
    read -p "Fortfahren? (y/N): " confirm
    
    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        cf undeploy grid-germany --delete-services --delete-service-keys
        print_step "Undeploy abgeschlossen ✓"
    else
        echo "Abgebrochen."
    fi
}

# ============================================
# Local Development
# ============================================
local_dev() {
    print_header "Lokale Entwicklung starten"
    
    echo "Starte HTTP Server für lokales Testen..."
    echo ""
    echo "Dashboard:     http://localhost:8080"
    echo "Fleet Control: http://localhost:8081"
    echo ""
    echo "Drücke Ctrl+C zum Beenden"
    echo ""
    
    # Start both servers
    cd app/dashboard/webapp && python3 -m http.server 8080 &
    PID1=$!
    cd app/fleet-control/webapp && python3 -m http.server 8081 &
    PID2=$!
    
    trap "kill $PID1 $PID2 2>/dev/null" EXIT
    wait
}

# ============================================
# Main Menu
# ============================================
show_menu() {
    print_header "GRIDGermany - Deployment"
    
    echo "Verfügbare Befehle:"
    echo ""
    echo "  1) check       - Prüfe Voraussetzungen"
    echo "  2) install     - Installiere Dependencies"
    echo "  3) solclient   - Lade Solace Library"
    echo "  4) build       - Baue MTA Archive"
    echo "  5) login       - CF Login"
    echo "  6) deploy      - Deploy nach BTP"
    echo "  7) urls        - Zeige App URLs"
    echo "  8) undeploy    - Entferne von BTP"
    echo "  9) local       - Lokale Entwicklung"
    echo "  0) all         - Kompletter Build & Deploy"
    echo ""
    echo "  q) Beenden"
    echo ""
}

# ============================================
# Run all steps
# ============================================
run_all() {
    check_prerequisites
    install_dependencies
    download_solclient
    build_mta
    cf_login
    deploy
    show_urls
}

# ============================================
# Main
# ============================================
case "$1" in
    check)      check_prerequisites ;;
    install)    install_dependencies ;;
    solclient)  download_solclient ;;
    build)      build_mta ;;
    login)      cf_login ;;
    deploy)     deploy ;;
    urls)       show_urls ;;
    undeploy)   undeploy ;;
    local)      local_dev ;;
    all)        run_all ;;
    *)
        show_menu
        read -p "Auswahl: " choice
        case "$choice" in
            1) check_prerequisites ;;
            2) install_dependencies ;;
            3) download_solclient ;;
            4) build_mta ;;
            5) cf_login ;;
            6) deploy ;;
            7) show_urls ;;
            8) undeploy ;;
            9) local_dev ;;
            0) run_all ;;
            q|Q) exit 0 ;;
            *) echo "Ungültige Auswahl" ;;
        esac
        ;;
esac
