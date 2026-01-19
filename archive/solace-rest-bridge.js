#!/usr/bin/env node
/**
 * Solace to SAP Build REST API Bridge
 * 
 * Subscribes to Solace events and exposes REST endpoints for SAP Build Apps
 */

const express = require('express');
const mqtt = require('mqtt');
const cors = require('cors');
const axios = require('axios');

const app = express();
app.use(cors());
app.use(express.json());

// Configuration
const CONFIG = {
  solace: {
    host: process.env.SOLACE_HOST || 'localhost',
    port: parseInt(process.env.SOLACE_PORT || '1883'),
    username: process.env.SOLACE_USERNAME,
    password: process.env.SOLACE_PASSWORD
  },
  webhook: {
    outage: process.env.WEBHOOK_OUTAGE_URL || null,
    anomaly: process.env.WEBHOOK_ANOMALY_URL || null
  },
  server: {
    port: parseInt(process.env.PORT || '3000')
  }
};

// In-memory event store (use Redis/database for production)
const eventStore = {
  heartbeats: [],
  statusUpdates: [],
  anomalies: [],
  outages: [],
  maxSize: 500
};

// Statistics
const stats = {
  messagesReceived: 0,
  lastUpdate: null,
  startTime: Date.now()
};

// Store event with size limit
function storeEvent(category, event) {
  eventStore[category].unshift(event);
  if (eventStore[category].length > eventStore.maxSize) {
    eventStore[category].pop();
  }
  stats.messagesReceived++;
  stats.lastUpdate = new Date().toISOString();
}

// Connect to Solace
console.log('Connecting to Solace...');
console.log(`  Host: ${CONFIG.solace.host}:${CONFIG.solace.port}`);
console.log(`  Username: ${CONFIG.solace.username || '(none)'}`);

const solaceClient = mqtt.connect(
  `mqtt://${CONFIG.solace.host}:${CONFIG.solace.port}`,
  {
    username: CONFIG.solace.username,
    password: CONFIG.solace.password,
    reconnectPeriod: 5000
  }
);

solaceClient.on('connect', () => {
  console.log('✓ Connected to Solace broker\n');
  
  // Subscribe to all sensor events
  const topics = [
    'bs/+/+/+/powerline/heartbeat/v1/+',
    'bs/+/+/+/powerline/statusUpdated/v1/+',
    'bs/+/+/+/powerline/anomalyDetected/v1/+',
    'bs/+/outage/detected/v1/+',
    'bs/+/outage/update/v1/+',
    'bs/+/outage/resolved/v1/+'
  ];
  
  topics.forEach(topic => {
    solaceClient.subscribe(topic, (err) => {
      if (err) {
        console.error(`✗ Failed to subscribe to ${topic}:`, err.message);
      } else {
        console.log(`✓ Subscribed to: ${topic}`);
      }
    });
  });
  
  console.log('\n✓ All subscriptions active');
});

solaceClient.on('error', (err) => {
  console.error('✗ Solace connection error:', err.message);
});

solaceClient.on('message', async (topic, message) => {
  try {
    const event = JSON.parse(message.toString());
    
    // Route by event type
    if (topic.includes('heartbeat')) {
      storeEvent('heartbeats', event);
    } 
    else if (topic.includes('statusUpdated')) {
      storeEvent('statusUpdates', event);
    } 
    else if (topic.includes('anomalyDetected')) {
      storeEvent('anomalies', event);
      
      // Trigger webhook for anomalies if configured
      if (CONFIG.webhook.anomaly) {
        try {
          await axios.post(CONFIG.webhook.anomaly, event);
          console.log(`✓ Anomaly webhook triggered: ${event.eventId}`);
        } catch (err) {
          console.error(`✗ Anomaly webhook failed: ${err.message}`);
        }
      }
    } 
    else if (topic.includes('outage')) {
      storeEvent('outages', event);
      
      // Trigger webhook for outages if configured
      if (topic.includes('detected') && CONFIG.webhook.outage) {
        try {
          await axios.post(CONFIG.webhook.outage, event);
          console.log(`✓ Outage workflow triggered: ${event.outageId}`);
        } catch (err) {
          console.error(`✗ Outage webhook failed: ${err.message}`);
        }
      }
    }
  } catch (err) {
    console.error('✗ Error processing message:', err.message);
  }
});

