// Rasterises the Parlo app icon to PNG without any image dependencies:
// signed-distance shapes, 4×4 supersampling, and a hand-written PNG encoder.
//   node scripts/make-icons.mjs
import { writeFileSync } from "node:fs";
import { deflateSync } from "node:zlib";

const crcTable = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
const crc32 = (buf) => {
  let c = 0xffffffff;
  for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
};
function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
function png(size, pixel) {
  const raw = Buffer.alloc(size * (size * 4 + 1));
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0;
    for (let x = 0; x < size; x++) {
      const [r, g, b, a] = pixel(x, y);
      const o = y * (size * 4 + 1) + 1 + x * 4;
      raw[o] = r;
      raw[o + 1] = g;
      raw[o + 2] = b;
      raw[o + 3] = a;
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const roundRect = (px, py, x, y, w, h, r) => {
  const qx = Math.abs(px - (x + w / 2)) - (w / 2 - r);
  const qy = Math.abs(py - (y + h / 2)) - (h / 2 - r);
  return Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - r;
};
const circle = (px, py, cx, cy, r) => Math.hypot(px - cx, py - cy) - r;
const tri = (px, py, a, b, c) => {
  const s = (p1, p2, p3) => (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1]);
  const p = [px, py];
  const d1 = s(p, a, b), d2 = s(p, b, c), d3 = s(p, c, a);
  return (d1 < 0 || d2 < 0 || d3 < 0) && (d1 > 0 || d2 > 0 || d3 > 0) ? 1 : -1;
};
const mix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
const VIOLET = [109, 93, 252];
const PEACH = [255, 138, 92];

// Icon in a 48-unit design space; `pad` shrinks it for the maskable safe zone.
function render(size, { pad = 0, full = false } = {}) {
  const SS = 4;
  return png(size, (x, y) => {
    let acc = [0, 0, 0, 0];
    for (let sy = 0; sy < SS; sy++)
      for (let sx = 0; sx < SS; sx++) {
        const u = ((x + (sx + 0.5) / SS) / size) * 48;
        const v = ((y + (sy + 0.5) / SS) / size) * 48;
        const k = 48 / (48 - pad * 2);
        const du = (u - 24) * k + 24;
        const dv = (v - 24) * k + 24;
        const t = Math.min(1, Math.max(0, (u + v) / 96));
        const bg = mix(VIOLET, PEACH, t);
        const inBg = full ? true : roundRect(u, v, 2, 2, 44, 44, 14) <= 0;
        if (!inBg) continue;
        let col = bg;
        const bubble = roundRect(du, dv, 15, 13, 18, 15, 3.5) <= 0 || tri(du, dv, [17.3, 26], [22.5, 28], [17.3, 32.6]) < 0;
        if (bubble) {
          col = [255, 255, 255];
          for (const cx of [20, 24, 28]) if (circle(du, dv, cx, 20.5, 1.7) <= 0) col = mix(VIOLET, PEACH, (cx - 20) / 16);
        }
        acc = [acc[0] + col[0], acc[1] + col[1], acc[2] + col[2], acc[3] + 255];
      }
    const n = SS * SS;
    const a = acc[3] / n;
    return a === 0 ? [0, 0, 0, 0] : [acc[0] / (n * (a / 255)), acc[1] / (n * (a / 255)), acc[2] / (n * (a / 255)), a].map(Math.round);
  });
}

const out = new URL("../public/icons/", import.meta.url);
writeFileSync(new URL("icon-192.png", out), render(192));
writeFileSync(new URL("icon-512.png", out), render(512));
writeFileSync(new URL("icon-maskable-512.png", out), render(512, { pad: 7, full: true }));
writeFileSync(new URL("apple-touch-icon.png", out), render(180, { pad: 3, full: true }));
console.log("icons written");
