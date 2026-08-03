import type { ReactNode } from "react";
import { Box, Stack, Typography } from "@mui/material";
import MarkdownText from "./MarkdownText";
import {
  parseBasis,
  parseClashes,
  parseDirections,
  parseParen,
  parsePicks,
  parseProfiles,
  parseScenarios,
  splitSections,
  strengthTone,
} from "../utils/reportParse";

/** 与天梯图同一套配色(强=红 / 弱=绿,A股口径) */
const C = {
  up: "#e5484d",
  down: "#30a46c",
  warn: "#f5a623",
  blue: "#58a6ff",
  text: "#e6edf3",
  muted: "#8b949e",
  dim: "#6e7681",
  line: "#21262d",
  panel: "#161b22",
};
const TONE = { strong: C.up, mid: C.warn, weak: C.down };

function Pill({
  children,
  color = C.muted,
  solid,
  size = 11,
}: {
  children: ReactNode;
  color?: string;
  solid?: boolean;
  size?: number;
}) {
  return (
    <Box
      component="span"
      sx={{
        fontSize: size,
        fontWeight: 700,
        lineHeight: 1.7,
        px: 0.75,
        borderRadius: 0.5,
        whiteSpace: "nowrap",
        ...(solid
          ? { bgcolor: color, color: "#fff" }
          : { color, border: `1px solid ${color}55`, bgcolor: `${color}14` }),
      }}
    >
      {children}
    </Box>
  );
}

