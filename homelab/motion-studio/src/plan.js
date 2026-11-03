// 把请求规格排成时间线：每个场景的时长、数据、转场。
import { W, H, TRANSITIONS } from './theme.js';

export const PAGE_SIZE = 5;
const MAX_TOTAL_SECONDS = 240;

const RESOLUTIONS = {
  '1080p': { width: 1920, height: 1080 },
  '720p': { width: 1280, height: 720 },
};

function chunk(list, size) {
  const out = [];
  for (let i = 0; i < list.length; i += size) out.push(list.slice(i, i + size));
  return out;
}

function withTransitions(scenes, seed) {
  const offset = seed % TRANSITIONS.length;
  scenes.forEach((scene, i) => {
    if (i === 0) {
      scene.transition = { kind: 'cut', duration: 0 };
      return;
    }
    const kind = TRANSITIONS[(i + offset) % TRANSITIONS.length];
    scene.transition = { kind, duration: kind === 'cut' ? 0.001 : 0.5 };
  });
  return scenes;
}

function ledgerScenes(spec, date) {
  const sections = spec.sections;
  const pages = [];
  sections.forEach((section) => {
    chunk(section.items, PAGE_SIZE).forEach((items, pageIndex, all) => {
      pages.push({ section, items, pageIndex, pageCount: all.length });
    });
  });

  const stats = {
    sections: sections.length,
    items: sections.reduce((sum, s) => sum + s.items.length, 0),
    pages: pages.length,
  };

  const scenes = [
    {
      kind: 'cover',
      duration: 4.0,
      seed: 11,
      data: {
        kicker: spec.kicker,
        title: spec.title,
        subtitle: spec.subtitle,
        footer: spec.footer,
        date,
      },
    },
  ];

  let si = 0;
  const sectionPageCursor = new Map();
  sections.forEach((section) => {
    scenes.push({
      kind: 'section',
      duration: 2.5,
      seed: 31 + si,
      data: {
        index: si,
        total: sections.length,
        heading: section.heading,
        caption: section.caption,
        count: section.items.length,
      },
    });
    pages
      .filter((p) => p.section === section)
      .forEach((p) => {
        const page = (sectionPageCursor.get(section) || 0) + 1;
        sectionPageCursor.set(section, page);
        scenes.push({
          kind: 'list',
          duration: 1.0 + p.items.length * 0.5 + 1.0,
          seed: 71 + si * 13 + page,
          data: {
            heading: section.heading,
            page,
            pages: p.pageCount,
            pageSize: PAGE_SIZE,
            items: p.items,
            footer: spec.footer,
          },
        });
      });
    si += 1;
  });

  scenes.push({
    kind: 'end',
    duration: 4.5,
    seed: 301,
    data: {
      title: spec.endingTitle || '数据已归档',
      subtitle: spec.endingSubtitle || '',
      footer: spec.footer,
    },
  });

  return { scenes, stats };
}

function customScenes(spec, date) {
  const stats = {
    sections: spec.scenes.filter((s) => s.type === 'section' || s.type === 'portrait').length,
    items: spec.scenes.reduce((sum, s) => sum + (s.items ? s.items.length : 0), 0),
    pages: spec.scenes.filter((s) => s.type === 'list').length,
  };

  const scenes = [];
  let sectionIndex = 0;
  const chapterTotal = spec.scenes.filter((s) => s.type === 'section' || s.type === 'portrait').length;

  spec.scenes.forEach((item, i) => {
    const seed = 101 + i * 17;
    switch (item.type) {
      case 'cover':
        scenes.push({
          kind: 'cover',
          duration: item.duration || 4.0,
          seed,
          data: {
            kicker: item.kicker || spec.kicker,
            title: item.title || spec.title,
            subtitle: item.subtitle || spec.subtitle,
            footer: item.footer || spec.footer,
            date,
          },
        });
        break;
      case 'portrait':
        scenes.push({
          kind: 'portrait',
          duration: item.duration || 4.0,
          seed,
          data: {
            index: sectionIndex,
            total: Math.max(chapterTotal, 1),
            variant: item.variant,
            title: item.title,
            subtitle: item.subtitle,
            caption: item.caption,
            keywords: item.keywords,
            accent: item.accent,
            side: item.side,
          },
        });
        sectionIndex += 1;
        break;
      case 'section':
        scenes.push({
          kind: 'section',
          duration: item.duration || 2.5,
          seed,
          data: {
            index: sectionIndex,
            total: Math.max(chapterTotal, 1),
            heading: item.heading,
            caption: item.caption,
            count: item.count || 0,
          },
        });
        sectionIndex += 1;
        break;
      case 'list': {
        const pages = chunk(item.items || [], 6);
        pages.forEach((items, pageIndex) => {
          scenes.push({
            kind: 'list',
            duration: item.duration || 1.0 + items.length * 0.5 + 1.0,
            seed: seed + pageIndex,
            data: {
              heading: item.heading || '',
              page: pageIndex + 1,
              pages: pages.length,
              pageSize: 6,
              items,
              footer: item.footer || spec.footer,
            },
          });
        });
        break;
      }
      case 'stat':
        scenes.push({
          kind: 'stat',
          duration: item.duration || 4.0,
          seed,
          data: { title: item.title, items: item.items || [] },
        });
        break;
      case 'quote':
        scenes.push({
          kind: 'quote',
          duration: item.duration || 4.5,
          seed,
          data: { text: item.text, author: item.author },
        });
        break;
      case 'end':
        scenes.push({
          kind: 'end',
          duration: item.duration || 4.5,
          seed,
          data: {
            title: item.title || spec.endingTitle || '完',
            subtitle: item.subtitle || '',
            footer: item.footer || spec.footer,
          },
        });
        break;
      default:
        break;
    }
  });

  return { scenes, stats };
}

export function buildPlan(spec) {
  const size = RESOLUTIONS[spec.resolution] || RESOLUTIONS['1080p'];
  const date = spec.date || formatDate(new Date());
  const built = spec.template === 'scenes' ? customScenes(spec, date) : ledgerScenes(spec, date);
  const scenes = withTransitions(built.scenes, spec.seed || 0);
  const totalDuration = scenes.reduce((sum, s) => sum + s.duration, 0);

  if (totalDuration > MAX_TOTAL_SECONDS) {
    const error = new Error(
      `内容太长（约 ${Math.round(totalDuration)} 秒），单个任务最多 ${MAX_TOTAL_SECONDS} 秒，请删减条目或拆成多个任务`,
    );
    error.code = 'content_too_long';
    throw error;
  }

  return {
    template: spec.template,
    theme: spec.theme,
    width: size.width,
    height: size.height,
    fps: spec.fps,
    audio: spec.audio !== false,
    scenes,
    totalDuration,
    stats: built.stats,
    spec: { ...spec, date },
    design: { width: W, height: H },
  };
}

export function formatDate(date) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}.${pad(date.getMonth() + 1)}.${pad(date.getDate())}`;
}

export { RESOLUTIONS, MAX_TOTAL_SECONDS };
