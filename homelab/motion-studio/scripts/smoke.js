// 容器内冒烟测试：不启动 HTTP，直接跑一遍完整渲染，验证字体、转场与 ffmpeg 编码。
import { validateSpec } from '../src/validate.js';
import { buildPlan } from '../src/plan.js';
import { renderVideo } from '../src/render.js';

const spec = validateSpec({
  template: 'ledger',
  theme: process.env.SMOKE_THEME || 'ink',
  resolution: '720p',
  fps: 24,
  kicker: 'SMOKE TEST',
  title: '一页台账的十八秒',
  subtitle: '验证中文、数字、转场与编码是否都正常',
  footer: 'motion-studio smoke test',
  sections: [
    {
      heading: '第一章 · 起点',
      caption: '2026-11-02',
      items: [
        { label: '首条记录', value: '#001', note: '采集时间 09:12' },
        { label: '关联账号', value: '3 个', note: '其中 1 个已注销' },
        { label: '传播峰值', value: '1.2 万', note: '出现在第 6 小时' },
      ],
    },
    {
      heading: '第二章 · 收束',
      items: [
        { label: '已核验条目', value: '24', note: '全部带原始链接' },
        { label: '待补充', value: '2', note: '等待平台回执' },
      ],
    },
  ],
});

const plan = buildPlan(spec);
const out = process.env.SMOKE_OUT || '/tmp/motion-smoke.mp4';
console.log(`场景 ${plan.scenes.length} 个，总时长 ${plan.totalDuration.toFixed(1)}s，${plan.width}x${plan.height}@${plan.fps}`);

const result = await renderVideo(plan, {
  outPath: out,
  posterPath: out.replace(/\.mp4$/, '.png'),
  onProgress: (progress) => {
    if (progress.frames_done % 60 === 0 || progress.frames_done === progress.frames_total) {
      console.log(`  ${progress.frames_done}/${progress.frames_total}`);
    }
  },
});

console.log('渲染完成：', JSON.stringify(result));
if (!result.checks.passed) {
  console.log('注意：数值核验有告警', result.checks.warnings);
}
