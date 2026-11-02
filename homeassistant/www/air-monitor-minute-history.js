/* Minute history remains inside HA and uses the active HA login. */
const FIELDS = {
  co2_ppm: ["CO₂", "ppm", "#39836c"],
  hcho_ppb: ["甲醛", "ppb", "#a97536"],
  temperature_c: ["温度", "°C", "#b86159"],
  humidity_pct: ["湿度", "%", "#4c82a1"],
};
const requests = new Map();

export function minuteSegments(points, field) {
  const segments = [];
  let segment = [];
  for (const point of points) {
    const value = point[field];
    if (!value || ![value.mean, value.min, value.max, point.t].every(Number.isFinite)) {
      if (segment.length) segments.push(segment);
      segment = [];
      continue;
    }
    if (segment.length && point.t - segment[segment.length - 1].t > 90) {
      segments.push(segment);
      segment = [];
    }
    segment.push(point);
  }
  if (segment.length) segments.push(segment);
  return segments;
}

function localInput(date) {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export class AirMonitorMinuteHistory extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block}ha-card{padding:18px;color:var(--primary-text-color);overflow:hidden}
        h2{font-size:18px;font-weight:500;margin:0 0 12px}.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
        select,input,button{font:inherit;color:var(--primary-text-color);background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:8px;padding:8px;min-height:40px;box-sizing:border-box}
        button{cursor:pointer}.dates{display:none;flex-wrap:wrap;gap:8px;margin-top:8px}.dates label{font-size:12px;display:grid;gap:4px}
        .note,.status{font-size:12px;color:var(--secondary-text-color);line-height:1.6;margin-top:8px}
        svg{width:100%;height:auto;display:block;margin-top:14px;touch-action:pan-y}.tooltip{min-height:42px;font-size:13px;line-height:1.6}
        .legend{display:flex;gap:16px;font-size:12px;color:var(--secondary-text-color)}.legend span:before{content:"";display:inline-block;width:16px;height:3px;background:var(--air-color);margin-right:5px;vertical-align:middle}.legend span:last-child:before{height:9px;opacity:.22}
        @media(max-width:450px){ha-card{padding:14px}.dates input{max-width:100%}}
      </style>
      <ha-card><h2></h2><div class="controls"><select aria-label="记录时间范围"><option value="latest">最近一趟</option><option value="24">最近24小时</option><option value="168">最近7天</option><option value="720">最近30天</option><option value="custom">自选时间</option></select><button class="refresh">刷新</button></div>
      <div class="dates"><label>开始时间<input class="start" type="datetime-local"></label><label>结束时间<input class="end" type="datetime-local"></label><button class="apply">查看</button></div>
      <div class="status" role="status">等待加载…</div><div class="chart"></div><div class="tooltip" aria-live="polite"></div>
      <div class="legend"><span>分钟平均</span><span>分钟最低—最高</span></div>
      <div class="note">每分钟一条，长期保存。停车无数据不补零；间隔超过90秒断开曲线。“最近一趟”按超过5分钟无数据分段，最多显示24小时。</div></ha-card>`;
    this._select = this.shadowRoot.querySelector("select");
    this._status = this.shadowRoot.querySelector(".status");
    this._chart = this.shadowRoot.querySelector(".chart");
    this._tooltip = this.shadowRoot.querySelector(".tooltip");
    this._start = this.shadowRoot.querySelector(".start");
    this._end = this.shadowRoot.querySelector(".end");
    this._start.value = localInput(new Date(Date.now() - 86400000));
    this._end.value = localInput(new Date());
    this._select.addEventListener("change", () => {
      this.shadowRoot.querySelector(".dates").style.display = this._select.value === "custom" ? "flex" : "none";
      if (this._select.value !== "custom") this._load(true);
    });
    this.shadowRoot.querySelector(".refresh").addEventListener("click", () => this._load(true));
    this.shadowRoot.querySelector(".apply").addEventListener("click", () => this._load(true));
    this._generation = 0;
  }

  setConfig(config) {
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(config.device_id || "") || !FIELDS[config.metric]) {
      throw new Error("需要合法的 device_id 和 metric");
    }
    this._config = config;
    this.shadowRoot.querySelector("h2").textContent = config.title || `${FIELDS[config.metric][0]} · 分钟记录`;
    this.style.setProperty("--air-color", FIELDS[config.metric][2]);
  }

  set hass(hass) {
    this._hass = hass;
    if (this.isConnected && this._config && !this._loading && Date.now() - (this._lastLoad || 0) >= 60000) this._load();
  }

  connectedCallback() {
    if (this._hass && this._config) this._load();
    if (!this._timer) this._timer = setInterval(() => this._load(), 60000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    this._timer = null;
    this._generation++;
  }

  getCardSize() { return 6; }

  async _load(force = false) {
    if (!this._hass || !this._config || (this._loading && !force) || (!force && Date.now() - (this._lastLoad || 0) < 55000)) return;
    const generation = ++this._generation;
    this._loading = true;
    this._lastLoad = Date.now();
    this._status.textContent = "读取分钟记录…";
    try {
      const mode = this._select.value;
      const now = Math.floor(Date.now() / 60000) * 60 + 59;
      let query, range;
      if (mode === "latest") query = "latest=1";
      else {
        const end = mode === "custom" ? Date.parse(this._end.value) / 1000 : now;
        const start = mode === "custom" ? Date.parse(this._start.value) / 1000 : now - Number(mode) * 3600;
        if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || end - start > 31 * 86400) throw new Error("请选择不超过31天的有效时间范围");
        query = `start=${Math.floor(start)}&end=${Math.floor(end)}`;
        range = [start, end];
      }
      const path = `air_monitor/minutes/${encodeURIComponent(this._config.device_id)}?${query}`;
      const key = `${this._hass.user?.id || ""}:${path}`;
      let cached = requests.get(key);
      if (!cached || Date.now() - cached.at >= (force ? 1000 : 55000)) {
        if (requests.size >= 12) requests.delete(requests.keys().next().value);
        cached = { at: Date.now(), promise: this._hass.callApi("GET", path) };
        requests.set(key, cached);
      }
      const result = await cached.promise;
      if (generation !== this._generation || !this.isConnected) return;
      this._points = result.points;
      this._range = range;
      this._draw();
    } catch (error) {
      if (generation === this._generation) {
        this._chart.replaceChildren();
        this._tooltip.textContent = "";
        this._status.textContent = `读取失败：${error.message || error.body?.message || "请稍后重试"}`;
      }
    } finally {
      if (generation === this._generation) this._loading = false;
    }
  }

  _draw() {
    const field = this._config.metric, unit = FIELDS[field][1], color = FIELDS[field][2];
    const segments = minuteSegments(this._points, field);
    const valid = segments.flat();
    this._tooltip.textContent = "";
    if (!valid.length) {
      this._chart.replaceChildren();
      this._status.textContent = "这段时间没有有效测量。车辆断电或传感器未就绪时不会生成浓度点。";
      return;
    }
    const first = valid[0].t, last = valid[valid.length - 1].t;
    const start = this._range?.[0] ?? first - 30, end = this._range?.[1] ?? Math.max(last + 30, first + 30);
    let low = Math.min(...valid.map(p => p[field].min)), high = Math.max(...valid.map(p => p[field].max));
    const padding = Math.max((high - low) * .12, field === "co2_ppm" ? 10 : 1);
    low -= padding; high += padding;
    const W = 720, H = 250, left = 60, right = 16, top = 16, bottom = 40;
    const x = t => left + (t - start) / Math.max(1, end - start) * (W - left - right);
    const y = v => top + (high - v) / (high - low) * (H - top - bottom);
    let drawing = "";
    for (let i = 0; i <= 4; i++) {
      const v = low + (high - low) * i / 4, yy = y(v);
      drawing += `<line x1="${left}" x2="${W-right}" y1="${yy}" y2="${yy}" stroke="var(--divider-color)"/><text x="${left-8}" y="${yy+4}" text-anchor="end" fill="var(--secondary-text-color)" font-size="11">${v.toFixed(field === "temperature_c" ? 1 : 0)}</text>`;
    }
    for (const segment of segments) {
      const upper = segment.map(p => `${x(p.t)},${y(p[field].max)}`).join(" ");
      const lower = [...segment].reverse().map(p => `${x(p.t)},${y(p[field].min)}`).join(" ");
      drawing += `<polygon points="${upper} ${lower}" fill="${color}" opacity=".18"/>`;
      drawing += `<polyline points="${segment.map(p => `${x(p.t)},${y(p[field].mean)}`).join(" ")}" fill="none" stroke="${color}" stroke-width="2"/>`;
      if (segment.length === 1) drawing += `<circle cx="${x(segment[0].t)}" cy="${y(segment[0][field].mean)}" r="3" fill="${color}"/>`;
    }
    for (let i = 0; i <= 3; i++) {
      const t = start + (end-start)*i/3;
      const label = new Date(t*1000).toLocaleString([], {month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false});
      drawing += `<text x="${x(t)}" y="${H-10}" text-anchor="${i===0?'start':i===3?'end':'middle'}" fill="var(--secondary-text-color)" font-size="11">${label}</text>`;
    }
    this._chart.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="分钟平均与最高最低范围">${drawing}</svg>`;
    const format = t => new Date(t*1000).toLocaleString([], {hour12:false});
    this._status.textContent = `${format(first)} — ${format(last)} · ${valid.length} 条分钟记录 · ${unit}`;
    const svg = this._chart.querySelector("svg");
    const show = event => {
      const rect = svg.getBoundingClientRect();
      const target = start + ((event.clientX-rect.left)/rect.width*W-left)/(W-left-right)*(end-start);
      let nearest = valid[0];
      for (const p of valid) if (Math.abs(p.t-target)<Math.abs(nearest.t-target)) nearest=p;
      const value = nearest[field];
      this._tooltip.textContent = `${format(nearest.t)}　平均 ${value.mean.toFixed(2)} ${unit}　最低 ${value.min.toFixed(2)}　最高 ${value.max.toFixed(2)}　有效样本 ${value.count}`;
    };
    svg.addEventListener("pointermove", show);
    svg.addEventListener("click", show);
  }
}

if (!customElements.get("air-monitor-minute-history")) customElements.define("air-monitor-minute-history", AirMonitorMinuteHistory);
window.customCards = window.customCards || [];
window.customCards.push({type:"air-monitor-minute-history",name:"空气仪分钟历史",description:"长期保留的一分钟行车记录"});
