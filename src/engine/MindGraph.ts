// MindGraph.ts — canvas force-directed knowledge graph (the agent's living mind).
import { buildMind, CATS, GROWTH, META, type RawEdge } from '../data/mind';
import { AGENT } from '../data/seed';
import type { NodeType, GrowthSpec, LearnSpec } from '../data/types';
import { tr } from '../lib/i18n';
import { SwarmStage } from './swarmStage';

export interface GraphNode {
  id: number;
  label: string;
  type: NodeType;
  topic: string | null;
  x: number;
  y: number;
  vx: number;
  vy: number;
  heat: number;
  spawn: number;
  mass: number;
  r: number;
  born: number;
  tvis: number;
}

// edge: [a, b, weight, bornDay]
type Edge = [number, number, number, number];

interface Pulse {
  a: number;
  b: number;
  t: number;
  sp: number;
}

interface Dust {
  x: number;
  y: number;
  z: number;
}

interface Callbacks {
  hover: (n: GraphNode | null) => void;
  select: (n: GraphNode | null) => void;
  thought: (n: { label: string; query?: boolean } | null) => void;
  grow: (n: GraphNode) => void;
}

type ScreenPoint = { clientX: number; clientY: number };

export class MindGraph {
  canvas: HTMLCanvasElement;
  ctx: CanvasRenderingContext2D;
  dpr: number;
  on: Callbacks = { hover: () => {}, select: () => {}, thought: () => {}, grow: () => {} };
  accent = '#ffb152';
  motion = true;
  filter: Set<NodeType> | null = null;
  searchMatch: Set<number> | null = null;

  nodes: GraphNode[];
  edges: Edge[];
  self: GraphNode;
  adj: number[][];
  degree: number[];

  MAXDAY: number;
  day: number;
  scrub = false;

  cam = { x: 0, y: 0, scale: 1, tScale: 1 };
  anchorX = 0.5;
  anchorXT = 0.5;
  anchorY = 0.5;
  interactive = true;
  mouse = { x: 0, y: 0, down: false, moved: false };
  hoverId: number | null = null;
  selectId: number | null = null;
  dragId: number | null = null;
  panning = false;
  pulses: Pulse[] = [];
  dust: Dust[];
  growIdx = 0;
  /** 蜂群运行时的临时叠加层(契约/worker/冲突/修复实时长在图上,跑完 clear)。 */
  stage = new SwarmStage();

  W = 0;
  H = 0;
  raf = 0;
  lastThought = 0;
  lastGrow = 0;
  private _fly: { x: number; y: number; t: number } | null = null;
  private _ro: ResizeObserver | null = null;
  private _pinch: number | null = null;

  constructor(canvas: HTMLCanvasElement, graph?: ReturnType<typeof buildMind>) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d')!;
    this.dpr = Math.min(2, window.devicePixelRatio || 1);

    const { nodes: rawNodes, edges: rawEdges, self: rawSelf } = graph ?? buildMind();
    const N = rawNodes.length;
    this.adj = rawNodes.map(() => []);
    this.degree = rawNodes.map(() => 0);
    rawEdges.forEach(([a, b]) => {
      this.adj[a].push(b);
      this.adj[b].push(a);
      this.degree[a]++;
      this.degree[b]++;
    });

    // promote raw nodes to physics nodes
    this.nodes = rawNodes.map((n, i): GraphNode => {
      const ci = (i / N) * Math.PI * 2;
      const x = n.type === 'self' ? 0 : Math.cos(ci) * 240 + (Math.random() - 0.5) * 40;
      const y = n.type === 'self' ? 0 : Math.sin(ci) * 200 + (Math.random() - 0.5) * 40;
      const r = n.type === 'self' ? 17 : n.type === 'topic' ? 7 + Math.min(6, this.degree[i]) : 3.4 + Math.min(4, this.degree[i] * 0.7);
      const mass = n.type === 'self' ? 8 : n.type === 'topic' ? 3 : 1;
      return { ...n, x, y, vx: 0, vy: 0, heat: 0, spawn: 1, mass, r, born: 0, tvis: 1 };
    });
    this.self = this.nodes[rawSelf.id];
    this.edges = rawEdges.map((e: RawEdge): Edge => [e[0], e[1], e[2], 0]);

