import { useEffect, useRef, useState, type ReactNode } from "react";
import { Box, Stack, Tab, Tabs } from "@mui/material";

const TOOLBAR_H = 48; // AppBar variant="dense" 的高度
const NAV_H = 40;
/** 锚点跳转后 section 顶部要让出的距离(AppBar + 本条 nav + 一点呼吸) */
const ANCHOR_OFFSET = TOOLBAR_H + NAV_H + 8;
/** scrollspy 判定线:视口内越过这条线的最后一段即当前段 */
const SPY_LINE = TOOLBAR_H + NAV_H + 12;

export type PageSection = {
  id: string;
  label: string; // tab 上的短名(section 自己的标题由内容面板出)
  content: ReactNode;
};

/**
 * 分段页:顶部信息区 + 吸顶锚点导航 + 下方 section 平铺。
 *
 * 替代早期的 FoldCard 折叠流 —— 信息不再靠折叠收纳,而是靠"顶部常显 + 锚点跳转"。
 * 各 section **直接挂载**(面板 mount 即自拉数据),换来滚动即见,代价是首屏并发请求变多。
 * 内容面板多数自带 Card + 标题,故这里只负责锚点与间距,不再套壳(裸内容用 PanelCard 包)。
 */
export default function SectionedPage({
  header,
  sections,
}: {
  header?: ReactNode; // 常显信息区,随页面滚走(底部间距由调用方自己给)
  sections: PageSection[];
}) {
  const [active, setActive] = useState("");
  const lockUntil = useRef(0); // 点 tab 后的平滑滚动期内不让 scrollspy 抢回去
  const ids = sections.map((s) => s.id).join(",");

  useEffect(() => {
    const list = ids ? ids.split(",") : [];
    if (!list.length) return;

    const pick = () => {
      if (performance.now() < lockUntil.current) return;
      let cur = list[0];
      for (const id of list) {
        const el = document.getElementById(`sec-${id}`);
        if (el && el.getBoundingClientRect().top <= SPY_LINE) cur = id;
      }
      // 触底强制末段:最后一段太短时永远越不过判定线。
      // 必须先确认页面真能滚 —— 首屏数据没到齐时页面不足一屏,否则会误判成"已触底"停在末段。
      const doc = document.documentElement;
      const scrollable = doc.scrollHeight > window.innerHeight + 8;
      if (scrollable && window.innerHeight + window.scrollY >= doc.scrollHeight - 4) {
        cur = list[list.length - 1];
      }
      setActive(cur);
    };

    pick();
    window.addEventListener("scroll", pick, { passive: true });
    window.addEventListener("resize", pick);
    // 各面板 mount 后自拉数据,高度会持续变;不重算的话高亮会卡在初始值
    const ro = new ResizeObserver(pick);
    ro.observe(document.body);
    return () => {
      window.removeEventListener("scroll", pick);
      window.removeEventListener("resize", pick);
      ro.disconnect();
    };
  }, [ids]);

  const go = (id: string) => {
    lockUntil.current = performance.now() + 800;
    setActive(id);
    document.getElementById(`sec-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // 数据未到齐时 section 会增减,active 可能指向已消失的段
  const value = sections.some((s) => s.id === active) ? active : sections[0]?.id ?? false;

  return (
    <>
      {header}

      {sections.length > 1 && (
        <Box
          sx={{
            position: "sticky",
            top: `${TOOLBAR_H}px`,
            zIndex: (t) => t.zIndex.appBar - 1,
            bgcolor: "background.default",
            borderBottom: "1px solid",
            borderColor: "divider",
            mb: 2,
          }}
        >
          <Tabs
            value={value}
            onChange={(_, v) => go(v)}
            variant="scrollable"
            scrollButtons="auto"
            sx={{ minHeight: NAV_H, "& .MuiTabs-flexContainer": { gap: 0.5 } }}
          >
            {sections.map((s) => (
              <Tab key={s.id} value={s.id} label={s.label} sx={{ minHeight: NAV_H, py: 0, px: 1.5 }} />
            ))}
          </Tabs>
        </Box>
      )}

      <Stack spacing={2}>
        {sections.map((s) => (
          <Box key={s.id} id={`sec-${s.id}`} sx={{ scrollMarginTop: `${ANCHOR_OFFSET}px` }}>
            {s.content}
          </Box>
        ))}
      </Stack>
    </>
  );
}
