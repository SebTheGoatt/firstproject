// Vehicle Routing Problem solver with capacity + time windows (CVRPTW).
//
//   1. Construction: regret-2 insertion. Each round, every unrouted order
//      computes its cheapest feasible insertion in every vehicle. The order
//      that would "lose the most" if it missed its best slot is inserted first.
//      High-priority orders get a bonus so they are placed early.
//   2. Improvement: local search until no move helps —
//        - 2-opt   (reverse a segment inside a route)
//        - relocate (move one stop anywhere, same or other route)
//        - swap     (exchange two stops between routes)
//
// Every move is checked against vehicle capacity, customer time windows and
// the driver's shift end.

const { roadKm, travelMinutes } = require('./geo');

const PRIORITY_BONUS = { high: 50, normal: 0, low: -5 };

function solve({ depot, vehicles, orders, roadFactor = 1.3, maxPasses = 50 }) {
  const started = Date.now();
  const points = [depot, ...orders];
  const n = points.length;

  // Distance matrix (km). Index 0 = depot, i = orders[i - 1].
  const dist = Array.from({ length: n }, () => new Float64Array(n));
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const d = roadKm(points[i], points[j], roadFactor);
      dist[i][j] = d;
      dist[j][i] = d;
    }
  }

  const ord = (idx) => orders[idx - 1];

  // Simulate a route; returns null when infeasible.
  function evaluate(vehicle, seq) {
    let load = 0;
    for (const idx of seq) load += ord(idx).weightKg || 0;
    if (load > vehicle.capacityKg + 1e-9) return null;
    if (vehicle.maxStops && seq.length > vehicle.maxStops) return null;

    let t = vehicle.shiftStart;
    let km = 0;
    let wait = 0;
    let prev = 0;
    const etas = [];
    for (const idx of seq) {
      const leg = dist[prev][idx];
      km += leg;
      t += travelMinutes(leg, vehicle.speedKmh);
      const o = ord(idx);
      if (o.windowStart != null && t < o.windowStart) {
        wait += o.windowStart - t;
        t = o.windowStart;
      }
      if (o.windowEnd != null && t > o.windowEnd + 1e-9) return null;
      etas.push(t);
      t += o.serviceMin || 0;
      prev = idx;
    }
    if (seq.length) {
      km += dist[prev][0];
      t += travelMinutes(dist[prev][0], vehicle.speedKmh);
    }
    if (t > vehicle.shiftEnd + 1e-9) return null;
    // Cost: distance first, with a small penalty on idle waiting time.
    return { km, end: t, wait, load, etas, cost: km + wait * 0.05 };
  }

  const routes = vehicles.map((v) => ({ vehicle: v, seq: [], ev: evaluate(v, []) }));
  const unrouted = new Set(orders.map((_, i) => i + 1));
  const unassigned = [];

  // ---------- Construction: regret-2 insertion ----------
  while (unrouted.size) {
    let pick = null;
    for (const idx of unrouted) {
      let best = null;
      let second = Infinity;
      for (let r = 0; r < routes.length; r++) {
        const route = routes[r];
        let routeBest = null;
        for (let pos = 0; pos <= route.seq.length; pos++) {
          const seq = route.seq.slice();
          seq.splice(pos, 0, idx);
          const ev = evaluate(route.vehicle, seq);
          if (!ev) continue;
          const delta = ev.cost - route.ev.cost;
          if (!routeBest || delta < routeBest.delta) routeBest = { r, pos, delta, ev, seq };
        }
        if (!routeBest) continue;
        if (!best || routeBest.delta < best.delta) {
          second = best ? best.delta : second;
          best = routeBest;
        } else if (routeBest.delta < second) {
          second = routeBest.delta;
        }
      }
      if (!best) {
        unrouted.delete(idx);
        unassigned.push({ orderId: ord(idx).id, reason: explainUnassignable(ord(idx), vehicles) });
        continue;
      }
      // Only one feasible vehicle => urgent; give it a big but finite regret.
      const regret = (second === Infinity ? 1000 : second - best.delta) +
        (PRIORITY_BONUS[ord(idx).priority] || 0);
      if (!pick || regret > pick.regret) pick = { idx, regret, ...best };
    }
    if (!pick) break;
    routes[pick.r].seq = pick.seq;
    routes[pick.r].ev = pick.ev;
    unrouted.delete(pick.idx);
  }

  const totalCost = () => routes.reduce((s, r) => s + r.ev.cost, 0);
  const constructionKm = routes.reduce((s, r) => s + r.ev.km, 0);

  // ---------- Improvement: local search ----------
  let passes = 0;
  let improved = true;
  while (improved && passes < maxPasses) {
    improved = false;
    passes++;

    // 2-opt inside each route
    for (const route of routes) {
      const s = route.seq;
      for (let i = 0; i < s.length - 1; i++) {
        for (let j = i + 1; j < s.length; j++) {
          const cand = s.slice(0, i).concat(s.slice(i, j + 1).reverse(), s.slice(j + 1));
          const ev = evaluate(route.vehicle, cand);
          if (ev && ev.cost < route.ev.cost - 1e-6) {
            route.seq = cand;
            route.ev = ev;
            improved = true;
            break;
          }
        }
        if (improved) break;
      }
    }

    // Relocate: move one stop to its best position anywhere
    for (let a = 0; a < routes.length; a++) {
      const A = routes[a];
      for (let i = 0; i < A.seq.length; i++) {
        const idx = A.seq[i];
        const aSeq = A.seq.slice(0, i).concat(A.seq.slice(i + 1));
        const aEv = evaluate(A.vehicle, aSeq);
        if (!aEv) continue;
        let best = null;
        for (let b = 0; b < routes.length; b++) {
          const B = routes[b];
          const base = b === a ? aSeq : B.seq;
          const baseCost = b === a ? 0 : B.ev.cost;
          for (let pos = 0; pos <= base.length; pos++) {
            if (b === a && pos === i) continue;
            const bSeq = base.slice();
            bSeq.splice(pos, 0, idx);
            const bEv = evaluate(B.vehicle, bSeq);
            if (!bEv) continue;
            const gain = b === a
              ? A.ev.cost - bEv.cost
              : A.ev.cost + baseCost - aEv.cost - bEv.cost;
            if (gain > 1e-6 && (!best || gain > best.gain)) best = { b, bSeq, bEv, gain };
          }
        }
        if (best) {
          if (best.b === a) {
            A.seq = best.bSeq;
            A.ev = best.bEv;
          } else {
            A.seq = aSeq;
            A.ev = aEv;
            routes[best.b].seq = best.bSeq;
            routes[best.b].ev = best.bEv;
          }
          improved = true;
          i = -1; // restart scan on the modified route
        }
      }
    }

    // Swap one stop between two routes
    for (let a = 0; a < routes.length; a++) {
      for (let b = a + 1; b < routes.length; b++) {
        const A = routes[a];
        const B = routes[b];
        let done = false;
        for (let i = 0; i < A.seq.length && !done; i++) {
          for (let j = 0; j < B.seq.length && !done; j++) {
            const aSeq = A.seq.slice();
            const bSeq = B.seq.slice();
            [aSeq[i], bSeq[j]] = [bSeq[j], aSeq[i]];
            const aEv = evaluate(A.vehicle, aSeq);
            if (!aEv) continue;
            const bEv = evaluate(B.vehicle, bSeq);
            if (!bEv) continue;
            if (aEv.cost + bEv.cost < A.ev.cost + B.ev.cost - 1e-6) {
              A.seq = aSeq; A.ev = aEv;
              B.seq = bSeq; B.ev = bEv;
              improved = true;
              done = true;
            }
          }
        }
      }
    }
  }

  const outRoutes = routes
    .filter((r) => r.seq.length)
    .map((r) => {
      let prev = 0;
      const stops = r.seq.map((idx, k) => {
        const legKm = dist[prev][idx];
        prev = idx;
        return { orderId: ord(idx).id, eta: r.ev.etas[k], legKm };
      });
      return {
        vehicleId: r.vehicle.id,
        stops,
        totalKm: r.ev.km,
        returnLegKm: dist[prev][0],
        startTime: r.vehicle.shiftStart,
        endTime: r.ev.end,
        waitMin: r.ev.wait,
        loadKg: r.ev.load,
        capacityKg: r.vehicle.capacityKg,
      };
    });

  const totalKm = outRoutes.reduce((s, r) => s + r.totalKm, 0);
  return {
    routes: outRoutes,
    unassigned,
    stats: {
      orders: orders.length,
      routed: orders.length - unassigned.length,
      vehiclesUsed: outRoutes.length,
      totalKm,
      constructionKm,
      improvementPct: constructionKm ? ((constructionKm - totalKm) / constructionKm) * 100 : 0,
      totalCost: totalCost(),
      passes,
      ms: Date.now() - started,
    },
  };
}

function explainUnassignable(order, vehicles) {
  const maxCap = Math.max(0, ...vehicles.map((v) => v.capacityKg));
  if (!vehicles.length) return 'No vehicles available';
  if ((order.weightKg || 0) > maxCap) return `Weight ${order.weightKg} kg exceeds largest vehicle (${maxCap} kg)`;
  return 'No vehicle can reach it inside its time window / driver shift';
}

module.exports = { solve };
