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
