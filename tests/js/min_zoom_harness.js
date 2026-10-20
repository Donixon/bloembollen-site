'use strict';
// Voert initMainMap uit app.js uit met Leaflet-stubs en print de aan setMinZoom doorgegeven waarden.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const boundsZoom = Number(process.argv[2]);
const setMinZoomCalls = [];

const noop = () => {};
const bounds = () => ({});
const map = {
  addLayer: noop,
  fitBounds: noop,
  getBoundsZoom: () => boundsZoom,
  setMinZoom: (zoom) => setMinZoomCalls.push(zoom),
  on: noop,
  scrollWheelZoom: { enable: noop, disable: noop },
};
const L = {
  latLngBounds: bounds,
  divIcon: () => ({}),
  icon: () => ({}),
  map: () => map,
  tileLayer: () => ({ addTo: noop }),
  markerClusterGroup: () => ({}),
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

const component = factories.bollen();
component.$refs = { mainMap: {} };
component.initMainMap();
process.stdout.write(JSON.stringify(setMinZoomCalls));
