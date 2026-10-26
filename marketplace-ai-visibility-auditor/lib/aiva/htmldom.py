"""A tiny, dependency-free HTML DOM.

Just enough tree to answer the questions an AI-visibility audit asks:
"is this fact present as plain text a machine can read?", "what does the
markup actually declare?", "is the visible content assembled by JavaScript?"

Deliberately tolerant: real marketplace HTML is malformed, and a parser that
throws is a parser that produces no evidence.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Dict, Iterable, Iterator, List, Optional

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}

# Tags that implicitly close a still-open sibling of the same/related type.
IMPLICIT_CLOSERS = {
    "li": {"li"},
    "p": {"p"},
    "dt": {"dt", "dd"},
    "dd": {"dt", "dd"},
    "option": {"option"},
    "optgroup": {"option", "optgroup"},
    "tr": {"td", "th", "tr"},
    "td": {"td", "th"},
    "th": {"td", "th"},
    "thead": {"td", "th", "tr"},
    "tbody": {"td", "th", "tr", "thead"},
    "tfoot": {"td", "th", "tr", "tbody"},
}

#: Elements whose text is markup/metadata, not human-visible page copy.
NON_CONTENT_TAGS = {"script", "style", "noscript", "template", "svg", "head"}

BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "div", "dl", "dt", "dd",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre",
    "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "text", "is_text", "_depth")

    def __init__(self, tag: Optional[str] = None, attrs: Optional[Dict[str, str]] = None,
                 text: str = "", is_text: bool = False) -> None:
        self.tag = tag
        self.attrs: Dict[str, str] = attrs or {}
        self.children: List["Node"] = []
        self.parent: Optional["Node"] = None
        self.text = text
        self.is_text = is_text
        self._depth = 0

    # -- tree --------------------------------------------------------------
    def append(self, child: "Node") -> None:
        child.parent = self
        child._depth = self._depth + 1
        self.children.append(child)

    def walk(self) -> Iterator["Node"]:
        stack = list(reversed(self.children))
        while stack:
            node = stack.pop()
            yield node
            if node.children:
                stack.extend(reversed(node.children))

    # -- queries -----------------------------------------------------------
    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name.lower(), default)

    def has_attr(self, name: str) -> bool:
        return name.lower() in self.attrs

    def find_all(self, tag: Optional[str] = None, attrs: Optional[Dict[str, str]] = None,
                 limit: Optional[int] = None) -> List["Node"]:
        wanted = {tag} if isinstance(tag, str) else (set(tag) if tag else None)
        out: List["Node"] = []
        for node in self.walk():
            if node.is_text:
                continue
            if wanted and node.tag not in wanted:
                continue
            if attrs:
                ok = True
                for key, value in attrs.items():
                    actual = node.attrs.get(key.lower())
                    if actual is None:
                        ok = False
                        break
                    if value is not None and value is not True:
                        if key.lower() == "class":
                            if value.lower() not in actual.lower().split():
                                ok = False
                                break
                        elif actual.strip().lower() != str(value).strip().lower():
                            ok = False
                            break
                if not ok:
                    continue
            out.append(node)
            if limit and len(out) >= limit:
                break
        return out

    def find(self, tag: Optional[str] = None,
             attrs: Optional[Dict[str, str]] = None) -> Optional["Node"]:
        found = self.find_all(tag, attrs, limit=1)
        return found[0] if found else None

    def ancestors(self) -> Iterator["Node"]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def has_ancestor(self, tags: Iterable[str]) -> bool:
        wanted = set(tags)
        return any(a.tag in wanted for a in self.ancestors())

    # -- text --------------------------------------------------------------
    def get_text(self, separator: str = " ", skip_non_content: bool = True) -> str:
        parts: List[str] = []
        for node in self.walk():
            if not node.is_text:
                continue
            if skip_non_content and node.has_ancestor(NON_CONTENT_TAGS):
                continue
            value = node.text.strip()
            if value:
                parts.append(value)
        return separator.join(parts)

    def get_block_text(self) -> str:
        """Text with block-level boundaries preserved as newlines."""
        parts: List[str] = []
        for node in self.walk():
            if node.is_text:
                if node.has_ancestor(NON_CONTENT_TAGS):
                    continue
                value = node.text.strip()
                if value:
                    parts.append(value)
            elif node.tag in BLOCK_TAGS:
                parts.append("\n")
        return " ".join(parts).replace(" \n ", "\n")

    @property
    def raw_text(self) -> str:
        """All descendant text including script/style bodies.

        Concatenated without a separator: html.parser can emit the body of a
        <script> in several chunks, and inserting spaces between them would
        corrupt an embedded JSON-LD payload.
        """
        return "".join(n.text for n in self.walk() if n.is_text)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        if self.is_text:
            return f"<text {self.text[:24]!r}>"
        return f"<{self.tag} {list(self.attrs)[:4]}>"


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node(tag="#document")
        self.stack: List[Node] = [self.root]
        self.comments: List[str] = []
        self.doctype: str = ""
        self.parse_errors: int = 0

    # -- helpers -----------------------------------------------------------
    @property
    def current(self) -> Node:
        return self.stack[-1]

    def _close_implicit(self, tag: str) -> None:
        closers = IMPLICIT_CLOSERS.get(tag)
        if not closers:
            return
        while len(self.stack) > 1 and self.stack[-1].tag in closers:
            self.stack.pop()

    # -- HTMLParser API ----------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        self._close_implicit(tag)
        attr_map: Dict[str, str] = {}
        for key, value in attrs:
            key = (key or "").lower()
            if key and key not in attr_map:
                attr_map[key] = value if value is not None else ""
        node = Node(tag=tag, attrs=attr_map)
        self.current.append(node)
        if tag not in VOID_ELEMENTS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        attr_map = {}
        for key, value in attrs:
            key = (key or "").lower()
            if key and key not in attr_map:
                attr_map[key] = value if value is not None else ""
        self.current.append(Node(tag=tag, attrs=attr_map))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in VOID_ELEMENTS:
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return
        self.parse_errors += 1  # stray close tag

    def handle_data(self, data):
        if data and data.strip():
            self.current.append(Node(text=data, is_text=True))

    def handle_comment(self, data):
        self.comments.append(data)

    def handle_decl(self, decl):
        self.doctype = decl

    def error(self, message):  # pragma: no cover - py<3.10 compatibility
        self.parse_errors += 1


class Document:
    """Parsed HTML document."""

    def __init__(self, root: Node, comments: List[str], doctype: str,
                 parse_errors: int, source_length: int) -> None:
        self.root = root
        self.comments = comments
        self.doctype = doctype
        self.parse_errors = parse_errors
        self.source_length = source_length

    # convenience passthroughs
    def find_all(self, *args, **kwargs) -> List[Node]:
        return self.root.find_all(*args, **kwargs)

    def find(self, *args, **kwargs) -> Optional[Node]:
        return self.root.find(*args, **kwargs)

    def get_text(self, *args, **kwargs) -> str:
        return self.root.get_text(*args, **kwargs)

    @property
    def body(self) -> Node:
        return self.find("body") or self.root

    @property
    def head(self) -> Node:
        return self.find("head") or self.root


def parse_html(text: str) -> Document:
    builder = _Builder()
    try:
        builder.feed(text or "")
        builder.close()
    except Exception:  # noqa: BLE001 - never let malformed HTML abort an audit
        builder.parse_errors += 1
    return Document(builder.root, builder.comments, builder.doctype,
                    builder.parse_errors, len(text or ""))
