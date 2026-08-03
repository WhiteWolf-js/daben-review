import { useCallback, useEffect, useRef, useState } from "react";
import { getReport, streamSSE, type UsageCost } from "../api";

/**
 * 当日复盘状态(markdown / 生成中 / 本次成本)+ 生成动作。
 *
 * 提成 hook 的原因:盘后视图里「决策区(核心矛盾摘要+按钮)」与「折叠区(完整正文)」是两个组件,
 * 若各自持有状态就会重复请求、且在一处点「生成」另一处不刷新。由父级调一次、往下传。
 */
export function useReport(date: string, onGenerated?: () => void) {
  const [md, setMd] = useState("");
  const [createdAt, setCreatedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [usage, setUsage] = useState<UsageCost | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    abortRef.current?.abort();
    setMd("");
    setCreatedAt(null);
    if (!date) return;
    getReport(date)
      .then((r) => {
        setMd(r.markdown);
        setCreatedAt(r.created_at);
      })
      .catch(() => {}); // 404 = 该日尚未生成
    return () => abortRef.current?.abort();
  }, [date]);

  const generate = useCallback(() => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setMd("");
    setCreatedAt(null);
    setUsage(null);
    setLoading(true);
    streamSSE(
      "/api/generate",
      { date },
      (t) => setMd((p) => p + t),
      (u) => {
        setLoading(false);
        if (u) setUsage(u);
        onGenerated?.(); // 复盘存库(含候选)后通知刷新候选表 + 当日成本
      },
      ctrl.signal,
    ).catch(() => setLoading(false));
  }, [date, onGenerated]);

  return { md, createdAt, loading, usage, generate };
}
