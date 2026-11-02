// 请求规格校验：所有限制集中在这里，API 文档与错误提示都以本文件为准。
export class ValidationError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
    this.status = 400;
  }
}

export const LIMITS = {
  sections: 12,
  itemsPerSection: 40,
  itemsTotal: 120,
  scenes: 24,
  title: 60,
  kicker: 40,
  subtitle: 120,
  footer: 120,
  heading: 32,
  caption: 80,
  label: 40,
  value: 20,
  note: 80,
  quote: 240,
  author: 40,
  keyword: 16,
};

const THEMES = ['ink', 'paper', 'signal'];
const RESOLUTIONS = ['1080p', '720p'];
const FPS = [24, 30];
const PORTRAIT_VARIANTS = ['pride', 'envy', 'wrath', 'sloth', 'greed', 'gluttony', 'lust', 'figure'];

function clean(value, max, label) {
  if (value === undefined || value === null) return '';
  if (typeof value !== 'string') throw new ValidationError('bad_field', `${label} 必须是字符串`);
  const text = value
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '')
    .replace(/\r\n/g, '\n')
    .trim();
  if ([...text].length > max) {
    throw new ValidationError('too_long', `${label}最多 ${max} 个字（当前 ${[...text].length}）`);
  }
  return text;
}

function cleanLine(value, max, label) {
  return clean(value, max, label).replace(/\s*\n+\s*/g, ' ');
}

function requireText(value, max, label) {
  const text = cleanLine(value, max, label);
  if (!text) throw new ValidationError('empty_field', `请填写${label}`);
  return text;
}

function arr(value, max, label) {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) throw new ValidationError('bad_field', `${label} 必须是数组`);
  if (value.length > max) throw new ValidationError('too_many', `${label}最多 ${max} 项`);
  return value;
}

function itemsOf(list, label) {
  return arr(list, LIMITS.itemsPerSection, label).map((item, index) => {
    if (!item || typeof item !== 'object') {
      throw new ValidationError('bad_field', `${label}第 ${index + 1} 条格式不正确`);
    }
    const name = cleanLine(item.label, LIMITS.label, `${label}第 ${index + 1} 条的名称`);
    if (!name) throw new ValidationError('empty_field', `${label}第 ${index + 1} 条缺少名称`);
    return {
      label: name,
      value: cleanLine(item.value, LIMITS.value, '数值'),
      note: cleanLine(item.note, LIMITS.note, '备注'),
    };
  });
}

function normalizeScenes(scenes) {
  if (!Array.isArray(scenes) || scenes.length === 0) {
    throw new ValidationError('empty_scenes', 'scenes 模板至少需要 1 个场景');
  }
  if (scenes.length > LIMITS.scenes) {
    throw new ValidationError('too_many', `场景最多 ${LIMITS.scenes} 个`);
  }
  return scenes.map((scene, i) => {
    const label = `第 ${i + 1} 个场景`;
    if (!scene || typeof scene !== 'object') {
      throw new ValidationError('bad_field', `${label}格式不正确`);
    }
    const type = String(scene.type || '').trim();
    const duration =
      scene.duration === undefined
        ? undefined
        : Math.min(20, Math.max(1.5, Math.round((Number(scene.duration) || 0) * 2) / 2));
    switch (type) {
      case 'cover':
        return {
          type,
          duration,
          kicker: cleanLine(scene.kicker, LIMITS.kicker, '眉标'),
          title: cleanLine(scene.title, LIMITS.title, '标题'),
          subtitle: cleanLine(scene.subtitle, LIMITS.subtitle, '副标题'),
          footer: cleanLine(scene.footer, LIMITS.footer, '页脚'),
        };
      case 'portrait':
        return {
          type,
          duration,
          variant: PORTRAIT_VARIANTS.includes(scene.variant) ? scene.variant : 'figure',
          title: requireText(scene.title, LIMITS.heading, '人像标题'),
          subtitle: cleanLine(scene.subtitle, LIMITS.subtitle, '人像副标题'),
          caption: cleanLine(scene.caption, LIMITS.caption, '人像说明'),
          keywords: arr(scene.keywords, 4, '关键词').map((word, index) =>
            cleanLine(word, LIMITS.keyword, `第 ${index + 1} 个关键词`),
          ),
          side: scene.side === 'left' ? 'left' : scene.side === 'right' ? 'right' : '',
          accent: /^#[0-9a-fA-F]{6}$/.test(String(scene.accent || '')) ? String(scene.accent) : '',
        };
      case 'section':
        return {
          type,
          duration,
          heading: requireText(scene.heading, LIMITS.heading, '章节标题'),
          caption: cleanLine(scene.caption, LIMITS.caption, '章节说明'),
          count: Math.max(0, Math.min(9999, Number(scene.count) || 0)),
        };
      case 'list': {
        const items = itemsOf(scene.items, '列表条目');
        if (items.length === 0) throw new ValidationError('empty_field', `${label}至少需要 1 条记录`);
        return {
          type,
          duration,
          heading: cleanLine(scene.heading, LIMITS.heading, '列表标题'),
          footer: cleanLine(scene.footer, LIMITS.footer, '页脚'),
          items,
        };
      }
      case 'stat': {
        const items = arr(scene.items, 3, '数字卡片').map((item) => ({
          value: cleanLine(item?.value, LIMITS.value, '数字'),
          label: cleanLine(item?.label, LIMITS.label, '数字说明'),
          note: cleanLine(item?.note, LIMITS.note, '数字备注'),
        }));
        if (items.length === 0) throw new ValidationError('empty_field', `${label}至少需要 1 个数字`);
        return { type, duration, title: cleanLine(scene.title, LIMITS.heading, '数字页标题'), items };
      }
      case 'quote':
        return {
          type,
          duration,
          text: requireText(scene.text, LIMITS.quote, '引用文字'),
          author: cleanLine(scene.author, LIMITS.author, '引用出处'),
        };
      case 'end':
        return {
          type,
          duration,
          title: cleanLine(scene.title, LIMITS.title, '结尾标题'),
          subtitle: cleanLine(scene.subtitle, LIMITS.subtitle, '结尾副标题'),
          footer: cleanLine(scene.footer, LIMITS.footer, '页脚'),
        };
      default:
        throw new ValidationError(
          'bad_scene_type',
          `${label}类型不支持：${type || '(空)'}，可用 cover/section/list/stat/quote/end`,
        );
    }
  });
}