    // timeline: assign a "born day" (0 = launch, MAXDAY = today) — kept for fade-in bloom rings
    this.MAXDAY = AGENT.uptimeDays;
    const hash = (s: string): number => {
      let h = 0;
      for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
      return h;
    };
    this.nodes.forEach((n) => {
      if (n.type === 'self') n.born = 0;
      else if (n.type === 'topic') n.born = 1 + (hash(n.label) % 7);
      else {
        const lo = n.type === 'source' || n.type === 'person' ? 2 : 5;
        n.born = lo + (hash(n.label) % (this.MAXDAY - lo));
      }
    });
    this.edges.forEach((e) => {
      e[3] = Math.max(this.nodes[e[0]].born, this.nodes[e[1]].born);
    });
    this.day = this.MAXDAY;

    this.dust = Array.from({ length: 70 }, () => ({
      x: (Math.random() - 0.5) * 1400,
      y: (Math.random() - 0.5) * 1000,
      z: 0.3 + Math.random() * 0.7,
    }));

    this.resize();
    for (let k = 0; k < 260; k++) this.tick(1); // warmup settle
    this.fit();
    this.cam.scale = this.cam.tScale;

    this._bind();
    this.lastThought = performance.now();
    this.lastGrow = performance.now();
    this.raf = requestAnimationFrame(this.frame);
  }

  private _bind(): void {
    const c = this.canvas;
    this._ro = new ResizeObserver(() => this.resize());
    this._ro.observe(c.parentElement || c);
    c.addEventListener('mousemove', this.onMove);
    c.addEventListener('mousedown', this.onDown);
    window.addEventListener('mouseup', this.onUp);
    c.addEventListener('dblclick', this.onDblClick);
    c.addEventListener('wheel', this.onWheel, { passive: false });
    c.addEventListener('mouseleave', this.onLeave);
    c.addEventListener('touchstart', this.onTouchStart, { passive: false });
    c.addEventListener('touchmove', this.onTouchMove, { passive: false });
    window.addEventListener('touchend', this.onTouchEnd);
  }

  destroy(): void {
    cancelAnimationFrame(this.raf);
    this._ro?.disconnect();
    window.removeEventListener('mouseup', this.onUp);
    window.removeEventListener('touchend', this.onTouchEnd);
    this.canvas.removeEventListener('mousemove', this.onMove);
    this.canvas.removeEventListener('mousedown', this.onDown);
    this.canvas.removeEventListener('dblclick', this.onDblClick);
    this.canvas.removeEventListener('wheel', this.onWheel);
    this.canvas.removeEventListener('mouseleave', this.onLeave);
    this.canvas.removeEventListener('touchstart', this.onTouchStart);
    this.canvas.removeEventListener('touchmove', this.onTouchMove);
  }

  private onLeave = (): void => {
    if (this.hoverId !== null && this.selectId === null) {
      this.hoverId = null;
      this.on.hover(null);
    }
  };

  onTouchStart = (e: TouchEvent): void => {
    if (e.touches.length === 2) {
      this._pinch = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
      this.dragId = null;
      this.panning = false;
      return;
    }
    e.preventDefault();
    const t = e.touches[0];
    this.onDown({ clientX: t.clientX, clientY: t.clientY });
  };

  onTouchMove = (e: TouchEvent): void => {
    if (e.touches.length === 2 && this._pinch) {
      e.preventDefault();
      const d = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
      const r = this.canvas.getBoundingClientRect();
      const cx = (e.touches[0].clientX + e.touches[1].clientX) / 2 - r.left;
      const cy = (e.touches[0].clientY + e.touches[1].clientY) / 2 - r.top;
      const before = this.s2w(cx, cy);
      this.cam.scale = Math.max(0.35, Math.min(3.2, this.cam.scale * (d / this._pinch)));
      this.cam.tScale = this.cam.scale;
      const after = this.s2w(cx, cy);
      this.cam.x += before.x - after.x;
      this.cam.y += before.y - after.y;
      this._pinch = d;
      return;
    }
    e.preventDefault();
    const t = e.touches[0];
    this.onMove({ clientX: t.clientX, clientY: t.clientY });
  };

  onTouchEnd = (): void => {
    this._pinch = null;
    this.onUp();
  };

  resize = (): void => {
    const r = (this.canvas.parentElement || this.canvas).getBoundingClientRect();
    this.W = r.width;
    this.H = r.height;
    this.canvas.width = this.W * this.dpr;
    this.canvas.height = this.H * this.dpr;
    this.canvas.style.width = this.W + 'px';
    this.canvas.style.height = this.H + 'px';
  };

  // world <-> screen
  s2w(sx: number, sy: number): { x: number; y: number } {
    return { x: (sx - this.W * this.anchorX) / this.cam.scale + this.cam.x, y: (sy - this.H * this.anchorY) / this.cam.scale + this.cam.y };
  }
  w2s(wx: number, wy: number): { x: number; y: number } {
    return { x: (wx - this.cam.x) * this.cam.scale + this.W * this.anchorX, y: (wy - this.cam.y) * this.cam.scale + this.H * this.anchorY };
  }
  private _centroid(): { x: number; y: number } {
    let x = 0, y = 0;
    this.nodes.forEach((n) => { x += n.x; y += n.y; });
    return { x: x / this.nodes.length, y: y / this.nodes.length };
  }
  private _fitScale(): number {
    let a = 1e9, b = 1e9, c = -1e9, d = -1e9;
    this.nodes.forEach((n) => { a = Math.min(a, n.x); b = Math.min(b, n.y); c = Math.max(c, n.x); d = Math.max(d, n.y); });
    return Math.min(this.W / (c - a + 160), this.H / (d - b + 160), 1.4);
  }

  dock(on: boolean, narrow?: boolean): void {
    const ct = this._centroid();
    this.flyTo(ct.x, ct.y);
    if (on) {
      if (narrow) {
        this.anchorXT = 0.5;
        this.cam.tScale = this._fitScale() * 0.7;
      } else {
        this.anchorXT = 0.21;
        this.cam.tScale = 0.62;
      }
      this.interactive = false;
      this.select(null);
      this.hoverId = null;
    } else {
      this.anchorXT = 0.5;
      this.cam.tScale = this._fitScale();
      this.interactive = true;
    }
  }

  lightLabels(labels: string[], intensity?: number): void {
    (labels || []).forEach((l) => {
      const n = this.nodes.find((x) => x.label === l);
      if (n) this.thoughtFrom(n.id, intensity || 1);
    });
  }

  fit(): void {
    let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    this.nodes.forEach((n) => { minX = Math.min(minX, n.x); minY = Math.min(minY, n.y); maxX = Math.max(maxX, n.x); maxY = Math.max(maxY, n.y); });
    const w = maxX - minX + 160, h = maxY - minY + 160;
    // Recenter the graph centroid on the current anchor. flyTo (eased) instead
    // of snapping cam.x/y so wheel-zoom drift glides back smoothly. Without this
    // the only way to undo a drifted wheel-zoom was an undiscoverable gesture.
    this.flyTo((minX + maxX) / 2, (minY + maxY) / 2);
    // A bare fit() (double-click recenter) means "show me everything, centered" —
    // so if a transient left-anchor lingers while undocked, snap the target back.
    if (this.interactive) this.anchorXT = 0.5;
    this.cam.tScale = Math.min(this.W / w, this.H / h, 1.4);
  }

  tick(strong?: number): void {
    const ns = this.nodes, k = strong || 1;
    // repulsion (cutoff)
    for (let i = 0; i < ns.length; i++) {
      const a = ns[i];
      for (let j = i + 1; j < ns.length; j++) {
        const b = ns[j];
        const dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 > 130000) continue;
        if (d2 < 1) d2 = 1;
        const d = Math.sqrt(d2);
        const f = 2600 / d2;
        const fx = (dx / d) * f, fy = (dy / d) * f;
        a.vx += fx / a.mass; a.vy += fy / a.mass;
        b.vx -= fx / b.mass; b.vy -= fy / b.mass;
      }
    }
    // springs
    for (const [ai, bi, w] of this.edges) {
      const a = ns[ai], b = ns[bi];
      const rest = (a.type === 'self' || b.type === 'self') ? 150 : (a.type === 'topic' || b.type === 'topic') ? 78 : 64;
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.hypot(dx, dy) || 1;
      const f = (d - rest) * 0.014 * w;
      const fx = (dx / d) * f, fy = (dy / d) * f;
      a.vx += fx / a.mass; a.vy += fy / a.mass;
      b.vx -= fx / b.mass; b.vy -= fy / b.mass;
    }
    // gravity to center + integrate
    for (const n of ns) {
      n.vx += -n.x * 0.0016; n.vy += -n.y * 0.0016;
      if (n.type === 'self') { n.x = 0; n.y = 0; n.vx = 0; n.vy = 0; continue; }
      if (n.id === this.dragId) continue;
      n.vx *= 0.85; n.vy *= 0.85;
      const sp = Math.hypot(n.vx, n.vy);
      if (sp > 12) { n.vx = (n.vx / sp) * 12; n.vy = (n.vy / sp) * 12; }
      n.x += n.vx * k; n.y += n.vy * k;
    }
  }

  hitTest(sx: number, sy: number): GraphNode | null {
    let best: GraphNode | null = null, bd = 1e9;
    for (const n of this.nodes) {
      if (this.filter && n.type !== 'self' && !this.filter.has(n.type)) continue;
      const p = this.w2s(n.x, n.y);
      const rr = Math.max(10, n.r * this.cam.scale + 6);
      const d = Math.hypot(p.x - sx, p.y - sy);
      if (d < rr && d < bd) { bd = d; best = n; }
    }
    return best;
  }

  focusSet(): Set<number> | null {
    const id = this.hoverId != null ? this.hoverId : this.selectId;
    if (id == null) return null;
    const s = new Set([id]);
    this.adj[id].forEach((j) => s.add(j));
    return s;
  }

  onMove = (e: ScreenPoint): void => {
    if (!this.interactive) return;
    const r = this.canvas.getBoundingClientRect();
    const sx = e.clientX - r.left, sy = e.clientY - r.top;
    if (this.mouse.down) this.mouse.moved = true;
    if (this.dragId != null) {
      const w = this.s2w(sx, sy);
      const n = this.nodes[this.dragId];
      n.x = w.x; n.y = w.y; n.vx = n.vy = 0;
      this.mouse.x = sx; this.mouse.y = sy;
      return;
    }
    if (this.panning) {
      this.cam.x -= (sx - this.mouse.x) / this.cam.scale;
      this.cam.y -= (sy - this.mouse.y) / this.cam.scale;
      this.mouse.x = sx; this.mouse.y = sy;
      return;
    }
    this.mouse.x = sx; this.mouse.y = sy;
    const hit = this.hitTest(sx, sy);
    const id = hit ? hit.id : null;
    this.canvas.style.cursor = hit ? 'pointer' : 'grab';
    if (id !== this.hoverId) {
      this.hoverId = id;
      if (this.selectId == null) this.on.hover(hit || null);
    }
  };

  onDown = (e: ScreenPoint): void => {
    if (!this.interactive) return;
    const r = this.canvas.getBoundingClientRect();
    const sx = e.clientX - r.left, sy = e.clientY - r.top;
    this.mouse.down = true; this.mouse.moved = false; this.mouse.x = sx; this.mouse.y = sy;
    const hit = this.hitTest(sx, sy);
    if (hit) { this.dragId = hit.id; this.canvas.style.cursor = 'grabbing'; }
    else { this.panning = true; this.canvas.style.cursor = 'grabbing'; }
  };

  onUp = (): void => {
    if (this.dragId != null && !this.mouse.moved) this.select(this.dragId);
    else if (this.panning && !this.mouse.moved) this.select(null);
    this.dragId = null; this.panning = false; this.mouse.down = false;
    this.canvas.style.cursor = 'grab';
  };

  // Double-click anywhere recenters the graph (the universal node-canvas
  // gesture); without it a pan into empty space leaves no way back.
  onDblClick = (): void => {
    if (!this.interactive) return;
    this.fit();
  };

  onWheel = (e: WheelEvent): void => {
    if (!this.interactive) return;
    e.preventDefault();
    const r = this.canvas.getBoundingClientRect();
    const sx = e.clientX - r.left, sy = e.clientY - r.top;
    const before = this.s2w(sx, sy);
    const f = Math.exp(-e.deltaY * 0.0014);
    this.cam.scale = Math.max(0.35, Math.min(3.2, this.cam.scale * f));
    this.cam.tScale = this.cam.scale;
    const after = this.s2w(sx, sy);
    this.cam.x += before.x - after.x;
    this.cam.y += before.y - after.y;
  };

  select(id: number | null): void {
    this.selectId = id;
    const n = id == null ? null : this.nodes[id];
    this.on.select(n);
    if (n) { this.thoughtFrom(id!, 0.9); this.flyTo(n.x, n.y); }
  }

  flyTo(x: number, y: number): void {
    this._fly = { x, y, t: 0 };
  }

  setAccent(hex: string): void { this.accent = hex; }
  setMotion(on: boolean): void { this.motion = on; }

  search(q: string): number {
    q = (q || '').trim().toLowerCase();
    if (!q) { this.searchMatch = null; return 0; }
    const m = this.nodes.filter(
      (n) => n.label.toLowerCase().includes(q) || String(tr(n.label)).toLowerCase().includes(q),
    );
    this.searchMatch = new Set(m.map((n) => n.id));
    if (m.length) {
      const cx = m.reduce((s, n) => s + n.x, 0) / m.length;
      const cy = m.reduce((s, n) => s + n.y, 0) / m.length;
      this.flyTo(cx, cy);
      m.forEach((n) => { n.heat = Math.max(n.heat, 0.8); });
    }
    return m.length;
  }

  thoughtFrom(id: number, intensity: number): void {
    const seed = this.nodes[id];
    if (!seed) return;
    seed.heat = Math.max(seed.heat, intensity);
    this.adj[id].forEach((j) => {
      this.nodes[j].heat = Math.max(this.nodes[j].heat, intensity * 0.6);
      this.pulses.push({ a: id, b: j, t: 0, sp: 0.018 + Math.random() * 0.02 });
      this.adj[j].forEach((kk) => {
        if (kk !== id) this.nodes[kk].heat = Math.max(this.nodes[kk].heat, intensity * 0.3);
      });
    });
  }

  autoThought(): void {
    const cand = this.nodes.filter((n) => n.type === 'topic' || (n.type === 'skill' && this.degree[n.id] > 2));
    const seed = cand[Math.floor(Math.random() * cand.length)];
    this.thoughtFrom(seed.id, 1);
    this.on.thought(seed);
  }

  grow(): void {
    if (this.growIdx >= GROWTH.length) return;
    const g: GrowthSpec = GROWTH[this.growIdx++];
    const anchor = this.nodes.find((x) => x.label === g.near) || this.self;
    const node: GraphNode = {
      id: this.nodes.length, label: g.label, type: g.type, topic: g.near,
      x: anchor.x + (Math.random() - 0.5) * 30, y: anchor.y + (Math.random() - 0.5) * 30,
      vx: 0, vy: 0, heat: 1, spawn: 0, mass: 1, r: 4, born: this.MAXDAY, tvis: 1,
    };
    this.nodes.push(node); this.adj.push([]); this.degree.push(0);
    this.edges.push([anchor.id, node.id, 0.6, this.MAXDAY]);
    this.adj[anchor.id].push(node.id); this.adj[node.id].push(anchor.id);
    this.degree[anchor.id]++; this.degree[node.id]++;
    this.on.grow(node);
  }

  // run → memory closed loop: a finished task deposits a new node, wired to what it used
  learn(spec: LearnSpec): GraphNode {
    const existing = this.nodes.find((n) => n.label === spec.label);
    if (existing) { this.thoughtFrom(existing.id, 1.2); return existing; }
    const anchors = (spec.links || []).map((l) => this.nodes.find((n) => n.label === l)).filter(Boolean) as GraphNode[];
    const base = anchors[0] || this.self;
    const node: GraphNode = {
      id: this.nodes.length, label: spec.label, type: spec.type || 'memory', topic: base.topic,
      x: base.x + (Math.random() - 0.5) * 26, y: base.y + (Math.random() - 0.5) * 26,
      vx: 0, vy: 0, heat: 1.4, spawn: 0, mass: 1, r: 4.5, born: this.MAXDAY, tvis: 1,
    };
    this.nodes.push(node); this.adj.push([]); this.degree.push(0);
    anchors.forEach((a) => {
      this.edges.push([a.id, node.id, 0.6, this.MAXDAY]);
      this.adj[a.id].push(node.id); this.adj[node.id].push(a.id);
      this.degree[a.id]++; this.degree[node.id]++;
      a.heat = Math.max(a.heat, 0.7);
      this.pulses.push({ a: a.id, b: node.id, t: 0, sp: 0.02 });
    });
    this.on.grow(node);
    return node;
  }

  frame = (now: number): void => {
    this.raf = requestAnimationFrame(this.frame);
    // camera easing
    this.cam.scale += (this.cam.tScale - this.cam.scale) * 0.12;
    this.anchorX += (this.anchorXT - this.anchorX) * 0.1;
    if (this._fly) {
      this._fly.t += 0.06;
      this.cam.x += (this._fly.x - this.cam.x) * 0.08;
      this.cam.y += (this._fly.y - this.cam.y) * 0.08;
      if (this._fly.t > 1) this._fly = null;
    }
    if (this.motion) this.tick(1);
    // heat decay + timeline fade
    for (const n of this.nodes) {
      n.heat *= this.motion ? 0.975 : 1;
      if (n.spawn < 1) n.spawn = Math.min(1, n.spawn + 0.04);
      const tgt = n.born <= this.day ? 1 : 0;
      n.tvis += (tgt - n.tvis) * 0.16;
    }
    // stage(临时蜂群层)节点的生长 + 发热衰减
    for (const sn of this.stage.nodes) {
      if (sn.spawn < 1) sn.spawn = Math.min(1, sn.spawn + 0.05);
      sn.heat *= this.motion ? 0.97 : 1;
    }
    if (this.motion && !this.scrub && now - this.lastThought > 3200) { this.lastThought = now; this.autoThought(); }
    if (this.motion && !this.scrub && now - this.lastGrow > 13000) { this.lastGrow = now; this.grow(); }
    this.draw(now);
  };

  draw(now: number): void {
    const ctx = this.ctx, dpr = this.dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, this.W, this.H);
    const focus = this.focusSet();
    const sm = this.searchMatch;
    const breathe = this.motion ? 1 + Math.sin(now * 0.0012) * 0.04 : 1;

    // dust motes
    ctx.save();
    for (const d of this.dust) {
      const p = this.w2s(d.x, d.y);
      ctx.globalAlpha = 0.06 * d.z;
      ctx.fillStyle = '#9fb4d0';
      ctx.beginPath();
      ctx.arc(p.x, p.y, d.z * 1.3, 0, 7);
      ctx.fill();
    }
    ctx.restore();

    const vis = (n: GraphNode): boolean =>
      (!this.filter || n.type === 'self' || this.filter.has(n.type)) && n.tvis > 0.02;
    const dim = (n: GraphNode): number => {
      if (sm) return sm.has(n.id) ? 1 : 0.12;
      if (focus) return focus.has(n.id) ? 1 : 0.16;
      return 1;
    };

    // edges
    ctx.lineCap = 'round';
    for (const [ai, bi] of this.edges) {
      const a = this.nodes[ai], b = this.nodes[bi];
      if (!vis(a) || !vis(b)) continue;
      const pa = this.w2s(a.x, a.y), pb = this.w2s(b.x, b.y);
      const h = Math.min(a.heat, b.heat);
      const df = Math.min(dim(a), dim(b));
      const alpha = (0.07 + h * 0.5) * df;
      if (alpha < 0.012) continue;
      ctx.strokeStyle = h > 0.15 ? this._mix(this.accent, '#ffffff', h * 0.4) : '#7f93b3';
      ctx.globalAlpha = alpha;
      ctx.lineWidth = h > 0.2 ? 1.6 : 0.8;
      ctx.beginPath();
      ctx.moveTo(pa.x, pa.y);
      ctx.lineTo(pb.x, pb.y);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    // pulses
    for (let i = this.pulses.length - 1; i >= 0; i--) {
      const p = this.pulses[i];
      p.t += p.sp * (this.motion ? 1 : 0);
      if (p.t >= 1) { this.pulses.splice(i, 1); continue; }
      const a = this.nodes[p.a], b = this.nodes[p.b];
      const px = a.x + (b.x - a.x) * p.t, py = a.y + (b.y - a.y) * p.t;
      const s = this.w2s(px, py);
      ctx.save();
      ctx.globalAlpha = (1 - p.t) * 0.9;
      ctx.shadowColor = this.accent;
      ctx.shadowBlur = 12;
      ctx.fillStyle = '#fff';
      ctx.beginPath();
      ctx.arc(s.x, s.y, 2.4, 0, 7);
      ctx.fill();
      ctx.restore();
    }

    // nodes
    for (const n of this.nodes) {
      if (!vis(n)) continue;
      const p = this.w2s(n.x, n.y);
      const cat = CATS[n.type];
      const col = n.type === 'self' ? this.accent : cat.color;
      const glow = n.type === 'self' ? this.accent : cat.glow;
      const df = dim(n) * n.tvis;
      const r = n.r * n.spawn * (0.5 + 0.5 * n.tvis) * (n.type === 'self' ? breathe : 1) * this.cam.scale;
      const heatBoost = 1 + n.heat * 1.2;
      // freshly-born ring (bloom)
      if (n.tvis < 0.96 && n.born <= this.day) {
        ctx.save();
        ctx.globalAlpha = (1 - n.tvis) * 0.8;
        ctx.strokeStyle = glow;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r + 5 + (1 - n.tvis) * 14, 0, 7);
        ctx.stroke();
        ctx.restore();
      }
      ctx.save();
      // glow
      ctx.globalAlpha = (0.5 + n.heat * 0.5) * df;
      ctx.shadowColor = glow;
      ctx.shadowBlur = (10 + n.heat * 26 + (n.type === 'self' ? 22 : n.type === 'topic' ? 8 : 4)) * df;
      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.arc(p.x, p.y, Math.max(1, r * 0.92), 0, 7);
      ctx.fill();
      ctx.restore();
      // core
      ctx.save();
      ctx.globalAlpha = df;
      ctx.fillStyle = n.heat > 0.3 ? this._mix(col, '#ffffff', n.heat * 0.6) : col;
      const coreR = r * 0.55 * heatBoost > r ? r : r * 0.55 * heatBoost;
      ctx.beginPath();
      ctx.arc(p.x, p.y, Math.max(0.8, coreR), 0, 7);
      ctx.fill();
      if (n.type === 'self') {
        ctx.fillStyle = '#fff7ec';
        ctx.beginPath();
        ctx.arc(p.x, p.y, r * 0.34, 0, 7);
        ctx.fill();
      }
      ctx.restore();
      // ring on hover/select
      if (n.id === this.hoverId || n.id === this.selectId) {
        ctx.save();
        ctx.globalAlpha = 0.9;
        ctx.strokeStyle = col;
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r + 6, 0, 7);
        ctx.stroke();
        ctx.restore();
      }
    }

    // labels — drawn in priority order; lower-priority labels that would
    // overlap an already-placed label are skipped (still appear on hover).
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    type LabelCand = { n: GraphNode; pri: number };
    const cands: LabelCand[] = [];
    for (const n of this.nodes) {
      if (!vis(n)) continue;
      const showAlways = n.type === 'self' || n.type === 'topic';
      const focused = focus && focus.has(n.id);
      const matched = sm && sm.has(n.id);
      const hovd = n.id === this.hoverId || n.id === this.selectId;
      if (!showAlways && !focused && !matched && !hovd) continue;
      // priority: self(4) > hovered/selected(3) > matched/focused(2) > topic/other(1)
      const pri = n.type === 'self' ? 4 : hovd ? 3 : (matched || focused) ? 2 : 1;
      cands.push({ n, pri });
    }
    // higher priority first; ties keep node order (stable)
    cands.sort((a, b) => b.pri - a.pri);

    const placed: { x0: number; y0: number; x1: number; y1: number }[] = [];
    const overlaps = (b: { x0: number; y0: number; x1: number; y1: number }) =>
      placed.some((p) => b.x0 < p.x1 && b.x1 > p.x0 && b.y0 < p.y1 && b.y1 > p.y0);

    for (const { n, pri } of cands) {
      const p = this.w2s(n.x, n.y);
      const r = n.r * this.cam.scale;
      const showAlways = n.type === 'self' || n.type === 'topic';
      const focused = focus && focus.has(n.id);
      const matched = sm && sm.has(n.id);
      const hovd = n.id === this.hoverId || n.id === this.selectId;
      let a = hovd ? 1 : focused || matched ? 0.92 : n.type === 'self' ? 0.95 : 0.5;
      if (focus && !focused && showAlways) a = 0.18;
      const fs = n.type === 'self' ? 15 : n.type === 'topic' ? 12 : 11;
      ctx.font = `${n.type === 'self' ? '700' : '500'} ${fs}px 'IBM Plex Sans', sans-serif`;
      const ty = p.y + r + fs * 0.9 + 3;
      const label = tr(n.label);

      // bounding box for collision (measured width, label height ≈ fs)
      const w = ctx.measureText(label).width;
      const pad = 2;
      const box = { x0: p.x - w / 2 - pad, y0: ty - fs / 2 - pad, x1: p.x + w / 2 + pad, y1: ty + fs / 2 + pad };

      // self and the actively hovered/selected label always win and are always drawn
      const mustDraw = pri >= 3;
      if (!mustDraw && overlaps(box)) continue;
      placed.push(box);

      ctx.globalAlpha = a * 0.55;
      ctx.fillStyle = '#05070c';
      ctx.fillText(label, p.x + 0.6, ty + 0.6);
      ctx.globalAlpha = a;
      ctx.fillStyle = hovd || matched ? '#ffffff' : showAlways && !focus ? '#d8c6a8' : '#c8d4e6';
      ctx.fillText(label, p.x, ty);
    }
    ctx.globalAlpha = 1;

    this.drawStage(now);
  }

  // 蜂群临时叠加层:契约/worker 节点围绕中心环形铺开,实时长出+脉冲+按状态着色。
  // 与永久 nodes 隔离,只在蜂群运行时存在;state: active=accent / conflict=橙 / resolved=绿。
  private drawStage(now: number): void {
    const stage = this.stage;
    if (stage.nodes.length === 0) return;
    const ctx = this.ctx;
    const center = this.w2s(this.self.x, this.self.y);
    const ring = 120 * this.cam.scale; // worker 环半径(屏幕像素)
    const breathe = this.motion ? 1 + Math.sin(now * 0.004) * 0.12 : 1;
    const stateColor = (s: string) => (s === 'conflict' ? '#ff7a4d' : s === 'resolved' ? '#45e0a0' : this.accent);

    const pos = (n: { radius: number; angle: number }) => ({
      x: center.x + Math.cos(n.angle) * ring * n.radius,
      y: center.y + Math.sin(n.angle) * ring * n.radius,
    });

    // links: contract → worker(虚线脉冲感)
    ctx.save();
    ctx.lineWidth = 1.1;
    for (const l of stage.links) {
      const from = stage.nodes.find((n) => n.id === l.from);
      const to = stage.nodes.find((n) => n.id === l.to);
      if (!from || !to) continue;
      const a = pos(from), b = pos(to);
      ctx.globalAlpha = 0.35 * to.spawn;
      ctx.strokeStyle = stateColor(to.state);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }
    ctx.restore();

    // nodes
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (const n of stage.nodes) {
      const p = pos(n);
      const col = stateColor(n.state);
      const baseR = (n.kind === 'contract' ? 9 : 6) * this.cam.scale;
      const r = baseR * n.spawn * (n.state === 'conflict' ? breathe : 1);
      // born ring bloom
      if (n.spawn < 0.95) {
        ctx.save();
        ctx.globalAlpha = (1 - n.spawn) * 0.7;
        ctx.strokeStyle = col;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r + 6 + (1 - n.spawn) * 12, 0, 7);
        ctx.stroke();
        ctx.restore();
      }
      ctx.save();
      ctx.globalAlpha = 0.5 + n.heat * 0.5;
      ctx.shadowColor = col;
      ctx.shadowBlur = (12 + n.heat * 24) * this.cam.scale;
      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.arc(p.x, p.y, Math.max(1, r), 0, 7);
      ctx.fill();
      ctx.restore();
      // label
      ctx.globalAlpha = 0.9 * n.spawn;
      ctx.font = `${n.kind === 'contract' ? '700' : '500'} ${n.kind === 'contract' ? 12 : 10.5}px 'IBM Plex Sans', sans-serif`;
      ctx.fillStyle = '#05070c';
      const label = n.label.length > 18 ? n.label.slice(0, 17) + '…' : n.label;
      ctx.fillText(label, p.x + 0.6, p.y + r + 11 + 0.6);
      ctx.fillStyle = '#e8eef8';
      ctx.fillText(label, p.x, p.y + r + 11);
    }
    ctx.globalAlpha = 1;
  }

  private _mix(a: string, b: string, t: number): string {
    const pa = this._rgb(a), pb = this._rgb(b);
    const r = Math.round(pa[0] + (pb[0] - pa[0]) * t);
    const g = Math.round(pa[1] + (pb[1] - pa[1]) * t);
    const bl = Math.round(pa[2] + (pb[2] - pa[2]) * t);
    return `rgb(${r},${g},${bl})`;
  }
  private _rgb(h: string): [number, number, number] {
    if (h[0] === '#') {
      const n = parseInt(h.slice(1), 16);
      return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    }
    return [255, 255, 255];
  }
}

export { META };
