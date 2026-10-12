// Demo data: a delivery hub in San Antonio, TX with a small mixed fleet and
// a day's worth of orders. Deterministic so every reset looks the same.

function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

const FIRST = ['Maria', 'James', 'Ana', 'Robert', 'Linda', 'Carlos', 'Patricia', 'Michael', 'Sofia', 'David',
  'Elena', 'Daniel', 'Grace', 'Luis', 'Hannah', 'Jose', 'Olivia', 'Marcus', 'Isabel', 'Tyler'];
const LAST = ['Garcia', 'Johnson', 'Martinez', 'Smith', 'Lopez', 'Brown', 'Hernandez', 'Davis', 'Rodriguez',
  'Wilson', 'Gonzalez', 'Moore', 'Perez', 'Taylor', 'Sanchez', 'Anderson', 'Ramirez', 'Thomas'];
const STREETS = ['Broadway', 'Fredericksburg Rd', 'Blanco Rd', 'Culebra Rd', 'Nogalitos St', 'Austin Hwy',
  'Commerce St', 'Hildebrand Ave', 'Zarzamora St', 'Bandera Rd', 'Babcock Rd', 'Wurzbach Rd',
  'Pleasanton Rd', 'Rigsby Ave', 'Vance Jackson Rd', 'Callaghan Rd', 'Walzem Rd', 'Military Dr'];
const WINDOWS = [
  ['08:00', '12:00'], ['09:00', '13:00'], ['12:00', '17:00'], ['13:00', '18:00'],
  ['08:00', '18:00'], ['08:00', '18:00'], ['08:00', '18:00'], ['10:00', '14:00'],
];

function hhmm(s) {
  const [h, m] = s.split(':').map(Number);
  return h * 60 + m;
}

function buildSeed() {
  const rand = rng(20261012);
  const depot = {
    id: 'DEP-1',
    name: 'San Antonio Hub',
    address: '1 Logistics Way, San Antonio, TX',
    lat: 29.4520,
    lng: -98.5100,
  };

  const drivers = [
    { id: 'DRV-1', name: 'Alex Rivera', phone: '(210) 555-0101', shiftStart: 480, shiftEnd: 1080 },
    { id: 'DRV-2', name: 'Jordan Lee', phone: '(210) 555-0102', shiftStart: 480, shiftEnd: 1080 },
    { id: 'DRV-3', name: 'Sam Torres', phone: '(210) 555-0103', shiftStart: 480, shiftEnd: 1020 },
    { id: 'DRV-4', name: 'Casey Nguyen', phone: '(210) 555-0104', shiftStart: 540, shiftEnd: 1080 },
    { id: 'DRV-5', name: 'Morgan Diaz', phone: '(210) 555-0105', shiftStart: 480, shiftEnd: 1080 },
    { id: 'DRV-6', name: 'Riley Brooks', phone: '(210) 555-0106', shiftStart: 480, shiftEnd: 960 },
  ].map((d) => ({ ...d, active: true }));

  const vehicles = [
    { id: 'VEH-1', name: 'Van 01', type: 'Cargo Van', capacityKg: 700, speedKmh: 38, driverId: 'DRV-1' },
    { id: 'VEH-2', name: 'Van 02', type: 'Cargo Van', capacityKg: 700, speedKmh: 38, driverId: 'DRV-2' },
    { id: 'VEH-3', name: 'Van 03', type: 'Cargo Van', capacityKg: 700, speedKmh: 38, driverId: 'DRV-3' },
    { id: 'VEH-4', name: 'Box Truck 01', type: 'Box Truck', capacityKg: 1800, speedKmh: 34, driverId: 'DRV-4' },
    { id: 'VEH-5', name: 'Sprinter 01', type: 'Sprinter', capacityKg: 1100, speedKmh: 36, driverId: 'DRV-5' },
    { id: 'VEH-6', name: 'E-Bike 01', type: 'Cargo E-Bike', capacityKg: 90, speedKmh: 18, driverId: 'DRV-6' },
  ].map((v) => ({ ...v, depotId: depot.id, active: true }));

  const orders = [];
  for (let i = 0; i < 48; i++) {
    // Spread customers within ~14 km of the hub, denser near the center.
    const r = 0.13 * Math.sqrt(rand());
    const theta = rand() * Math.PI * 2;
    const lat = +(depot.lat - 0.03 + r * Math.cos(theta)).toFixed(5);
    const lng = +(depot.lng + 0.02 + r * Math.sin(theta) * 1.15).toFixed(5);
    const [ws, we] = WINDOWS[Math.floor(rand() * WINDOWS.length)];
    const big = rand() < 0.12;
    orders.push({
      id: `ORD-${1001 + i}`,
      customer: `${FIRST[Math.floor(rand() * FIRST.length)]} ${LAST[Math.floor(rand() * LAST.length)]}`,
      phone: `(210) 555-${String(2000 + i).padStart(4, '0')}`,
      address: `${100 + Math.floor(rand() * 9800)} ${STREETS[Math.floor(rand() * STREETS.length)]}, San Antonio, TX`,
      lat,
      lng,
      weightKg: big ? Math.round(80 + rand() * 160) : Math.round(2 + rand() * 28),
      serviceMin: big ? 10 : 4,
      windowStart: hhmm(ws),
      windowEnd: hhmm(we),
      priority: rand() < 0.15 ? 'high' : 'normal',
      notes: big ? 'Heavy item – 2-person lift may be needed' : '',
    });
  }

  return {
    depots: [depot],
    drivers,
    vehicles,
    orders: orders.map((o) => ({ ...o, status: 'pending', routeId: null, eta: null, createdAt: Date.now() })),
    routes: [],
    events: [],
    settings: { roadFactor: 1.3, simSpeed: 30, autopilot: true, successRate: 0.94 },
    sim: { clock: 7 * 60 + 45, running: false },
    counters: { order: 1001 + orders.length, route: 1, driver: drivers.length + 1, vehicle: vehicles.length + 1 },
  };
}

module.exports = { buildSeed };
