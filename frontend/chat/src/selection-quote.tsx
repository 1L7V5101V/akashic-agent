import { Quote } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

const POINTER_FINE = "(hover: hover) and (pointer: fine)";
const MESSAGE = ".web-message-anchor";
const BUTTON_GAP = 8;
const BUTTON_HEIGHT = 28;
// 浮动标题条之下才算可见阅读区。
const TOP_CHROME = 64;

type Anchor = { left: number; top: number; below: boolean };

// 在一条消息里选中一段文字后，选区上方浮出"引用"：把选中内容作为 Markdown 引用块接到草稿后面，针对一句追问。
// 只在鼠标等精细指针下出现；触屏有系统自带的选择菜单，不再叠一层。整条引用仍走消息操作行的"引用此消息"。
export function SelectionQuote({ onQuote }: { onQuote: (markdown: string) => void }) {
  const [anchor, setAnchor] = useState<Anchor | null>(null);

  // 必要 effect：选区与滚动都是 document 级事件，只能在这里订阅。
  useEffect(() => {
    if (!window.matchMedia(POINTER_FINE).matches) return;
    const measure = () => {
      const range = selectedRange();
      setAnchor(range ? placeAbove(range) : null);
    };
    const hide = () => setAnchor(null);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") hide();
      else if (event.shiftKey) measure();
    };
    // 高亮代码在 shadow DOM 里，document 侧的选区会被折叠成宿主外的一点：按文字是否为空判断，而不是 isCollapsed。
    const onSelectionChange = () => {
      if (!window.getSelection()?.toString().trim()) hide();
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

// 取当前选区：有文字、起止在同一条消息里、不在可编辑区域。高亮代码的选区要带上 shadow root 才取得到真实端点。
function selectedRange(): Range | null {
  const selection = window.getSelection();
  if (!selection?.rangeCount || !selection.toString().trim()) return null;
  // 1. 普通 DOM 直接用；端点被折叠到宿主外时，改从 composed range 还原 shadow 里的端点。
  let range: Range | null = selection.getRangeAt(0);
  if (range.collapsed && typeof selection.getComposedRanges === "function") {
    const shadowRoots = [...document.querySelectorAll("diffs-container")].flatMap((host) => host.shadowRoot ? [host.shadowRoot] : []);
    const [composed] = selection.getComposedRanges({ shadowRoots });
    range = composed ? toRange(composed) : null;
  }
  if (!range || range.collapsed) return null;
  // 2. 起止都要落在同一条消息里（越过 shadow 边界向上找），且不在输入框里。
  const start = closestComposed(range.startContainer, MESSAGE);
  if (!start || start !== closestComposed(range.endContainer, MESSAGE)) return null;
  if (closestComposed(range.startContainer, "input, textarea, [contenteditable]")) return null;
  return range;
}

// 按钮落在选区可见部分：优先首个可见行的上方；放不下就放到末个可见行下方；仍放不下时压回可见区。
function placeAbove(range: Range): Anchor | null {
  const bottomEdge = window.innerHeight - BUTTON_GAP;
  const lines = [...range.getClientRects()].filter((rect) => rect.width > 0 && rect.bottom > TOP_CHROME && rect.top < bottomEdge);
  const first = lines[0];
  const last = lines.at(-1);
  if (!first || !last) return null;
  const clampX = (rect: DOMRect) => Math.min(Math.max(rect.left + rect.width / 2, 48), window.innerWidth - 48);
  if (first.top - BUTTON_GAP - BUTTON_HEIGHT >= TOP_CHROME) {
    return { left: clampX(first), top: first.top - BUTTON_GAP, below: false };
  }
  const below = Math.min(last.bottom + BUTTON_GAP, bottomEdge - BUTTON_HEIGHT);
  return { left: clampX(last), top: Math.max(below, TOP_CHROME), below: true };
}

function toRange(staticRange: StaticRange): Range | null {
  try {
    const range = document.createRange();
    range.setStart(staticRange.startContainer, staticRange.startOffset);
    range.setEnd(staticRange.endContainer, staticRange.endOffset);
    return range;
  } catch {
    // 起止跨在不同的树里（一端在 shadow 内、一端在外），这种选区不算单条消息内的引用。
    return null;
  }
}

function closestComposed(node: Node, selector: string): Element | null {
  let element: Element | null = node instanceof Element ? node : node.parentElement;
  while (element) {
    const hit = element.closest(selector);
    if (hit) return hit;
    const root = element.getRootNode();
    element = root instanceof ShadowRoot ? root.host : null;
  }
  return null;
}
