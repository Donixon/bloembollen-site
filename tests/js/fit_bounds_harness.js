'use strict';
// Voert initMainMap + loadMap uit app.js uit met Leaflet-stubs; argument is een JSON-lijst met kaartpunten.
// Print de fitBounds-aanroepen (punten + opties) als JSON.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const items = JSON.parse(process.argv[2]);
const fitCalls = [];

const noop = () => {};
const map = {
  addLayer: noop,
  fitBounds: (bounds, options) => fitCalls.push({ points: bounds.points || null, options: options || null }),
  getBoundsZoom: () => 6,
  setMinZoom: noop,
  invalidateSize: noop,
  on: noop,
  scrollWheelZoom: { enable: noop, disable: noop },
};
const L = {
  latLngBounds: (a) => ({ points: a }),
  divIcon: () => ({}),
  icon: () => ({}),
  map: () => map,
  tileLayer: () => ({ addTo: noop }),
  markerClusterGroup: () => ({ addLayers: noop }),
  marker: (latlng) => ({
    getLatLng: () => latlng,
    bindPopup: noop,
    on: noop,
  }),
  popup: () => ({}),
};

const factories = {};
let alpineInit;
const sandbox = {
  L,
  Alpine: { data: (name, factory) => (factories[name] = factory) },
  document: {
    addEventListener: (type, handler) => {
      if (type === 'alpine:init') alpineInit = handler;
    },
    createElement: () => ({}),
  },
  fetch: async () => ({ ok: true, json: async () => items }),
  window: {},
  console,
};
sandbox.window = sandbox;

const source = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'static', 'js', 'app.js'),
  'utf8',
);
vm.runInNewContext(source, sandbox, { filename: 'app.js' });
alpineInit();

(async () => {
  const component = factories.bollen();
  component.$refs = { mainMap: {} };
  component.initMainMap();
  const afterInit = fitCalls.length;
  await component.loadMap();
  await component.loadMap();
  process.stdout.write(JSON.stringify({ afterInit, calls: fitCalls.slice(afterInit) }));
})();
