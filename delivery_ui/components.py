from __future__ import annotations

import html
from typing import Any, Dict, Iterable, List, Optional

ICONS: Dict[str, str] = {
    "home": '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v9.5h13V10"/><path d="M10 19.5v-5h4v5"/>',
    "card": '<rect x="3" y="5.5" width="18" height="13" rx="2"/><path d="M3 10h18"/><path d="M6.5 15h4"/>',
    "file": '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/><path d="M9.5 12h5M9.5 15.5h5"/>',
    "shield": '<path d="M12 3 4.5 6v5.5c0 4.4 3.1 8 7.5 9.5 4.4-1.5 7.5-5.1 7.5-9.5V6z"/><path d="m9 12 2.2 2.2L15.5 10"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    "upload": '<path d="M12 16V5"/><path d="m7.5 9.5 4.5-4.5 4.5 4.5"/><path d="M5 17v2.5h14V17"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12.3 2.8 2.8L16.2 9.5"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5"/><circle cx="12" cy="16.3" r=".6" fill="currentColor"/>',
    "x": '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.6a2.5 2.5 0 1 1 3.6 2.2c-.8.4-1.2 1-1.2 1.8"/><circle cx="12" cy="16.8" r=".6" fill="currentColor"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><circle cx="12" cy="7.8" r=".6" fill="currentColor"/>',
    "review": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 2"/>',
    "person": '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5"/>',
    "mail": '<rect x="3" y="5.5" width="18" height="13" rx="2"/><path d="m4 7.5 8 6 8-6"/>',
    "truck": '<path d="M3 7h11v9H3z"/><path d="M14 10h4l3 3v3h-7"/><circle cx="7.5" cy="17" r="1.8"/><circle cx="17" cy="17" r="1.8"/>',
    "chat": '<path d="M4 5.5h16v10H9.5L5.5 19v-3.5H4z"/>',
    "dash": '<circle cx="12" cy="12" r="9"/><path d="M8.5 12h7"/>',
    "back": '<path d="M19 12H5"/><path d="m11 6-6 6 6 6"/>',
    "chev": '<path d="m9 6 6 6-6 6"/>',
    "down": '<path d="m6 9 6 6 6-6"/>',
    "copy": '<rect x="8" y="8" width="11" height="12" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "bolt": '<path d="M13 3 5 13.5h6L10 21l8-10.5h-6z"/>',
    "doc-up": '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/><path d="M12 17v-5"/><path d="m9.7 14.2 2.3-2.3 2.3 2.3"/>',
    "list": '<path d="M8 6.5h12M8 12h12M8 17.5h12"/><circle cx="4.5" cy="6.5" r=".8"/><circle cx="4.5" cy="12" r=".8"/><circle cx="4.5" cy="17.5" r=".8"/>',
    "branch": '<circle cx="6" cy="6" r="2.2"/><circle cx="6" cy="18" r="2.2"/><circle cx="18" cy="9" r="2.2"/><path d="M6 8.2v7.6"/><path d="M18 11.2c0 3.5-4 3-9.5 5.6"/>',
    "lock": '<rect x="5.5" y="10.5" width="13" height="9" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
}


def esc(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def icon(name: str, size: int = 18, cls: str = "") -> str:
    body = ICONS.get(name, ICONS["info"])
    return (f'<svg class="svg {esc(cls)}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{body}</svg>')


def tone_icon(name: str, tone: str, size: int = 18) -> str:
    return f'<span class="tico tone-{esc(tone)}">{icon(name, size)}</span>'


def chip(label: str, tone: str = "slate", icon_name: Optional[str] = None, cls: str = "") -> str:
    ic = icon(icon_name, 14) if icon_name else ""
    return f'<span class="chip tone-{esc(tone)} {esc(cls)}">{ic}<span>{esc(label)}</span></span>'


def source_chip(kind_map: Dict[str, Dict[str, str]], kind: str) -> str:
    k = kind_map[kind]
    return f'<span class="chip src tone-{esc(k["tone"])}" data-source="{esc(kind)}">{esc(k["label"])}</span>'


def button(label: str, href: Optional[str] = None, kind: str = "primary", icon_name: Optional[str] = None, **attrs: str) -> str:
    ic = icon(icon_name, 16) if icon_name else ""
    extra = "".join(f' {esc(k.replace("_", "-"))}="{esc(v)}"' for k, v in attrs.items())
    if href is not None:
        return f'<a class="btn btn-{esc(kind)}" href="{esc(href)}"{extra}>{ic}<span>{esc(label)}</span></a>'
    return f'<button type="submit" class="btn btn-{esc(kind)}"{extra}>{ic}<span>{esc(label)}</span></button>'


def logo(size: int = 34) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 40 40" aria-hidden="true"><path d="M20 3 34.5 11.5v17L20 37 5.5 28.5v-17z" fill="#087F8C"/>'
            '<path d="M20 11 28 15.7v8.6L20 29l-8-4.7v-8.6z" fill="none" stroke="#fff" stroke-width="2.2" stroke-linejoin="round"/>'
            '<path d="M16 20.2 19 23l5.2-5.6" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def highlighted_text(text: str, facts: Iterable[Dict[str, Any]]) -> str:
    """Escape `text` and wrap exact fact spans in <mark>. Invariant (tested): removing the tags and unescaping gives back `text` unchanged."""
    spans = [f for f in facts if isinstance(f.get("span_start"), int) and 0 <= f["span_start"] < f["span_end"] <= len(text)]
    cuts = sorted({0, len(text)} | {x for f in spans for x in (f["span_start"], f["span_end"])})
    out: List[str] = []
    for a, b in zip(cuts, cuts[1:]):
        seg = text[a:b]
        hit = [f for f in spans if f["span_start"] <= a and f["span_end"] >= b]
        if not hit:
            out.append(esc(seg))
            continue
        ids = " ".join(f["fact_id"] for f in hit)
        tone = "amber" if any(f["state"] == "unreviewed" for f in hit) else ("green" if any(f["state"] == "carrier_reviewed" for f in hit) else "slate")
        out.append(f'<mark class="hl hl-{tone}" data-facts="{esc(ids)}">{esc(seg)}</mark>')
    return "".join(out)