// ============================================================================
// REST API ENDPOINTS FOR SAP BUILD APPS
// ============================================================================

// Health check
app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    solace: {
      connected: solaceClient.connected,
      messagesReceived: stats.messagesReceived,
      lastUpdate: stats.lastUpdate
    },
    uptime: Math.floor((Date.now() - stats.startTime) / 1000)
  });
});

// Dashboard summary
app.get('/api/dashboard', (req, res) => {
  const now = Date.now();
  const twoMinutesAgo = now - 120000;
  const thirtyMinutesAgo = now - 1800000;
  
  // Count active sensors (heartbeat in last 2 minutes)
  const activeSensors = new Set(
    eventStore.heartbeats
      .filter(hb => new Date(hb.timestamp) > twoMinutesAgo)
      .map(hb => hb.powerlineId)
  ).size;
  
  // Count current anomalies (last 30 minutes)
  const currentAnomalies = eventStore.anomalies
    .filter(a => new Date(a.timestamp) > thirtyMinutesAgo).length;
  
  // Count active outages (not resolved)
  const activeOutages = eventStore.outages
    .filter(o => o.eventType === 'OutageDetected').length;
  
  // Calculate district power averages
  const districtPower = {};
  const recentStatus = eventStore.statusUpdates.slice(0, 100);
  
  recentStatus.forEach(s => {
    if (s.status === 'normal' && s.measurements) {
      if (!districtPower[s.region]) {
        districtPower[s.region] = { total: 0, count: 0 };
      }
      districtPower[s.region].total += s.measurements.power.active;
      districtPower[s.region].count += 1;
    }
  });
  
  const districtAverages = Object.keys(districtPower)
    .map(district => ({
      district,
      avgPower: parseFloat((districtPower[district].total / districtPower[district].count).toFixed(2)),
      sensorCount: districtPower[district].count
    }))
    .sort((a, b) => a.district.localeCompare(b.district));
  
  res.json({
    summary: {
      activeSensors,
      currentAnomalies,
      activeOutages,
      totalDistricts: 12
    },
    districtPower: districtAverages,
    lastUpdate: stats.lastUpdate,
    performance: {
      messagesReceived: stats.messagesReceived,
      uptimeSeconds: Math.floor((now - stats.startTime) / 1000)
    }
  });
});

// Get all active sensors
app.get('/api/sensors', (req, res) => {
  const twoMinutesAgo = Date.now() - 120000;
  
  const activeSensors = eventStore.heartbeats
    .filter(hb => new Date(hb.timestamp) > twoMinutesAgo)
    .map(hb => ({
      sensorId: hb.powerlineId,
      region: hb.region,
      status: hb.status,
      lastSeen: hb.timestamp
    }));
  
  // Remove duplicates (keep most recent)
  const uniqueSensors = [];
  const seen = new Set();
  
  activeSensors.forEach(sensor => {
    if (!seen.has(sensor.sensorId)) {
      uniqueSensors.push(sensor);
      seen.add(sensor.sensorId);
    }
  });
  
  res.json({
    sensors: uniqueSensors,
    count: uniqueSensors.length,
    timestamp: new Date().toISOString()
  });
});

// Get sensors by district
app.get('/api/sensors/district/:district', (req, res) => {
  const { district } = req.params;
  const twoMinutesAgo = Date.now() - 120000;
  
  const districtSensors = eventStore.heartbeats
    .filter(hb => 
      hb.region === district && 
      new Date(hb.timestamp) > twoMinutesAgo
    )
    .map(hb => ({
      sensorId: hb.powerlineId,
      status: hb.status,
      lastSeen: hb.timestamp
    }));
  
  res.json({
    district,
    sensors: districtSensors,
    count: districtSensors.length
  });
});

