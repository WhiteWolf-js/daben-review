/**
 * 复盘正文 markdown → 结构化数据(供 ReportStructured 画成图示)。
 *
 * 为什么要解析:prompt 强制的五段模板是「一行一条、`—` 分隔字段」,但相邻行之间
 * 只有单换行,markdown 会把它们折叠成一大段 —— 读起来是一堵墙。与其改 prompt
 * (要同日复跑≥2次比对、且救不了历史报告),不如在前端把字段还原成表格/卡片。
 *
 * 铁律:**认不出就回退原文,绝不吞内容**。每个 parse* 把没吃掉的行原样放进 rest,
 * 由渲染层继续按 markdown 画;整段一条都认不出就返回 null 走全段 markdown。
 *
 * agent 的行格式历史上漂过,正则按这些**实测**变体放宽,别再收紧:
 * - 主线行:`主线1 名称(…)` / `**主线1 名称**(…)` / 反引号包裹且无「主线N」前缀
 * - 字段名:`属性定性:`~`属性:`、`龙头:`~`代表票:`、`今日实际走属性:`~`今日实际走的属性:`
 * - 强弱值:`中` / `**中**(依据:…)` / `弱转分歧:…`
 * - 画像头的 `[席位]` 可缺;对立行的关系词有 压制/独立于/分流/分化/⇄
 * - 0723 及更早整段用 markdown 表格 —— 表格本来就渲染得好,回退即可
 */

