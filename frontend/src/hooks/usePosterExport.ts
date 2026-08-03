import { useCallback, useRef, useState } from "react";

/**
 * 把一个 DOM 节点导成 PNG 下载(复盘海报 / 天梯图共用)。
 *
 * 注意:**不要对目标节点用 transform/zoom 缩放** —— html-to-image 会测到缩放后的尺寸,
 * 导出图会变小。预览要按原始宽度渲染,靠容器滚动,别缩放节点本身。
 */
export function usePosterExport(filename: string, pixelRatio = 2) {
  const ref = useRef<HTMLDivElement>(null);
  const [exporting, setExporting] = useState(false);

  const download = useCallback(async () => {
    const node = ref.current;
    if (!node) return;
    setExporting(true);
    try {
      const { toPng } = await import("html-to-image"); // 按需加载,不进主 bundle
      // 海报/天梯图用 2(要清晰);整篇复盘正文是长图,2 倍会到几十 MB,调用方传 1.5
      const url = await toPng(node, { pixelRatio, backgroundColor: "#0d1117" });
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
    } catch (e) {
      console.error("导出图片失败", e);
    } finally {
      setExporting(false);
    }
  }, [filename, pixelRatio]);

  return { ref, exporting, download };
}