// Get status updates for specific district
app.get('/api/status/district/:district', (req, res) => {
  const { district } = req.params;
  const limit = parseInt(req.query.limit) || 50;
  
  const districtStatus = eventStore.statusUpdates
    .filter(s => s.region === district)
    .slice(0, limit)
    .map(s => ({
      sensorId: s.powerlineId,
      timestamp: s.timestamp,
      status: s.status,
      voltage: s.measurements?.voltage?.l1,
      current: s.measurements?.current?.l1,
      power: s.measurements?.power?.active,
      temperature: s.measurements?.temperature
    }));
  
  res.json({
    district,
    status: districtStatus,
    count: districtStatus.length
  });
});

// Get specific sensor details
app.get('/api/sensor/:sensorId', (req, res) => {
  const { sensorId } = req.params;
  
  // Get latest heartbeat
  const heartbeat = eventStore.heartbeats.find(hb => hb.powerlineId === sensorId);
  
  // Get latest status
  const status = eventStore.statusUpdates.find(s => s.powerlineId === sensorId);
  
  // Get recent anomalies
  const anomalies = eventStore.anomalies
    .filter(a => a.powerlineId === sensorId)
    .slice(0, 10);
  
  if (!heartbeat && !status) {
    return res.status(404).json({ error: 'Sensor not found' });
  }
  
  res.json({
    sensorId,
    heartbeat,
    status,
    anomalies,
    anomalyCount: anomalies.length
  });
});

// Get current anomalies
app.get('/api/anomalies', (req, res) => {
  const hoursAgo = parseInt(req.query.hours) || 1;
  const timeAgo = Date.now() - (hoursAgo * 3600000);
  
  const currentAnomalies = eventStore.anomalies
    .filter(a => new Date(a.timestamp) > timeAgo)
    .map(a => ({
      eventId: a.eventId,
      sensorId: a.powerlineId,
      region: a.region,
      timestamp: a.timestamp,
      type: a.anomalyDetails?.type,
      voltageDeviation: a.anomalyDetails?.voltage_deviation_pct,
      currentRatio: a.anomalyDetails?.current_ratio,
      temperatureAboveNormal: a.anomalyDetails?.temperature_above_normal
    }));
  
  res.json({
    anomalies: currentAnomalies,
    count: currentAnomalies.length,
    timeRange: `Last ${hoursAgo} hour(s)`
  });
});

// Get active outages
app.get('/api/outages', (req, res) => {
  const outages = eventStore.outages.slice(0, 50).map(o => ({
    eventId: o.eventId,
    outageId: o.outageId,
    region: o.region,
    timestamp: o.timestamp,
    severity: o.severity,
    estimatedImpact: o.estimatedImpact,
    status: o.status
  }));
  
  res.json({
    outages,
    count: outages.length
  });
});

// Get statistics
app.get('/api/stats', (req, res) => {
  res.json({
    eventCounts: {
      heartbeats: eventStore.heartbeats.length,
      statusUpdates: eventStore.statusUpdates.length,
      anomalies: eventStore.anomalies.length,
      outages: eventStore.outages.length
    },
    performance: {
      messagesReceived: stats.messagesReceived,
      lastUpdate: stats.lastUpdate,
      uptimeSeconds: Math.floor((Date.now() - stats.startTime) / 1000)
    },
    solace: {
      connected: solaceClient.connected
    }
  });
});

// Start server
app.listen(CONFIG.server.port, () => {
  console.log('\n' + '='.repeat(60));
  console.log('✓ Solace to SAP Build REST API Bridge');
  console.log('='.repeat(60));
  console.log(`\n📡 Server running on port ${CONFIG.server.port}`);
  console.log('\nEndpoints:');
  console.log(`  Health:      http://localhost:${CONFIG.server.port}/health`);
  console.log(`  Dashboard:   http://localhost:${CONFIG.server.port}/api/dashboard`);
  console.log(`  Sensors:     http://localhost:${CONFIG.server.port}/api/sensors`);
  console.log(`  Anomalies:   http://localhost:${CONFIG.server.port}/api/anomalies`);
  console.log(`  Outages:     http://localhost:${CONFIG.server.port}/api/outages`);
  console.log(`  Stats:       http://localhost:${CONFIG.server.port}/api/stats`);
  console.log('\n' + '='.repeat(60) + '\n');
});

// Graceful shutdown
process.on('SIGINT', () => {
  console.log('\n\nShutting down gracefully...');
  solaceClient.end();
  process.exit(0);
});