export function validateSpec(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    throw new ValidationError('bad_body', '请求体必须是 JSON 对象');
  }
  const template = input.template === 'scenes' ? 'scenes' : 'ledger';
  const theme = THEMES.includes(input.theme) ? input.theme : 'ink';
  const resolution = RESOLUTIONS.includes(input.resolution) ? input.resolution : '1080p';
  const fps = FPS.includes(Number(input.fps)) ? Number(input.fps) : 30;

  const spec = {
    template,
    theme,
    resolution,
    fps,
    kicker: cleanLine(input.kicker, LIMITS.kicker, '眉标'),
    title: cleanLine(input.title, LIMITS.title, '标题'),
    subtitle: cleanLine(input.subtitle, LIMITS.subtitle, '副标题'),
    footer: cleanLine(input.footer, LIMITS.footer, '页脚'),
    endingTitle: cleanLine(input.ending_title, LIMITS.title, '结尾标题'),
    endingSubtitle: cleanLine(input.ending_subtitle, LIMITS.subtitle, '结尾副标题'),
    date: cleanLine(input.date, 20, '日期'),
    verify: input.verify !== false,
    audio: input.audio !== false,
    seed: Math.abs(Number(input.seed) || 0) % 100000,
    sections: [],
    scenes: [],
  };

  if (template === 'scenes') {
    spec.scenes = normalizeScenes(input.scenes);
    const cover = spec.scenes.find((s) => s.type === 'cover');
    if (!spec.title) spec.title = cover?.title || '';
    if (!spec.title) throw new ValidationError('empty_field', 'scenes 模板需要一个标题（顶层 title 或 cover 场景）');
  } else {
    if (!spec.title) throw new ValidationError('empty_field', '请填写标题');
    const sections = arr(input.sections, LIMITS.sections, '章节');
    if (sections.length === 0) throw new ValidationError('empty_sections', '至少需要 1 个章节');
    let total = 0;
    spec.sections = sections.map((section, i) => {
      const label = `第 ${i + 1} 个章节`;
      const heading = cleanLine(section?.heading, LIMITS.heading, `${label}标题`);
      if (!heading) throw new ValidationError('empty_field', `${label}缺少标题`);
      const items = itemsOf(section.items, `${label}的条目`);
      if (items.length === 0) throw new ValidationError('empty_field', `${label}至少需要 1 条记录`);
      total += items.length;
      return {
        heading,
        caption: cleanLine(section.caption, LIMITS.caption, `${label}说明`),
        items,
      };
    });
    if (total > LIMITS.itemsTotal) {
      throw new ValidationError('too_many', `条目总数最多 ${LIMITS.itemsTotal} 条（当前 ${total}）`);
    }
  }

  return spec;
}
