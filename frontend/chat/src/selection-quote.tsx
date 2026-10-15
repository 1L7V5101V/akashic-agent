import { Quote } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

const POINTER_FINE = "(hover: hover) and (pointer: fine)";
const MESSAGE = ".web-message-anchor";
const BUTTON_GAP = 8;

type Anchor = { left: number; top: number; below: boolean };

// 在一条消息里选中一段文字后，选区上方浮出"引用"：把选中内容作为 Markdown 引用块接到草稿后面，针对一句追问。
// 只在鼠标等精细指针下出现；触屏有系统自带的选择菜单，不再叠一层。整条引用仍走消息操作行的"引用此消息"。
export function SelectionQuote({ onQuote }: { onQuote: (markdown: string) => void }) {
  const [anchor, setAnchor] = useState<Anchor | null>(null);

  // 必要 effect：选区与滚动都是 document 级事件，只能在这里订阅。
  useEffect(() => {
    if (!window.matchMedia(POINTER_FINE).matches) return;
    // 1. 选区落在同一条消息、且不在可编辑区域里才算数。
    const measure = () => {
      const selection = window.getSelection();
      const range = selection && !selection.isCollapsed && selection.rangeCount ? selection.getRangeAt(0) : null;
      const start = range ? elementOf(range.startContainer)?.closest(MESSAGE) : null;
      const end = range ? elementOf(range.endContainer)?.closest(MESSAGE) : null;
      if (!range || !start || start !== end || !selection?.toString().trim()
        || elementOf(range.startContainer)?.closest("input, textarea, [contenteditable]")) {
        setAnchor(null);
        return;
      }
      // 2. 默认放在选区上方居中；贴近顶栏时改放到选区下方。
      const rect = range.getBoundingClientRect();
      const below = rect.top < 96;
      setAnchor({
        left: Math.min(Math.max(rect.left + rect.width / 2, 48), window.innerWidth - 48),
        top: below ? rect.bottom + BUTTON_GAP : rect.top - BUTTON_GAP,
        below,
      });
    };
    const hide = () => setAnchor(null);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") hide();
      else if (event.shiftKey) measure();
    };
    const onSelectionChange = () => {
      if (window.getSelection()?.isCollapsed) hide();
    };
    document.addEventListener("mouseup", measure);
    document.addEventListener("keyup", onKey);
    document.addEventListener("selectionchange", onSelectionChange);
    document.addEventListener("scroll", hide, { capture: true, passive: true });
    window.addEventListener("resize", hide);
    return () => {
      document.removeEventListener("mouseup", measure);
      document.removeEventListener("keyup", onKey);
      document.removeEventListener("selectionchange", onSelectionChange);
      document.removeEventListener("scroll", hide, { capture: true });
      window.removeEventListener("resize", hide);
    };
  }, []);

  if (!anchor) return null;
  return createPortal(<button type="button" className={`selection-quote${anchor.below ? " is-below" : ""}`}
    style={{ left: anchor.left, top: anchor.top }}
    // 按下时不能让按钮抢走焦点、清掉选区，否则点击时已经读不到选中的文字。
    onMouseDown={(event) => event.preventDefault()}
    onClick={() => {
      const text = window.getSelection()?.toString().trim() ?? "";
      setAnchor(null);
      if (!text) return;
      window.getSelection()?.removeAllRanges();
      onQuote(`${text.split(/\r?\n/u).map((line) => `> ${line}`.trimEnd()).join("\n")}\n\n`);
    }}>
    <Quote size={14} aria-hidden="true" />
    <span>引用</span>
  </button>, document.body);
}

function elementOf(node: Node): Element | null {
  return node instanceof Element ? node : node.parentElement;
}
