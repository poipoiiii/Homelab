// 程序化配乐与音效：120 BPM，卡点与转场/条目入场对齐。
// 输出 48kHz 16-bit 立体声 WAV；不依赖任何音频素材，避免版权问题。
import fs from 'node:fs/promises';
import { mulberry32 } from './theme.js';

export const BPM = 120;
export const BEAT = 60 / BPM; // 0.5s

const SAMPLE_RATE = 48000;

export async function renderAudio(plan, outPath) {
  const total = plan.totalDuration;
  const frames = Math.round(total * SAMPLE_RATE);
  const left = new Float32Array(frames + 1);
  const right = new Float32Array(frames + 1);
  const rand = mulberry32(20261102);

  const noise = () => rand() * 2 - 1;

  function write(index, value, pan = 0) {
    if (index < 0 || index >= frames) return;
    const l = pan >= 0 ? 1 - pan : 1;
    const r = pan <= 0 ? 1 + pan : 1;
    left[index] += value * l;
    right[index] += value * r;
  }

  function synth(startTime, duration, fn, pan = 0) {
    const start = Math.round(startTime * SAMPLE_RATE);
    const count = Math.round(duration * SAMPLE_RATE);
    for (let i = 0; i < count; i += 1) {
      const t = i / SAMPLE_RATE;
      const value = fn(t, i);
      if (value) write(start + i, value, pan);
    }
  }

  function kick(time, gain = 0.62) {
    let phase = 0;
    synth(
      time,
      0.42,
      (t) => {
        const f = 46 + 96 * Math.exp(-t * 26);
        phase += (2 * Math.PI * f) / SAMPLE_RATE;
        return Math.sin(phase) * Math.exp(-t * 8.2) * gain;
      },
      0,
    );
  }

  function snare(time, gain = 0.16) {
    let low = 0;
    synth(
      time,
      0.2,
      (t) => {
        const n = noise();
        low += 0.4 * (n - low);
        return (low * 0.8 + Math.sin(2 * Math.PI * 185 * t) * 0.25) * Math.exp(-t * 22) * gain;
      },
      0.05,
    );
  }

  function hat(time, gain = 0.06) {
    let previous = 0;
    synth(
      time,
      0.05,
      (t) => {
        const n = noise();
        const high = n - previous;
        previous = n;
        return high * Math.exp(-t * 70) * gain;
      },
      0.28,
    );
  }

  function bass(time, freq, gain = 0.14) {
    let p1 = 0;
    let p2 = 0;
    synth(time, 0.44, (t) => {
      p1 += (2 * Math.PI * freq) / SAMPLE_RATE;
      p2 += (2 * Math.PI * freq * 2) / SAMPLE_RATE;
      const env = Math.min(1, t / 0.01) * Math.exp(-t * 3.4);
      return (Math.sin(p1) * 0.82 + Math.sin(p2) * 0.18) * env * gain;
    });
  }

  function pad(time, freq, duration, gain = 0.035) {
    const start = Math.round(time * SAMPLE_RATE);
    const count = Math.round(duration * SAMPLE_RATE);
    let pL = 0;
    let pR = 0;
    let hL = 0;
    let hR = 0;
    for (let i = 0; i < count; i += 1) {
      const t = i / SAMPLE_RATE;
      const env = Math.min(1, t / 0.7) * Math.min(1, Math.max(0, (duration - t) / 0.9));
      pL += (2 * Math.PI * freq * 0.997) / SAMPLE_RATE;
      pR += (2 * Math.PI * freq * 1.003) / SAMPLE_RATE;
      hL += (2 * Math.PI * freq * 2) / SAMPLE_RATE;
      hR += (2 * Math.PI * freq * 2.004) / SAMPLE_RATE;
      const vl = (Math.sin(pL) * 0.72 + Math.sin(hL) * 0.28) * env * gain;
      const vr = (Math.sin(pR) * 0.72 + Math.sin(hR) * 0.28) * env * gain;
      write(start + i, vl, -0.15);
      write(start + i, vr, 0.15);
    }
  }

  function whoosh(time, duration = 0.55, gain = 0.2) {
    let low = 0;
    synth(time, duration, (t) => {
      const progress = Math.min(1, t / duration);
      const cut = 0.015 + 0.28 * progress * progress;
      const n = noise();
      low += cut * (n - low);
      return low * Math.pow(Math.sin(Math.PI * progress), 1.4) * gain;
    });
  }

  function impact(time, gain = 0.5) {
    let phase = 0;
    synth(time, 1.1, (t) => {
      const f = 34 + 48 * Math.exp(-t * 9);
      phase += (2 * Math.PI * f) / SAMPLE_RATE;
      const body = Math.sin(phase) * Math.exp(-t * 3.1);
      const air = noise() * Math.exp(-t * 17) * 0.32;
      return (body + air) * gain;
    });
  }

  function tick(time, gain = 0.09) {
    synth(
      time,
      0.06,
      (t) => (Math.sin(2 * Math.PI * 2100 * t) * 0.6 + noise() * 0.4) * Math.exp(-t * 55) * gain,
      0.18,
    );
  }

  function riser(time, duration = 2, gain = 0.2) {
    let low = 0;
    let phase = 0;
    synth(time, duration, (t) => {
      const progress = Math.min(1, t / duration);
      const n = noise();
      low += (0.008 + 0.36 * progress * progress) * (n - low);
      phase += (2 * Math.PI * (110 + 620 * progress * progress)) / SAMPLE_RATE;
      const env = progress * progress;
      return (low * 0.78 + Math.sin(phase) * 0.22) * env * gain;
    });
  }

  // 鼓组与低音：120 BPM，按场景类型做动态（人像满拍、列表半拍、引用留白）
  const ranges = [];
  let rangeCursor = 0;
  plan.scenes.forEach((scene) => {
    ranges.push({ start: rangeCursor, end: rangeCursor + scene.duration, kind: scene.kind });
    rangeCursor += scene.duration;
  });
  const kindAt = (time) => ranges.find((range) => time >= range.start && time < range.end)?.kind || 'list';

  const totalBeats = Math.ceil(total / BEAT);
  const chords = [
    [146.83, 174.61, 220.0], // Dm
    [116.54, 146.83, 174.61], // Bb
    [98.0, 116.54, 146.83], // Gm
    [110.0, 138.59, 164.81], // A
  ];
  const bassRoots = [73.42, 58.27, 49.0, 55.0];

  for (let beat = 0; beat < totalBeats; beat += 1) {
    const time = beat * BEAT;
    if (time > total) break;
    const kind = kindAt(time);
    if (kind === 'quote') continue;

    const full = kind === 'portrait' || kind === 'cover' || kind === 'end' || kind === 'stat';
    if (full || beat % 2 === 0) kick(time, beat % 4 === 0 ? 0.68 : 0.5);
    if (full) {
      if (beat % 4 === 2) snare(time, 0.17);
      hat(time + BEAT / 2, 0.07);
      if (beat % 2 === 1) hat(time, 0.03);
      bass(time, bassRoots[Math.floor(beat / 8) % 4], 0.13);
    } else {
      if (beat % 4 === 2) snare(time, 0.12);
      if (beat % 2 === 0) bass(time, bassRoots[Math.floor(beat / 8) % 4], 0.09);
      hat(time + BEAT / 2, 0.035);
    }
  }

  for (let block = 0; block < Math.ceil(total / (BEAT * 8)); block += 1) {
    const start = block * BEAT * 8;
    const chord = chords[block % chords.length];
    chord.forEach((freq) => pad(start, freq, Math.min(4.4, total - start), 0.032));
  }

  // 场景事件
  let cursor = 0;
  let endStart = null;
  plan.scenes.forEach((scene, index) => {
    const start = cursor;
    cursor += scene.duration;
    if (scene.kind === 'end') endStart = start;

    if (index > 0) {
      whoosh(Math.max(0, start - 0.34), 0.5, 0.18);
      impact(start, scene.kind === 'portrait' ? 0.5 : 0.34);
    }
    if (scene.kind === 'portrait') {
      tick(start + 0.12, 0.07);
      impact(start + 0.5, 0.18);
    }
    if (scene.kind === 'list') {
      (scene.data.items || []).forEach((_, itemIndex) => {
        tick(start + 0.16 + itemIndex * 0.14, 0.085);
      });
    }
  });

  if (endStart !== null) {
    riser(Math.max(0, endStart - 2), 2, 0.18);
    impact(endStart, 0.55);
  }

  // 结尾淡出
  const fade = Math.min(1.2, total * 0.3);
  const fadeStart = total - fade;
  for (let i = Math.round(fadeStart * SAMPLE_RATE); i < frames; i += 1) {
    const gain = Math.max(0, (total - i / SAMPLE_RATE) / fade);
    left[i] *= gain;
    right[i] *= gain;
  }

  // 归一化，留一点余量
  let peak = 0;
  for (let i = 0; i < frames; i += 1) {
    peak = Math.max(peak, Math.abs(left[i]), Math.abs(right[i]));
  }
  const scale = peak > 0.0001 ? 0.86 / peak : 1;
  const pcm = Buffer.alloc(44 + frames * 4);
  pcm.write('RIFF', 0);
  pcm.writeUInt32LE(36 + frames * 4, 4);
  pcm.write('WAVE', 8);
  pcm.write('fmt ', 12);
  pcm.writeUInt32LE(16, 16);
  pcm.writeUInt16LE(1, 20);
  pcm.writeUInt16LE(2, 22);
  pcm.writeUInt32LE(SAMPLE_RATE, 24);
  pcm.writeUInt32LE(SAMPLE_RATE * 4, 28);
  pcm.writeUInt16LE(4, 32);
  pcm.writeUInt16LE(16, 34);
  pcm.write('data', 36);
  pcm.writeUInt32LE(frames * 4, 40);
  for (let i = 0; i < frames; i += 1) {
    // 软限幅：抬平均响度，同时压住鼓点峰值
    const l = Math.tanh(left[i] * scale * 1.35);
    const r = Math.tanh(right[i] * scale * 1.35);
    pcm.writeInt16LE(Math.round(l * 32767), 44 + i * 4);
    pcm.writeInt16LE(Math.round(r * 32767), 46 + i * 4);
  }
  await fs.writeFile(outPath, pcm);
  return { peak, frames, sampleRate: SAMPLE_RATE, bytes: pcm.length };
}