const DASH = "(?:[—–]{1,2}|--)";
const RE = {
  dir: new RegExp(
    `^[\`*\\s]*(?:主线\\d+\\s*)?([^*\`(（]+?)[*\`]*\\s*[(（]([^)）]*)[)）]\\s*${DASH}` +
      `\\s*属性(?:定性)?[:：]\\s*(.*?)\\s*${DASH}\\s*(?:强弱[:：]\\s*)?(.*?)\\s*${DASH}` +
      `\\s*(?:龙头|代表票)[:：]\\s*(.*?)[\`\\s]*$`,
  ),
  // 括号内必须像「N板,…」的读数串(含板+逗号),否则任何以括号结尾的句子都会误命中
  profHead:
    /^\*{0,2}(?:\[(.+?)\]\s*)?([^[\](（*]+?)[(（]([^)）]*板[,，][^)）]*)[)）]\*{0,2}\s*(?:[—–]{1,2}\s*(?:多属性[:：])?\s*(.*))?$/,
  profLine: /^-\s*\*{0,2}(今日实际走[^:：]{0,4}|(?:梯队)?卡位)\*{0,2}[:：]\s*(.*)$/,
  // 两侧限「不含句号、≤64字」的短标 —— 不能排除冒号,右侧读数会带时间(如「华之杰14:31弱封」)
  clash: /^[`\s]*-?\s*\**([^。]{1,64}?)\**\s*(压制|独立于|对立|分流|分化|⇄)\s*\**([^。]{1,64}?)\**\s*[—–]{2,}\s*(.+?)[`\s]*$/,
  // `- **某某:** 一整段论述` 是散文条目不是对立行(0723/0724 那批),命中就跳过,否则右侧会吞掉整段
  clashLabel: /^[-*\s`]*\*\*[^*]+[:：]\*\*/,
  ifThen: /^-\s*若(.+?)\s*→\s*(.+)$/,
  phase: /^\*{0,2}周期定位\*{0,2}[:：]\s*(.+)$/,
  pickStyle: /^\*\*(.+?)\*\*$/,
  pick: /^(.+?)[(（](\d{6})[,，](.+?)[)）]\s*触发[:：]\s*(.+?)\s*[|｜]\s*放弃[:：]\s*(.+?)\s*[|｜]\s*逻辑[:：]\s*(.+)$/,
  basis: /数据基础[:：]\s*(.+)$/m,
};

export type Section = { num: string; title: string; body: string };

/** 按 `## ` 切段;`##` 之前的内容(自检行 + 数据基础)作 preamble。 */
export function splitSections(md: string): { preamble: string; sections: Section[] } {
  const parts = md.split(/^##\s*/m);
  const preamble = (parts.shift() ?? "").trim();
  const sections = parts.map((p) => {
    const nl = p.indexOf("\n");
    const head = (nl < 0 ? p : p.slice(0, nl)).trim();
    const body = (nl < 0 ? "" : p.slice(nl + 1)).trim();
    const m = head.match(/^([一二三四五六七八九十]+)、\s*(.*)$/);
    return { num: m?.[1] ?? "", title: m?.[2] ?? head, body };
  });
  return { preamble, sections };
}

/** preamble 里的 `数据基础:A / B / C` → 芯片数组;取不到返回空数组。 */
export function parseBasis(preamble: string): string[] {
  const m = preamble.match(RE.basis);
  if (!m) return [];
  // 按「空格/空格」切,不能按裸 `/` —— 末项本身是 `工具6/6`
  return m[1]
    .split(/\s+\/\s+/)
    .map((s) => s.replace(/[`*>]/g, "").trim())
    .filter(Boolean);
}

const clean = (s: string) => s.replace(/[`*]/g, "").trim();

/** 强弱字段 `**中**(依据:…)` / `弱转分歧:…` → 标签 + 依据。标签原样留(0727 有「弱转分歧」)。 */
function splitStrength(raw: string): { label: string; why: string } {
  const s = clean(raw);
  const m = s.match(/^([^:：(（]{1,8})[:：(（]?\s*([\s\S]*)$/);
  if (!m) return { label: s, why: "" };
  return {
    label: m[1].trim(),
    why: m[2].replace(/[)）]\s*$/, "").replace(/^依据[:：]\s*/, "").trim(),
  };
}

/** 强弱标签 → 色调(A股口径:强=红 / 弱=绿)。 */
export function strengthTone(label: string): "strong" | "mid" | "weak" {
  if (label.includes("强")) return "strong";
  if (label.includes("弱")) return "weak";
  return "mid";
}

export type DirRow = { name: string; counts: string; attr: string; strength: string; why: string; leader: string };

/** 一、盘面方向拆解。剩下的(当前市场风格等)原样回 rest。 */
export function parseDirections(body: string): { rows: DirRow[]; rest: string } | null {
  const rows: DirRow[] = [];
  const rest: string[] = [];
  for (const line of body.split("\n")) {
    const m = line.trim().match(RE.dir);
    if (m) {
      const s = splitStrength(m[4]);
      rows.push({
        name: clean(m[1]),
        counts: clean(m[2]),
        attr: clean(m[3]),
        strength: s.label,
        why: s.why,
        leader: clean(m[5]),
      });
    } else rest.push(line);
  }
  return rows.length ? { rows, rest: rest.join("\n").trim() } : null;
}

export type ProfCard = {
  seat: string;
  name: string;
  stats: string[];
  attrs: string[];
  lines: { label: string; text: string }[];
};

/** 二、重点连板票属性画像 → 每票一张卡。 */
export function parseProfiles(body: string): { cards: ProfCard[]; rest: string } | null {
  const cards: ProfCard[] = [];
  const rest: string[] = [];
  for (const line of body.split("\n")) {
    const t = line.trim();
    const head = t.match(RE.profHead);
    if (head) {
      cards.push({
        seat: clean(head[1] ?? ""),
        name: clean(head[2]),
        stats: head[3].split(/[,，]/).map(clean).filter(Boolean),
        attrs: (head[4] ?? "").split(/\s*\+\s*/).map(clean).filter(Boolean),
        lines: [],
      });
      continue;
    }
    const sub = t.match(RE.profLine);
    if (sub && cards.length) {
      cards[cards.length - 1].lines.push({ label: clean(sub[1]), text: clean(sub[2]) });
      continue;
    }
    if (t) rest.push(line);
  }
  return cards.length ? { cards, rest: rest.join("\n").trim() } : null;
}

/** `传智教育(强,封流比8.2%)` → { head:"传智教育", note:"强,封流比8.2%" };没括号则 note 为空。 */
export function parseParen(s: string): { head: string; note: string } {
  const m = s.match(/^(.*?)[(（](.+)[)）]\s*$/);
  return m ? { head: clean(m[1]), note: clean(m[2]) } : { head: clean(s), note: "" };
}

export type ClashRow = { left: string; rel: string; right: string; mech: string };

/** 三、属性对立与联动 → 左强 vs 右弱 的对峙行。 */
export function parseClashes(body: string): { rows: ClashRow[]; rest: string } | null {
  const rows: ClashRow[] = [];
  const rest: string[] = [];
  for (const line of body.split("\n")) {
    const t = line.trim();
    const m = RE.clashLabel.test(t) ? null : t.match(RE.clash);
    if (m) rows.push({ left: clean(m[1]), rel: m[2], right: clean(m[3]), mech: clean(m[4]) });
    else if (t) rest.push(line);
  }
  return rows.length ? { rows, rest: rest.join("\n").trim() } : null;
}

export type Scenario = { title: string; rows: { cond: string; then: string }[] };

/**
 * 周期定位的值有两种(prompt 都允许):单词 `修复`,或修正长句
 * `规则初判修复 → 修正为分歧,依据:1进2晋级率13.33%…`。
 * 后者整串塞芯片会溢出,所以拆成:结论词(取最后一段里的 6 词枚举)+ 修正过程 + 依据。
 */
function splitPhase(raw: string): { phase: string; note: string; why: string } {
  let s = raw;
  let why = "";
  const w = s.split(/[,，]?\s*依据[:：]\s*/);
  if (w.length > 1) {
    s = w[0];
    why = w.slice(1).join("");
  }
  const parts = s.split(/\s*(?:→|->)\s*/);
  const tail = parts[parts.length - 1].trim();
  const enum6 = tail.match(/(冰点|修复|发酵|分歧|高潮|退潮)/);
  return {
    phase: enum6 ? enum6[1] : tail,
    note: parts.length > 1 ? `${parts.slice(0, -1).join(" → ")} → ${enum6 ? tail : ""}`.trim() : "",
    why,
  };
}

/** 四、情绪周期与明日核心矛盾 → 周期定位 + 每票的 if/则 分支。 */
export function parseScenarios(
  body: string,
): { phase: string; phaseNote: string; phaseWhy: string; blocks: Scenario[]; rest: string } | null {
  let phase = "";
  let phaseNote = "";
  const phaseWhy: string[] = [];
  const blocks: Scenario[] = [];
  const rest: string[] = [];
  for (const line of body.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    const ph = t.match(RE.phase);
    if (ph && !phase) {
      const sp = splitPhase(clean(ph[1]));
      phase = sp.phase;
      phaseNote = sp.note;
      if (sp.why) phaseWhy.push(sp.why);
      continue;
    }
    const it = t.match(RE.ifThen);
    if (it && blocks.length) {
      blocks[blocks.length - 1].rows.push({ cond: clean(it[1]), then: clean(it[2]) });
      continue;
    }
    // `**名称(代码)**` 开一个新分支块
    const title = t.match(/^\*\*(.+?)\*\*$/);
    if (title && !/^周期定位/.test(title[1])) {
      blocks.push({ title: clean(title[1]), rows: [] });
      continue;
    }
    if (phase && !blocks.length) phaseWhy.push(t); // 周期定位后、第一个块之前的都是依据
    else rest.push(line);
  }
  const usable = blocks.some((b) => b.rows.length);
  if (!phase && !usable) return null;
  return {
    phase,
    phaseNote,
    phaseWhy: phaseWhy.join("\n").replace(/^依据[:：]\s*/, "").trim(),
    blocks: blocks.filter((b) => b.rows.length),
    rest: rest.join("\n").trim(),
  };
}

export type PickRow = {
  name: string;
  code: string;
  meta: string;
  trigger: string;
  giveup: string;
  reason: string;
};
export type PickGroup = { style: string; rows: PickRow[]; note: string };

/** 五、四风格候选票 → 每风格一组(可能没票,只有一句说明,如「今日不参与(rank1仅D级)」)。 */
export function parsePicks(body: string): { groups: PickGroup[]; rest: string } | null {
  const groups: PickGroup[] = [];
  const rest: string[] = [];
  const notes: string[][] = [];
  for (const line of body.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    const st = t.match(RE.pickStyle);
    if (st) {
      groups.push({ style: clean(st[1]), rows: [], note: "" });
      notes.push([]);
      continue;
    }
    const p = t.match(RE.pick);
    if (p && groups.length) {
      groups[groups.length - 1].rows.push({
        name: clean(p[1]),
        code: p[2],
        meta: clean(p[3]),
        trigger: clean(p[4]),
        giveup: clean(p[5]),
        reason: clean(p[6]),
      });
      continue;
    }
    if (groups.length) notes[notes.length - 1].push(t);
    else rest.push(line);
  }
  groups.forEach((g, i) => (g.note = notes[i].join(" ")));
  // 一条候选行都没认出来(只匹配到风格小标题)就整段回退 —— 否则画出一堆空壳只剩 note
  if (!groups.some((g) => g.rows.length)) return null;
  return { groups, rest: rest.join("\n").trim() };
}
