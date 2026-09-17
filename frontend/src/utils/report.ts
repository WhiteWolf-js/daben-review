/** 复盘 markdown 的解析工具:海报与盘后决策区共用,勿各写一份正则。 */

/** 从复盘 markdown 取「四、情绪周期与明日核心矛盾」段正文(到下一个 ## 之前);取不到返回空串。 */
export function extractConflict(md: string): string {
  const m = md.match(/##\s*四、[^\n]*\n([\s\S]*?)(?=\n##\s|$)/);
  if (!m) return "";
  return m[1]
    .replace(/```[\s\S]*?```/g, "") // 去代码块
    .replace(/[*_`#>]/g, "") // 去 markdown 标记,按纯文本排版
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .join("\n");
}

/** 剥掉供系统解析的 ```json 候选块(agent 可能在其后仍附文字,故全局剥离而非仅尾部)。 */
export function stripJson(md: string): string {
  return md.replace(/```json[\s\S]*?```/g, "").replace(/\n{3,}/g, "\n\n").trimEnd();
}

/** 完整复盘长图拆几张 —— 见 sliceReportPart 的说明 */
export const REPORT_PARTS = 2;
/**
 * 第一张放前几段。五段结构下 3 = 「一、方向 + 二、画像 + 三、属性对立」,
 * 语义上正好切成「今日发生了什么 / 明日怎么打(四、核心矛盾 + 五、候选)」,
 * 两张也更均衡(20260916 实测 1:1.52 与 1:1.29;切在 2 段时是 1:1.20 与 1:1.60,后半更细长)。
 * **别按字数切** —— 画像段字多但是紧凑卡片,候选段字少却每只票占 4-5 行,字数和高度不成比例。
 */
const PART1_SECTIONS = 3;

/**
 * 把复盘正文切成第 `part` 张图的 markdown(part 从 1 起;越界返回空串)。
 *
 * **为什么要拆**:整篇是 1:2.7 的细长图,飞书聊天气泡按高度压缩后宽度只剩 21%,
 * 字全糊了(摘要海报 1:1.2 就清楚)。拆成两张各约 1:1.4,气泡里才读得动。
 *
 * **按位置切,不按段号切**:段号解析不出来时(agent 偶尔漏写「一、」前缀)按号分配会
 * 整段丢失,按位置切最坏只是两张不均衡。数据基础/自检行只跟第一张,不重复出现。
 */
export function sliceReportPart(md: string, part: number): string {
  const { preamble, sections } = splitSectionsRaw(md);
  const picked = part === 1 ? sections.slice(0, PART1_SECTIONS) : sections.slice(PART1_SECTIONS);
  if (!picked.length) return "";
  const body = picked.map((s) => `## ${s.head}\n${s.body}`).join("\n\n");
  return part === 1 && preamble ? `${preamble}\n\n${body}` : body;
}

/** 每张图的副标题:直接用该张实际包含的段标题,agent 改了段名也对得上 */
export function reportPartTitles(md: string, part: number): string[] {
  const { sections } = splitSectionsRaw(md);
  const picked = part === 1 ? sections.slice(0, PART1_SECTIONS) : sections.slice(PART1_SECTIONS);
  return picked.map((s) => s.head.replace(/^[一二三四五六七八九十]+、\s*/, ""));
}

/** 按 `## ` 切段,保留原始标题行 —— 与 reportParse.splitSections 同一套切法,
 *  但这里要原样重组回 markdown,所以不解析段号。 */
function splitSectionsRaw(md: string): { preamble: string; sections: { head: string; body: string }[] } {
  const parts = md.split(/^##\s*/m);
  const preamble = (parts.shift() ?? "").trim();
  const sections = parts.map((p) => {
    const nl = p.indexOf("\n");
    return {
      head: (nl < 0 ? p : p.slice(0, nl)).trim(),
      body: (nl < 0 ? "" : p.slice(nl + 1)).trim(),
    };
  });
  return { preamble, sections };
}