/** 段外框:标题条 + 内容。标题用 markdown 里的原文,不自造。 */
function Section({ num, title, children }: { num: string; title: string; children: ReactNode }) {
  return (
    <Box sx={{ mt: 2.5 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <Box sx={{ width: 3, height: 15, bgcolor: C.up, borderRadius: 1 }} />
        <Typography sx={{ fontSize: 15, fontWeight: 700, color: C.text }}>
          {num && `${num}、`}
          {title}
        </Typography>
      </Stack>
      {children}
    </Box>
  );
}

/** 一、盘面方向拆解:一主线一行 —— 名称 / 强弱 / 属性 / 家数,第二行挂龙头与依据。 */
function Directions({ body }: { body: string }) {
  const p = parseDirections(body);
  if (!p) return <MarkdownText md={body} />;
  return (
    <>
      <Box sx={{ border: `1px solid ${C.line}`, borderRadius: 1, overflow: "hidden" }}>
        {p.rows.map((r, i) => (
          <Box key={i} sx={{ borderTop: i ? `1px solid ${C.line}` : "none", px: 1.5, py: 1 }}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Box
                sx={{
                  width: 20, height: 20, flexShrink: 0, borderRadius: "50%", bgcolor: C.panel,
                  color: C.muted, fontSize: 11, fontWeight: 700,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}
              >
                {i + 1}
              </Box>
              <Typography sx={{ fontSize: 15, fontWeight: 700, color: C.text }}>{r.name}</Typography>
              {r.strength && (
                <Pill solid color={TONE[strengthTone(r.strength)]}>
                  {r.strength}
                </Pill>
              )}
              {r.attr && <Pill color={C.blue}>{r.attr}</Pill>}
              <Box sx={{ flexGrow: 1 }} />
              <Typography sx={{ fontSize: 12, color: C.muted }}>{r.counts}</Typography>
            </Stack>
            <Stack direction="row" spacing={0.75} sx={{ mt: 0.5, pl: "28px" }} flexWrap="wrap" useFlexGap>
              {r.leader && (
                <Typography sx={{ fontSize: 12, color: C.warn, fontWeight: 600 }}>龙头 {r.leader}</Typography>
              )}
              {r.why && <Typography sx={{ fontSize: 12, color: C.muted, lineHeight: 1.7 }}>{r.why}</Typography>}
            </Stack>
          </Box>
        ))}
      </Box>
      {p.rest && <Box sx={{ mt: 1 }}><MarkdownText md={p.rest} /></Box>}
    </>
  );
}

/** 二、属性画像:一票一卡 —— 席位标 + 读数芯片 + 多属性标签 + 走属性/卡位两行。 */
function Profiles({ body }: { body: string }) {
  const p = parseProfiles(body);
  if (!p) return <MarkdownText md={body} />;
  return (
    <>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", lg: "1fr 1fr" }, gap: 1.25 }}>
        {p.cards.map((c, i) => (
          <Box key={i} sx={{ border: `1px solid ${C.line}`, borderRadius: 1, p: 1.25, bgcolor: C.panel }}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              {c.seat && <Pill solid color={C.up}>{c.seat}</Pill>}
              <Typography sx={{ fontSize: 15, fontWeight: 700, color: C.text }}>{c.name}</Typography>
            </Stack>
            <Stack direction="row" spacing={0.5} sx={{ mt: 0.75 }} flexWrap="wrap" useFlexGap>
              {c.stats.map((s) => (
                <Pill key={s}>{s}</Pill>
              ))}
            </Stack>
            {c.attrs.length > 0 && (
              <Stack direction="row" spacing={0.5} sx={{ mt: 0.5 }} flexWrap="wrap" useFlexGap alignItems="center">
                <Typography sx={{ fontSize: 11, color: C.dim }}>多属性</Typography>
                {c.attrs.map((a) => (
                  <Pill key={a} color={C.blue}>{a}</Pill>
                ))}
              </Stack>
            )}
            {c.lines.map((l, j) => (
              <Stack key={j} direction="row" spacing={0.75} sx={{ mt: 0.75 }}>
                <Typography
                  sx={{ fontSize: 11, color: C.warn, fontWeight: 700, whiteSpace: "nowrap", pt: "2px" }}
                >
                  {l.label}
                </Typography>
                <Typography sx={{ fontSize: 12.5, lineHeight: 1.75, color: C.text }}>{l.text}</Typography>
              </Stack>
            ))}
          </Box>
        ))}
      </Box>
      {p.rest && <Box sx={{ mt: 1 }}><MarkdownText md={p.rest} /></Box>}
    </>
  );
}

/** 三、属性对立:左强 →关系→ 右弱,机制单独一行。窄屏纵向堆叠。 */
function Clashes({ body }: { body: string }) {
  const p = parseClashes(body);
  if (!p) return <MarkdownText md={body} />;
  const Side = ({ raw, color }: { raw: string; color: string }) => {
    const { head, note } = parseParen(raw);
    return (
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography sx={{ fontSize: 13.5, fontWeight: 700, color }}>{head}</Typography>
        {note && <Typography sx={{ fontSize: 11.5, color: C.muted, lineHeight: 1.6 }}>{note}</Typography>}
      </Box>
    );
  };
  return (
    <>
      <Stack spacing={1}>
        {p.rows.map((r, i) => (
          <Box key={i} sx={{ border: `1px solid ${C.line}`, borderRadius: 1, p: 1.25 }}>
            <Stack
              direction={{ xs: "column", sm: "row" }}
              spacing={1}
              alignItems={{ xs: "flex-start", sm: "center" }}
            >
              <Side raw={r.left} color={C.up} />
              <Pill solid color={C.dim} size={11}>
                {r.rel} ▸
              </Pill>
              <Side raw={r.right} color={C.down} />
            </Stack>
            <Typography sx={{ fontSize: 12.5, color: C.muted, mt: 0.75, lineHeight: 1.75 }}>{r.mech}</Typography>
          </Box>
        ))}
      </Stack>
      {p.rest && <Box sx={{ mt: 1 }}><MarkdownText md={p.rest} /></Box>}
    </>
  );
}

/**
 * 若…则 的结果着色:利多=红,利空=绿。
 * 两类词同时出现(如「缩量锁筹续板,但高度孤立、持续性存疑」)判中性 —— 那是带保留的结论,
 * 按先命中的词上色会把它涂成纯利多,误导。
 */
function thenColor(t: string): string {
  const up = /(延续|成立|升级|续板|加速|走强|新高|突破)/.test(t);
  const down = /(见顶|放弃|回落|坍塌|失败|退潮|下降|转差|崩|不参与|存疑|孤立)/.test(t);
  if (up === down) return C.text;
  return up ? C.up : C.down;
}

/** 四、周期与明日核心矛盾:周期定位芯片 + 每票的 if/则 分支表。 */
function Scenarios({ body }: { body: string }) {
  const p = parseScenarios(body);
  if (!p) return <MarkdownText md={body} />;
  return (
    <>
      {p.phase && (
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }} flexWrap="wrap" useFlexGap>
          <Typography sx={{ fontSize: 12, color: C.dim }}>周期定位</Typography>
          <Pill solid color={C.warn} size={13}>
            {p.phase}
          </Pill>
          {/* 规则初判被 agent 修正过的话,把修正过程摊出来,别塞进芯片(会溢出) */}
          {p.phaseNote && <Typography sx={{ fontSize: 11.5, color: C.dim }}>{p.phaseNote}</Typography>}
        </Stack>
      )}
      {p.phaseWhy && (
        <Typography sx={{ fontSize: 12.5, color: C.muted, mb: 1.25, lineHeight: 1.8 }}>{p.phaseWhy}</Typography>
      )}
      <Stack spacing={1}>
        {p.blocks.map((b, i) => (
          <Box key={i} sx={{ border: `1px solid ${C.line}`, borderRadius: 1, overflow: "hidden" }}>
            <Box sx={{ bgcolor: C.panel, px: 1.5, py: 0.75 }}>
              <Typography sx={{ fontSize: 14, fontWeight: 700, color: C.text }}>{b.title}</Typography>
            </Box>
            {b.rows.map((r, j) => (
              <Stack
                key={j}
                direction={{ xs: "column", sm: "row" }}
                spacing={{ xs: 0.25, sm: 1 }}
                sx={{ px: 1.5, py: 0.85, borderTop: `1px solid ${C.line}` }}
                alignItems={{ xs: "flex-start", sm: "baseline" }}
              >
                <Typography sx={{ fontSize: 12.5, color: C.muted, flex: 1.15, lineHeight: 1.7 }}>
                  <Box component="span" sx={{ color: C.dim, mr: 0.5 }}>
                    若
                  </Box>
                  {r.cond}
                </Typography>
                <Box component="span" sx={{ color: C.dim, fontSize: 12, display: { xs: "none", sm: "block" } }}>
                  →
                </Box>
                <Typography
                  sx={{ fontSize: 12.5, fontWeight: 600, color: thenColor(r.then), flex: 1, lineHeight: 1.7 }}
                >
                  {r.then}
                </Typography>
              </Stack>
            ))}
          </Box>
        ))}
      </Stack>
      {p.rest && <Box sx={{ mt: 1 }}><MarkdownText md={p.rest} /></Box>}
    </>
  );
}

/** 五、四风格候选票:一风格一块,票名 + 分级读数 + 触发/放弃/逻辑。 */
function Picks({ body }: { body: string }) {
  const p = parsePicks(body);
  if (!p) return <MarkdownText md={body} />;
  const gradeColor = (m: string) => (/^A/.test(m) ? C.up : /^B/.test(m) ? C.warn : /^[CD]/.test(m) ? C.dim : C.muted);
  return (
    <>
      <Stack spacing={1}>
        {p.groups.map((g, i) => (
          <Box key={i} sx={{ border: `1px solid ${C.line}`, borderRadius: 1, overflow: "hidden" }}>
            <Box sx={{ bgcolor: C.panel, px: 1.5, py: 0.75 }}>
              <Typography sx={{ fontSize: 13, fontWeight: 700, color: C.blue }}>{g.style}</Typography>
            </Box>
            {g.rows.map((r) => (
              <Box key={r.code} sx={{ px: 1.5, py: 1, borderTop: `1px solid ${C.line}` }}>
                <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
                  <Typography sx={{ fontSize: 14.5, fontWeight: 700, color: C.text }}>{r.name}</Typography>
                  <Typography sx={{ fontSize: 11.5, color: C.dim }}>{r.code}</Typography>
                  {r.meta.split(/[,，]/).map((m) => {
                    const t = m.trim();
                    return t ? (
                      <Pill key={t} color={gradeColor(t)}>
                        {t}
                      </Pill>
                    ) : null;
                  })}
                </Stack>
                <Stack direction="row" spacing={0.75} sx={{ mt: 0.6 }} flexWrap="wrap" useFlexGap>
                  <Pill solid color={C.up}>触发</Pill>
                  <Typography sx={{ fontSize: 12.5, color: C.text, lineHeight: 1.75 }}>{r.trigger}</Typography>
                </Stack>
                <Stack direction="row" spacing={0.75} sx={{ mt: 0.4 }} flexWrap="wrap" useFlexGap>
                  <Pill solid color={C.down}>放弃</Pill>
                  <Typography sx={{ fontSize: 12.5, color: C.text, lineHeight: 1.75 }}>{r.giveup}</Typography>
                </Stack>
                <Typography sx={{ fontSize: 12, color: C.muted, mt: 0.4, lineHeight: 1.75 }}>{r.reason}</Typography>
              </Box>
            ))}
            {g.note && (
              <Typography
                sx={{ fontSize: 12.5, color: C.muted, px: 1.5, py: 1, borderTop: `1px solid ${C.line}`, lineHeight: 1.75 }}
              >
                {g.note}
              </Typography>
            )}
          </Box>
        ))}
      </Stack>
      {p.rest && <Box sx={{ mt: 1 }}><MarkdownText md={p.rest} /></Box>}
    </>
  );
}

const BY_NUM: Record<string, (p: { body: string }) => ReactNode> = {
  一: Directions,
  二: Profiles,
  三: Clashes,
  四: Scenarios,
  五: Picks,
};

/**
 * 复盘正文的结构化视图 —— 把五段模板还原成图示,认不出的段/行原样回退 markdown。
 * 解析规则与实测格式变体见 utils/reportParse.ts 的头注。
 */
export default function ReportStructured({ md }: { md: string }) {
  const { preamble, sections } = splitSections(md);
  const basis = parseBasis(preamble);
  // 数据基础提成芯片后,preamble 剩下的是工具门禁自检行。
  // 注意 agent 把两者写在**同一行**(`我先依次拉取…。> 数据基础:…`),
  // 所以只能切掉「数据基础」那一截,按行过滤会把自检行一起吞掉。
  const selfCheck = preamble
    .replace(/>?\s*数据基础[:：][^\n]*/g, "")
    .replace(/[`*>]/g, "")
    .trim();

  return (
    <Box>
      {basis.length > 0 && (
        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
          {basis.map((b) => (
            <Pill key={b} color={C.blue} size={12}>
              {b}
            </Pill>
          ))}
        </Stack>
      )}
      {selfCheck && (
        <Typography sx={{ fontSize: 11.5, color: C.dim, mt: basis.length ? 0.75 : 0 }}>{selfCheck}</Typography>
      )}
      {!basis.length && !selfCheck && preamble && <MarkdownText md={preamble} />}

      {sections.map((s, i) => {
        const R = BY_NUM[s.num];
        return (
          <Section key={i} num={s.num} title={s.title}>
            {R ? <R body={s.body} /> : <MarkdownText md={s.body} />}
          </Section>
        );
      })}
    </Box>
  );
}
