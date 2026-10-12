// Tiny JSON-file datastore. Everything lives in memory and is flushed to
// data/db.json shortly after each change, so the app survives restarts
// without needing a database server.

const fs = require('fs');
const path = require('path');
const { buildSeed } = require('./seed');

const DATA_DIR = process.env.ROUTEOPS_DATA_DIR || path.join(__dirname, '..', 'data');
const DB_FILE = path.join(DATA_DIR, 'db.json');

let state = null;
let saveTimer = null;

function load() {
  try {
    state = JSON.parse(fs.readFileSync(DB_FILE, 'utf8'));
  } catch {
    state = buildSeed();
    save();
  }
  return state;
}

function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    fs.mkdirSync(DATA_DIR, { recursive: true });
    const tmp = DB_FILE + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(state, null, 2));
    fs.renameSync(tmp, DB_FILE);
  }, 250);
}

function reset() {
  state = buildSeed();
  save();
  return state;
}

function get() {
  return state || load();
}

function nextId(kind, prefix) {
  const s = get();
  const n = s.counters[kind]++;
  return `${prefix}-${n}`;
}

module.exports = { load, save, reset, get, nextId };
