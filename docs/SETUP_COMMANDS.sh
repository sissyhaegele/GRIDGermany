#!/bin/bash
# ============================================
# GRIDGermany - Setup & Migration Commands
# ============================================
# 
# Diese Datei enthält alle Befehle zur Migration
# des bestehenden Projekts nach SAP BTP
#
# Ausführen im Projekt-Verzeichnis:
#   /Users/sissyhaegele/Projekte/GRIDGermany/
# ============================================

# ============================================
# SCHRITT 0: Voraussetzungen installieren
# ============================================

# Cloud Foundry CLI (falls nicht vorhanden)
brew install cloudfoundry/tap/cf-cli@8

# MTA Build Tool
npm install -g mbt

# ============================================
# SCHRITT 1: BTP Projektstruktur erstellen
# ============================================

cd /Users/sissyhaegele/Projekte/GRIDGermany

# Neue Verzeichnisse erstellen
mkdir -p btp-deployment/{app/{dashboard/webapp,fleet-control/webapp},approuter,scripts}

# ============================================
# SCHRITT 2: Bestehende Dateien kopieren
# ============================================

# Solace Library kopieren
cp solclient-full.js btp-deployment/app/dashboard/webapp/

# (Optional) Bestehende HTML-Dateien als Backup
cp dashboard-multi.html btp-deployment/backup-dashboard.html
cp fleet-control.html btp-deployment/backup-fleet-control.html

# ============================================
# SCHRITT 3: BTP Konfigurationsdateien erstellen
# ============================================

# Die neuen Dateien werden aus dem grid-germany Ordner kopiert
# (Diese wurden von Claude erstellt)

# ============================================
# SCHRITT 4: Git Repository aktualisieren
# ============================================

cd /Users/sissyhaegele/Projekte/GRIDGermany

# Neuen BTP-Branch erstellen
git checkout -b feature/btp-deployment

# Dateien hinzufügen
git add btp-deployment/
git commit -m "Add SAP BTP deployment configuration"

# ============================================
# SCHRITT 5: Dependencies installieren
# ============================================

cd btp-deployment

# Approuter
cd approuter && npm install && cd ..

# Dashboard (optional, keine echten deps)
cd app/dashboard && npm install && cd ../..

# Fleet Control (optional, keine echten deps)
cd app/fleet-control && npm install && cd ../..

# ============================================
# SCHRITT 6: MTA Build
# ============================================

cd /Users/sissyhaegele/Projekte/GRIDGermany/btp-deployment

# MTA Archive bauen
mbt build

# Prüfen ob erfolgreich
ls -la mta_archives/

# ============================================
# SCHRITT 7: BTP Login & Deployment
# ============================================

# Cloud Foundry Login
# EU10 Trial: https://api.cf.eu10.hana.ondemand.com
# US10 Trial: https://api.cf.us10.hana.ondemand.com
cf login -a https://api.cf.eu10.hana.ondemand.com

# Deployment
cf deploy mta_archives/grid-germany_1.0.0.mtar

# ============================================
# SCHRITT 8: Rollen zuweisen (BTP Cockpit)
# ============================================

# 1. BTP Cockpit öffnen: https://cockpit.eu10.hana.ondemand.com
# 2. Subaccount → Security → Role Collections
# 3. "BS_GRID_Viewer" oder "BS_GRID_Operator" bearbeiten
# 4. Benutzer hinzufügen

# ============================================
# SCHRITT 9: App URLs anzeigen
# ============================================

cf apps

# URLs haben das Format:
# https://<approuter-route>/dashboard/
# https://<approuter-route>/fleet-control/

# ============================================
# NÜTZLICHE BEFEHLE
# ============================================

# Logs anzeigen
cf logs bs-grid-approuter --recent

# App Status
cf app bs-grid-approuter

# Undeploy (alles löschen)
cf undeploy grid-germany --delete-services --delete-service-keys

# Lokale Entwicklung (ohne BTP)
cd app/dashboard/webapp && python3 -m http.server 8080
cd app/fleet-control/webapp && python3 -m http.server 8081
