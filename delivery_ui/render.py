from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode

from delivery_ui.components import button, chip, esc, highlighted_text, icon, logo, source_chip, tone_icon
from delivery_ui.presenter import SOURCE_KINDS, KIND_LABELS

NAV = (("overview", "/", "home", "Overview"), ("payments", "/payments", "card", "Payments"), ("evidence", "/evidence", "file", "Evidence"), ("live", "/live", "lock", "Live sandbox"))
TABS = (("evidence", "Evidence"), ("assessment", "Assessment details"), ("whatif", "What changes?"), ("provenance", "Provenance"))
FILTERS = (("all", "All"), ("attention", "Needs attention"), ("review", "Under review"), ("ready", "Evidence ready"), ("unassessable", "Can't be assessed"))
KINDS = (("OTHER", "Other document"), ("CARRIER_EMAIL", "Carrier email"), ("TRACKING_PASTE", "Tracking page text"), ("MERCHANT_STATEMENT", "Merchant statement"),
         ("CUSTOMER_MESSAGE", "Customer message"))
POLICY_FOOTNOTE = "Delivery Gate does not guarantee Seller Protection, predict outcomes or make decisions for PayPal. PayPal makes the final decision."


def url(path: str, **params: Any) -> str:
    q = {k: v for k, v in params.items() if v not in (None, "")}
    return path + ("?" + urlencode(q) if q else "")


def pay_url(ref: str, tab: Optional[str] = None, **kw: Any) -> str:
    return url(f"/payments/{quote(ref)}", tab=tab, **kw)


# ---- shell ---------------------------------------------------------------------------------------------------------------------
def shell(title: str, active: str, body: str, q: str = "", flash: Optional[Dict[str, str]] = None) -> str:
    nav = "".join(f'<a class="nav-item{" active" if k == active else ""}" href="{h}">{icon(ic, 20)}<span>{esc(lbl)}</span></a>' for k, h, ic, lbl in NAV)
    fl = ""
    if flash and flash.get("msg"):
        lvl = flash.get("level") if flash.get("level") in ("ok", "error", "info") else "info"
        fl = f'<div class="flash flash-{lvl}" role="{"alert" if lvl == "error" else "status"}" data-testid="flash">{esc(flash["msg"])}</div>'
    pill = ('<span class="pill-fixture" title="This page shows real responses from the PayPal sandbox, not fixtures.">' + icon("lock", 14) + 'Live sandbox (not fixture)</span>' if active == "live" else
            '<span class="pill-fixture" title="All PayPal data on this page comes from fixtures, not a live PayPal account.">' + icon("lock", 14) + 'Fixture data</span>')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · Delivery Gate</title><link rel="stylesheet" href="/static/app.css"></head>
<body><div class="app">
<aside class="side"><a class="brand" href="/">{logo(36)}<span>Delivery<br>Gate</span></a>
<nav class="nav" aria-label="Main">{nav}</nav>
<div class="side-foot">{icon("shield", 26)}<div><strong>Delivery Gate</strong><small>Fixture payments; live sandbox page is separate.<br>PayPal makes the final decision.</small></div></div></aside>
<div class="main"><header class="top">
<form class="search" action="/payments" method="get" role="search">{icon("search", 18)}<input type="search" name="q" value="{esc(q)}" placeholder="Search transactions, orders or reference numbers…" aria-label="Search payments"></form>
<div class="top-right">{pill}
<span class="avatar" aria-hidden="true">DM</span><span class="who">Demo merchant</span></div></header>
<main class="content" id="content">{fl}{body}</main></div></div>
<script src="/static/app.js" defer></script></body></html>"""


def page_title(h1: str, sub: str = "", back: Optional[tuple] = None) -> str:
    b = f'<a class="back" href="{esc(back[0])}">{icon("back", 16)}<span>{esc(back[1])}</span></a>' if back else ""
    return f'<div class="page-head">{b}<h1>{esc(h1)}</h1>{f"<p class=sub>{esc(sub)}</p>" if sub else ""}</div>'


def banner(ov: Dict[str, Any], cta: str = "") -> str:
    return (f'<section class="banner tone-{esc(ov["tone"])}" data-testid="assessment-banner" data-status="{esc(ov["key"])}">'
            f'<span class="b-ico">{icon(ov["icon"], 34)}</span><div class="b-text"><small>Current assessment</small><h2>{esc(ov["label"])}</h2>'
            f'<p>{esc(ov["message"])}</p></div>{cta}</section>')


def notice_bar(d: Dict[str, Any]) -> str:
    return (f'<div class="notice" data-testid="policy-notice">{icon("info", 18)}<div><strong>PayPal makes the final decision.</strong> '
            f'{esc(d["display_notice"])}</div></div>')


# ---- payments overview ------------------------------------------------------------------------------------------------------------
def page_payments(rows: List[Dict[str, Any]], counters: Dict[str, int], flt: str, q: str, selected: Optional[Dict[str, Any]], total: int,
                  flash: Optional[Dict[str, str]] = None) -> str:
    cards = [("attention", "Needs attention", "alert", "red"), ("review", "Under review", "review", "amber"), ("ready", "Evidence ready", "check", "green"),
             ("unassessable", "Can't be assessed", "help", "slate")]
    kpi = "".join(f'<a class="kpi{" on" if flt == k else ""}" href="{url("/payments", filter=k, q=q)}" data-testid="kpi-{k}">{tone_icon(ic, tone, 30)}'
                  f'<div><span>{esc(lbl)}</span><strong>{counters[k]}</strong></div></a>' for k, lbl, ic, tone in cards)
    chips = "".join(f'<a class="fchip{" on" if flt == k else ""}" href="{url("/payments", filter=None if k == "all" else k, q=q)}">{esc(lbl)}</a>' for k, lbl in FILTERS)
    body_rows = []
    for r in rows:
        sel = selected is not None and selected["ref"] == r["ref"]
        pay = r["payment_status"]
        a = r["assessment"]
        body_rows.append(
            f'<tr class="row{" selected" if sel else ""}" data-href="{esc(url("/payments", selected=r["ref"], filter=None if flt == "all" else flt, q=q))}" data-testid="row-{esc(r["ref"])}">'
            f'<td><a class="ref" href="{esc(url("/payments", selected=r["ref"], filter=None if flt == "all" else flt, q=q))}">{esc(r["ref"])}</a></td>'
            f'<td class="nw">{esc(r["order_ref"])}</td><td class="num nw">{esc(r["amount"])}</td>'
            f'<td class="nw">{chip(pay["label"], pay["tone"], "check" if pay["tone"] == "green" else "info")}</td><td class="nw">{esc(r["dispute"])}</td>'
            f'<td><span class="pill tone-{esc("red" if a["key"] == "REQUIREMENTS_NOT_DEMONSTRATED" else a["tone"])}">{icon(a["icon"], 15)}<span>{esc(a["label"])}</span></span></td></tr>')
    table = (f'<div class="card table-card"><table class="tbl" data-testid="payments-table"><thead><tr><th>Transaction</th><th>Customer / order</th><th>Amount</th>'
             f'<th>Payment status</th><th>Dispute</th><th>Assessment</th></tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>') if rows else (
        f'<div class="card empty" data-testid="empty-payments">{icon("search", 30)}<h3>No payments match</h3><p>Nothing matches “{esc(q)}”{" in this filter" if flt != "all" else ""}. '
        f'Try a different search, or <a href="/payments">show all {total} payments</a>.</p></div>')
    panel = ""
    if selected:
        panel = _side_panel(selected, url("/payments", filter=None if flt == "all" else flt, q=q))
    body = (page_title("Payments", "Review payment evidence and assessment status") + f'<div class="kpis">{kpi}</div>'
            f'<div class="toolbar"><div class="fchips">{chips}</div><span class="count" data-testid="result-count">{len(rows)} of {total} payments</span></div>'
            f'<div class="split{" has-panel" if selected else ""}"><div>{table}</div>{panel}</div>')
    return shell("Payments", "payments", body, q=q, flash=flash)


def _side_panel(d: Dict[str, Any], close_href: str) -> str:
    ov = d["overall"]
    pay = d["paypal"]
    reqs = "".join(f'<li>{tone_icon(r["icon"], r["tone"], 20)}<span class="rl">{esc(r["title"])}</span><span class="rs tone-{esc(r["tone"])}">{esc(r["label"])}</span></li>'
                   for r in d["requirements"] if r["status"] != "NOT_APPLICABLE")
    reqs_html = f'<h4>Requirement checklist</h4><ul class="reqlist">{reqs}</ul>' if reqs else f'<p class="muted small">{esc(ov["message"])}</p>'
    ev = "".join(f'<li>{icon(e["icon"], 18)}<span class="rl">{esc(e["kind_label"])}</span><span class="rs">{esc(e["authenticity"]["label"])}</span></li>' for e in d["evidence"])
    ev_html = f'<h4>Evidence sources</h4><ul class="reqlist plain">{ev}</ul>' if ev else '<h4>Evidence sources</h4><p class="muted small">No evidence added yet.</p>'
    return (f'<aside class="card panel" data-testid="side-panel"><a class="x" href="{esc(close_href)}" aria-label="Close">×</a>'
            f'<h2>{esc(d["ref"])}</h2><div class="big">{esc(d["summary"]["amount"])}</div><div class="panel-claim">{esc(d["summary"]["dispute"])}</div>'
            f'<div class="mini-banner tone-{esc(ov["tone"])}">{icon(ov["icon"], 22)}<div><strong>{esc(ov["label"])}</strong><p>{esc(ov["message"])}</p></div></div>'
            f'{reqs_html}{ev_html}<div class="panel-actions">{button("Review evidence", f"/payments/{quote(d["ref"])}/evidence", "primary")}'
            f'{button("View assessment", pay_url(d["ref"], "assessment"), "secondary")}</div>'
            f'<p class="foot-note">{icon("info", 16)}PayPal makes the final Seller Protection decision.</p></aside>')


# ---- transaction detail --------------------------------------------------------------------------------------------------------------
def page_detail(d: Dict[str, Any], tab: str, extra: Dict[str, Any], flash: Optional[Dict[str, str]] = None) -> str:
    ref = d["ref"]
    pay = d["paypal"]
    ps = pay["payment_status"]
    head = (f'<section class="card pay-head" data-testid="payment-header"><div class="mark">{icon("card", 30)}</div>'
            f'<div class="ph"><small>Transaction reference</small><strong class="refbig">{esc(ref)}</strong><span class="muted tiny">PayPal capture {esc(pay["capture_id"])}</span></div>'
            f'<div class="ph"><small>Amount</small><strong>{esc(d["exposure"]["original"]["text"])}</strong></div>'
            f'<div class="ph"><small>Customer / order</small><strong>{esc(d["order_ref"])}</strong>'
            f'<button class="copy" type="button" data-copy="{esc(d["order_ref"])}" aria-label="Copy order reference">{icon("copy", 16)}</button></div>'
            f'<div class="ph status tone-{esc(ps["tone"])}"><small>Payment status</small><strong>{icon("check", 22) if ps["tone"] == "green" else ""}{esc(ps["label"])}</strong></div></section>')
    cta = button("View detailed assessment", pay_url(ref, "assessment"), "secondary", "chev") if tab != "assessment" else ""
    ban = banner(d["overall"], cta)
    live_tx = d.get("live_paypal")
    live_capture = live_tx.get("capture") or {} if live_tx else {}
    capture_rows = live_capture.get("captures", [])
    capture_summary = " · ".join(filter(None, [
        f"Capture status: {capture_rows[0].get('status')}" if capture_rows and capture_rows[0].get("status") else None,
        f"Amount: {capture_rows[0].get('amount', {}).get('value')} {capture_rows[0].get('amount', {}).get('currency_code')}" if capture_rows and capture_rows[0].get("amount") else None,
        f"Seller protection: {capture_rows[0].get('seller_protection', {}).get('status')}" if capture_rows and capture_rows[0].get("seller_protection", {}).get("status") else None,
    ]))
    live_panel = (f'<section class="card"><h3>Actual PayPal Sandbox transaction</h3><p>Order ID: <strong>{esc(live_tx.get("order_id"))}</strong> · Status: <strong>{esc(live_tx.get("status"))}</strong></p>'
                  f'<p>Capture ID(s): {esc(", ".join(c.get("id", "") for c in capture_rows) or "Not captured")}</p>'
                  f'<p>{esc(capture_summary or "Capture details are not available yet.")}</p>'
                  f'<details><summary>PayPal API transaction response</summary><pre>{esc(json.dumps(live_tx.get("order", {}), indent=2))}</pre></details>'
                  f'<details><summary>PayPal capture API response</summary><pre>{esc(json.dumps(live_capture.get("capture_response", {}), indent=2))}</pre></details></section>') if live_tx else ""
    scenario = ""
    if d["scenario"]["numbers"]:
        scenario = (f'<div class="scenario" data-testid="scenario-note"><span class="tag">Demo scenario {", ".join(str(n) for n in d["scenario"]["numbers"])}</span>'
                    f'<strong>{esc(d["scenario"]["title"])}.</strong> {esc(d["scenario"]["summary"])}</div>')
    info = _payment_info(d)
    tabs = "".join(f'<a class="tab{" on" if k == tab else ""}" href="{esc(pay_url(ref, k))}" data-testid="tab-{k}">{esc(lbl)}</a>' for k, lbl in TABS)
    content = {"evidence": _tab_evidence, "assessment": _tab_assessment, "whatif": _tab_whatif, "provenance": _tab_provenance}[tab](d, extra)
    right = _summary_card(d) + _next_steps_card(d)
    body = (page_title("Payment Overview", "A complete view of your payment, evidence and assessment.", ("/payments", "Back to Payments"))
            + scenario + live_panel + f'<div class="detail-grid"><div class="col-main">{head}{ban}{info}<nav class="tabs" aria-label="Sections">{tabs}</nav>'
            f'<div class="tabpane" data-testid="tabpane-{tab}">{content}</div></div><div class="col-side">{right}</div></div>')
    return shell(f"{ref} · Payment", "payments", body, flash=flash)


def _row(label: str, value: str, extra: str = "") -> str:
    return f'<div class="kv"><dt>{esc(label)}</dt><dd>{value}{extra}</dd></div>'


def _payment_info(d: Dict[str, Any]) -> str:
    p, m, ex = d["paypal"], d["merchant"], d["exposure"]
    sp = p["seller_protection"]
    if sp:
        mean = esc(sp["meaning"]) if sp["meaning"] else "PayPal returned a value that is not documented, so it is shown exactly as received."
        sp_val = (f'{esc(sp["label"])} {chip("Observed value", "navy")}<small class="hint">As reported by PayPal. It is not a Seller Protection decision.</small>'
                  f'<details class="mini"><summary>What PayPal says this means</summary><p class="small">{mean}</p>'
                  f'<p class="small muted">How this value relates to the Seller Protection policy is not established, so Delivery Gate does not use it to decide anything.</p></details>')
    else:
        sp_val = f'Not reported {chip("Unknown", "slate")}<small class="hint">PayPal did not return a Seller Protection status for this payment.</small>'
    dp = p["dispute"]
    if dp:
        route = (f'{esc(dp["channel"])}' + ("" if dp["route_known"] else f' {chip("Route unknown", "slate")}'))
        reason = esc(dp["reason"]) + ("" if dp["reason_normalised"] else f' {chip("Not matched to a claim type", "slate")}')
        disp = (_row("Dispute reason", reason) + _row("How it was filed", route, "") + _row("Stage", f'{esc(dp["stage"])}<small class="hint">Shown for information. It does not change the assessment.</small>')
                + _row("Disputed amount", esc(ex["disputed"]["text"]), f'<small class="hint">{esc(ex["disputed"]["hint"])}</small>'))
    else:
        disp = _row("Dispute", "No dispute reported")
    paypal = (f'<div class="card infobox" data-testid="paypal-info"><div class="ib-head"><h3>Payment information</h3>{source_chip(SOURCE_KINDS, "paypal")}<span class="fx">Fixture data</span></div>'
              f'<dl>{_row("Payment status", esc(p["payment_status"]["label"]), f"<small class=hint>{esc(p["payment_status"]["meaning"] or "")}</small>")}'
              f'{_row("Seller Protection status", sp_val)}{disp}'
              f'{_row("Potential seller exposure", esc(ex["potential"]["text"]), f"<small class=hint>{esc(ex["potential"]["hint"])}</small>")}</dl></div>')
    answers = "".join(_row(a["label"], esc(a["value"])) for a in m["answers"])
    addr = esc(m["address"]) if m["address"] else f'Not entered {chip("Needed to compare addresses", "amber")}'
    mer = (f'<div class="card infobox" data-testid="merchant-info"><div class="ib-head"><h3>Your information</h3>{source_chip(SOURCE_KINDS, "merchant")}</div>'
           f'<dl>{_row("Where your business is based", esc(m["country"] or "Not provided"), "<small class=hint>Entered by you. PayPal does not provide it here.</small>")}'
           f'{_row("Shipping address on your PayPal transaction details", addr, "<small class=hint>Entered by you from PayPal. The shipping address on the order is not used in its place.</small>")}'
           f'{answers}</dl><details class="edit"><summary>{icon("plus", 14)}Update what you provided</summary>{_info_form(d)}</details></div>')
    return f'<div class="info-grid">{paypal}{mer}</div>'


def _info_form(d: Dict[str, Any]) -> str:
    m = d["merchant"]
    a = m["address_fields"]
    ans = {x["key"]: x["raw"] for x in m["answers"]}

    def sel(name, opts, cur):
        o = "".join(f'<option value="{esc(v)}"{" selected" if v == cur else ""}>{esc(l)}</option>' for v, l in opts)
        return f'<select name="{name}">{o}</select>'
    return (f'<form class="form-grid" method="post" action="/payments/{quote(d["ref"])}/info" data-testid="info-form">'
            f'<label>Business country (2 letters)<input name="country" value="{esc(m["country"] or "")}" maxlength="2" pattern="[A-Za-z]{{2}}"></label>'
            f'<label>Address line 1<input name="line1" value="{esc(a.get("line1", ""))}"></label><label>City<input name="city" value="{esc(a.get("city", ""))}"></label>'
            f'<label>State / region<input name="region" value="{esc(a.get("region", ""))}"></label><label>Postal code<input name="postal_code" value="{esc(a.get("postal_code", ""))}"></label>'
            f'<label>Address country<input name="addr_country" value="{esc(a.get("country", ""))}" maxlength="2"></label>'
            f'<label>Redirected to another address?{sel("redirect_detected", [("", "Not answered"), ("false", "No redirect that I know of"), ("true", "Yes, a redirect was requested")], "" if ans["redirect_detected"] is None else str(ans["redirect_detected"]).lower())}</label>'
            f'<label>Responded to PayPal?{sel("response_to_paypal", [("", "Not answered"), ("NO_REQUEST_OUTSTANDING", "PayPal has not asked for anything"), ("RESPONDED_WITHIN_REQUESTED_TIME", "I responded within the time asked"), ("RESPONSE_LATE_OR_MISSING", "My response was late or missing")], ans["response_to_paypal"] or "")}</label>'
            f'<label>Shipped after PayPal advised not to?{sel("shipped_after_advised_not_to_release", [("", "Not answered"), ("false", "No"), ("true", "Yes")], "" if ans["shipped_after_advised_not_to_release"] is None else str(ans["shipped_after_advised_not_to_release"]).lower())}</label>'
            f'<div class="form-actions">{button("Save", None, "primary")}<span class="muted small">Your answers are recorded as statements by you. They are not corroborated.</span></div></form>')


def _summary_card(d: Dict[str, Any]) -> str:
    reqs = [r for r in d["requirements"] if r["status"] != "NOT_APPLICABLE"]
    lines = "".join(f'<li>{tone_icon(r["icon"], r["tone"], 20)}<span class="rl">{esc(r["title"])}</span><span class="rs tone-{esc(r["tone"])}">{esc(r["label"])}</span></li>' for r in reqs)
    if not lines:
        lines = f'<li class="empty-line">{esc(d["overall"]["message"])}</li>'
    ov = d["overall"]
    return (f'<section class="card side-card" data-testid="assessment-summary"><h3>Assessment summary {icon("info", 16)}</h3><ul class="reqlist">{lines}</ul>'
            f'<div class="overall tone-{esc(ov["tone"])}"><small>Overall status</small><div>{icon(ov["icon"], 30)}<strong>{esc(ov["label"])}</strong></div></div></section>')


def _next_steps_card(d: Dict[str, Any]) -> str:
    steps = "".join(f'<li class="step step-{esc(s["kind"])}">{esc(s["text"])}</li>' for s in d["next_steps"][:5]) or '<li class="step">No further steps right now.</li>'
    return (f'<section class="card side-card" data-testid="next-steps"><h3>{icon("bolt", 18)} Next steps</h3><ul class="steps">{steps}</ul>'
            f'{button("Review & update evidence", f"/payments/{quote(d["ref"])}/evidence", "primary")}</section>')


# ---- tab: evidence ----------------------------------------------------------------------------------------------------------------------
def _evidence_rows(d: Dict[str, Any]) -> str:
    out = []
    for e in d["evidence"]:
        out.append(f'<a class="ev-row" href="/payments/{quote(d["ref"])}/evidence/{quote(e["artifact_id"])}" data-testid="evidence-{esc(e["artifact_id"])}">'
                   f'<span class="evi">{icon(e["icon"], 28)}</span><span class="evt"><strong>{esc(e["kind_label"])}</strong><small>{esc(e["source_label"])} · {esc(e["artifact_id"])}'
                   f'{" · sample" if e["is_sample"] else ""}</small></span><span class="evd">{esc(e["added_at"])}</span>'
                   f'<span class="evs">{chip(e["chip"]["label"], e["chip"]["tone"], {"green": "check", "red": "x", "amber": "alert"}.get(e["chip"]["tone"]))}</span>{icon("chev", 18)}</a>')
    return "".join(out)


def _tab_evidence(d: Dict[str, Any], extra: Dict[str, Any]) -> str:
    rows = _evidence_rows(d)
    ev = (f'<section class="card"><div class="card-head"><div><h3>Evidence collected</h3><p class="muted">Documents and information on this payment.</p></div>'
          f'{button("Upload more", f"/payments/{quote(d["ref"])}/evidence", "secondary", "upload")}</div>'
          + (f'<div class="ev-list" data-testid="evidence-list">{rows}</div>' if rows else
             f'<div class="empty" data-testid="empty-evidence">{icon("file", 30)}<h4>No evidence added yet</h4><p>Add a carrier email, tracking text or a note about this order to see what it shows.</p></div>')
          + '</section>')
    return ev + _missing_card(d)


def _missing_card(d: Dict[str, Any]) -> str:
    items = []
    for c in d["contradictions"]:
        vals = "".join(f'<li><strong>{esc(v["value"])}</strong> <span class="muted">in evidence {esc(v["artifact_id"])}</span></li>' for v in c["values"])
        items.append(f'<div class="mi tone-red" data-kind="conflict">{tone_icon("x", "red", 22)}<div><strong>{esc(c["label"])}: {esc(c["message"])}</strong><ul class="inl">{vals}</ul>'
                     f'<p class="muted small">{esc(c["note"].rstrip(". "))}. Delivery Gate does not decide which record is right.</p></div></div>')
    for g in d["gates"]:
        if g["tone"] == "slate" and g["outcome"] != "Within the rules modeled":
            items.append(f'<div class="mi tone-slate" data-kind="unknown">{tone_icon("help", "slate", 22)}<div><strong>{esc(g["label"])}: {esc(g["outcome"])}</strong><p class="muted small">{esc(g["detail"])}</p></div></div>')
    for c in d["conditions"]:
        if c["unresolved"]:
            items.append(f'<div class="mi tone-slate" data-kind="unknown">{tone_icon("help", "slate", 22)}<div><strong>{esc(c["title"])}: {esc(c["outcome"])}</strong><p class="muted small">{esc(c["detail"])}</p></div></div>')
    for k in d["unknown_inputs"]:
        txt = {"transaction_details_address": "The shipping address on your PayPal transaction details has not been entered, so addresses can't be compared.",
               "route": "How the dispute was filed is not known.", "claim_category": "The type of claim is not known."}.get(k, k)
        items.append(f'<div class="mi tone-slate" data-kind="unknown">{tone_icon("help", "slate", 22)}<div><strong>Not known</strong><p class="muted small">{esc(txt)}</p></div></div>')
    for m in d["missing"]:
        items.append(f'<div class="mi tone-amber" data-kind="missing">{tone_icon("alert", "amber", 22)}<div><strong>{esc(m["title"])}</strong><p class="muted small">{esc(m["reason"])}</p></div></div>')
    for t in d["statement_only"]:
        items.append(f'<div class="mi tone-amber" data-kind="statement">{tone_icon("person", "amber", 22)}<div><strong>{esc(t)}: your statement only</strong>'
                     f'<p class="muted small">Stated by you. Nothing from a carrier backs it up, so it is not corroborated.</p></div></div>')
    inner = "".join(items) or f'<div class="mi tone-green">{tone_icon("check", "green", 22)}<div><strong>Nothing is missing or in conflict</strong><p class="muted small">Every modeled requirement is covered by the evidence on file.</p></div></div>'
    return f'<section class="card" data-testid="missing-card"><div class="card-head"><div><h3>Missing or conflicting information</h3></div></div><div class="mis">{inner}</div></section>'


# ---- tab: assessment ------------------------------------------------------------------------------------------------------------------------
def _support_li(s: Dict[str, Any]) -> str:
    span = f'<q class="span">{esc(s["span"])}</q>' if s.get("span") else ""
    amb = f' {chip("Unclear", "amber")}' if s.get("ambiguity") else ""
    return (f'<li><div class="sl-top"><strong>{esc(s["label"])}:</strong> {esc(s["value"])}{amb}</div>'
            f'<div class="sl-meta">{source_chip(SOURCE_KINDS, s["source_kind"])}<span class="muted small">Evidence {esc(s["artifact_id"])} · {esc(s["artifact_kind"])}</span>'
            f'{chip(s["authenticity"]["label"], s["authenticity"]["tone"])}</div>{span}</li>')


def _req_detail(r: Dict[str, Any]) -> str:
    sup = "".join(_support_li(s) for s in r["support"])
    mine = "".join(f'<li><strong>{esc(m["value"])}</strong> {source_chip(SOURCE_KINDS, "merchant")}</li>' for m in r["merchant_inputs"])
    ev_html = f'<ul class="sup">{sup}{mine}</ul>' if (sup or mine) else '<p class="muted">Nothing on file supports this yet.</p>'
    miss = f'<p>{esc(r["missing"])}</p><p class="muted small">{esc(r["next"])}</p>' if r["missing"] else '<p class="muted">Nothing is missing for this requirement.</p>'
    pol = "".join(f'<li><strong>{esc(p["title"])}</strong> · {esc(p["section"])}<br><span class="muted small">{esc(p["updated"] or "")} · {esc(p["review_status"])}</span></li>' for p in r["policy_sources"])
    tech = esc(json.dumps(r["details"], indent=1))
    interp = f'<p class="muted small">{esc(r["interpretation_note"])}</p>' if r["interpretation_note"] else ""
    return (f'<div class="req-grid"><div><h5>What it means</h5><p>{esc(r["means"])}</p>{interp}</div><div><h5>What supports it</h5>{ev_html}</div>'
            f'<div><h5>What is missing</h5>{miss}</div><div><h5>Policy source</h5><ul class="pol">{pol or "<li class=muted>None cited</li>"}</ul></div></div>'
            f'<details class="tech"><summary>Technical details</summary><pre>{tech}</pre></details>')


def _tab_assessment(d: Dict[str, Any], extra: Dict[str, Any]) -> str:
    gates = "".join(f'<li>{tone_icon("check" if g["tone"] == "green" else "help", g["tone"], 20)}<span class="rl"><strong>{esc(g["label"])}</strong><small>{esc(g["detail"])}</small></span>'
                    f'<span class="rs tone-{esc(g["tone"])}">{esc(g["outcome"])}</span></li>' for g in d["gates"])
    gate_tech = "".join(f'<details class="tech"><summary>Technical details: {esc(g["label"])}</summary><pre>{esc(json.dumps(g["technical"], indent=1))}</pre></details>' for g in d["gates"])
    conds = "".join(f'<li>{tone_icon("help" if c["unresolved"] else "check", c["tone"], 20)}<span class="rl"><strong>{esc(c["title"])}</strong><small>{esc(c["means"])}</small>'
                    f'<small>{esc(c["detail"])}</small></span><span class="rs tone-{esc(c["tone"])}">{esc(c["outcome"])}</span></li>' for c in d["conditions"])
    cond_tech = "".join(f'<details class="tech"><summary>Technical details: {esc(c["title"])}</summary><pre>{esc(json.dumps(c["technical"], indent=1))}</pre></details>' for c in d["conditions"])
    gates_card = f'<section class="card" data-testid="gates-card"><h3>Checked first</h3><p class="muted">Conditions that decide whether the requirements apply at all.</p><ul class="reqlist gl">{gates}{conds}</ul>{gate_tech}{cond_tech}</section>' if (gates or conds) else ""
    if d["requirements"]:
        reqs = "".join(
            f'<details class="req tone-{esc(r["tone"])}" data-testid="req-{esc(r["key"])}" data-status="{esc(r["status"])}"><summary><span class="rq-l">{tone_icon(r["icon"], r["tone"], 22)}'
            f'<span class="rq-t"><strong>{esc(r["title"])}</strong><small>{esc(r["reason"])}</small></span></span><span class="rq-r">{chip(r["label"], r["tone"])}{icon("down", 18)}</span></summary>'
            f'<div class="req-body">{_req_detail(r)}</div></details>' for r in d["requirements"])
        req_card = (f'<section class="card"><div class="card-head"><div><h3>Requirements currently modeled</h3><p class="muted">Select a requirement to see what it means, what supports it and where that comes from.</p></div>'
                    f'<button type="button" class="btn btn-secondary" data-expand-all>Expand all</button></div><div class="reqs">{reqs}</div></section>')
    else:
        reason = d["overall"]["message"]
        req_card = (f'<section class="card" data-testid="no-requirements"><h3>Requirements currently modeled</h3><p class="muted">No requirements were evaluated. {esc(reason)}</p></section>')
    unk = "".join(f'<li>{esc(u["text"])}</li>' for u in d["unknowns"])
    nm = "".join(f'<li>{esc(u["text"])}</li>' for u in d["not_modeled"])
    caveats = (f'<section class="card"><details class="plain"><summary><h3>What Delivery Gate can\'t tell you</h3></summary><ul class="bul">{unk}</ul>'
               f'<h4>Not modeled</h4><ul class="bul">{nm}</ul></details></section>') if (unk or nm) else ""
    return notice_bar(d) + gates_card + req_card + caveats + f'<p class="foot-note">{esc(POLICY_FOOTNOTE)}</p>'


# ---- tab: what changes ---------------------------------------------------------------------------------------------------------------------
def _tab_whatif(d: Dict[str, Any], extra: Dict[str, Any]) -> str:
    opts = extra.get("options", [])
    chosen = extra.get("what_if")
    err = extra.get("what_if_error")
    items = "".join(f'<li class="opt{" on" if chosen and chosen["option"]["id"] == o.option_id else ""}"><div><strong>{esc(o.label)}</strong><p class="muted small">{esc(o.detail)}</p></div>'
                    f'{button("Compare", pay_url(d["ref"], "whatif", option=o.option_id), "secondary", "branch")}</li>' for o in opts)
    head = (f'<section class="card"><div class="card-head"><div><h3>What changes?</h3><p class="muted">See how additional evidence could change the result. The engine reassesses the evidence; nothing is guessed.</p></div></div>'
            + (f'<ul class="opts" data-testid="whatif-options">{items}</ul>' if items else
               f'<div class="empty" data-testid="empty-whatif"><h4>Nothing to compare right now</h4><p>All the evidence on this payment is already reviewed, or there is no evidence to review.</p></div>') + '</section>')
    if err:
        return head + f'<div class="flash flash-error" role="alert">{esc(err)}</div>'
    if not chosen:
        return head
    cur, hyp = chosen["before"], chosen["after"]
    ch = "".join(f'<li><span class="rl">{esc(c["title"])}</span><span class="ba">{chip(c["before"]["label"], c["before"]["tone"])}<span class="arr">→</span>{chip(c["after"]["label"], c["after"]["tone"])}</span></li>' for c in chosen["changes"])
    added = "".join(f'<li>{esc(a["label"])}: <strong>{esc(a["value"])}</strong> <span class="muted small">from evidence {esc(a["artifact_id"])}</span></li>' for a in chosen["added"])
    still = "".join(f'<li>{esc(t)}</li>' for t in chosen["still_blocking"])
    verdict = "The result would change." if chosen["changed"] else "The result would not change."
    act = ""
    if chosen["option"]["kind"] == "ADD_SAMPLE":
        act = (f'<form method="post" action="/payments/{quote(d["ref"])}/evidence/sample" class="inline-form"><input type="hidden" name="sample_id" value="{esc(chosen["option"]["artifact_id"])}">'
               f'{button("Add this sample evidence to the payment", None, "primary", "plus")}</form>')
    else:
        act = button("Go to the evidence to review it", f"/payments/{quote(d['ref'])}/evidence/{quote(chosen['option']['artifact_id'])}", "primary", "chev")
    return (head + f'<section class="card whatif" data-testid="whatif-result"><div class="hypo">{icon("info", 18)}<span><strong>Hypothetical.</strong> {esc(chosen["hypothetical_notice"])}</span></div>'
            f'<h3>{esc(chosen["option"]["label"])}</h3><div class="compare"><div class="cmp tone-{esc(cur["tone"])}" data-testid="whatif-current"><small>Current assessment</small>'
            f'<div class="cmp-s">{icon(cur["icon"], 26)}<strong>{esc(cur["label"])}</strong></div></div><div class="cmp-arrow">{icon("chev", 30)}</div>'
            f'<div class="cmp tone-{esc(hyp["tone"])}" data-testid="whatif-hypothetical"><small>With additional evidence (hypothetical)</small><div class="cmp-s">{icon(hyp["icon"], 26)}<strong>{esc(hyp["label"])}</strong></div>'
            f'<p class="small">{esc(hyp["message"])}</p></div></div><p class="verdict" data-testid="whatif-verdict"><strong>{esc(verdict)}</strong> {esc(chosen["final_notice"])}</p>'
            + (f'<h4>Evidence this would add</h4><ul class="bul">{added}</ul>' if added else "")
            + (f'<h4>Requirements that change</h4><ul class="chg">{ch}</ul>' if ch else "")
            + (f'<h4>Still outstanding afterwards</h4><ul class="bul">{still}</ul>' if still else "")
            + f'<div class="card-actions">{act}</div></section>')


# ---- tab: provenance --------------------------------------------------------------------------------------------------------------------------
def _prov_items(d: Dict[str, Any]) -> List[Dict[str, Any]]:
    p, m, items = d["paypal"], d["merchant"], []
    items.append({"group": "paypal", "label": "Payment amount", "value": d["exposure"]["original"]["text"], "why": "Reported by PayPal for this payment (fixture data).",
                  "meta": f"PayPal capture {p['capture_id']}"})
    items.append({"group": "paypal", "label": "Payment status", "value": p["payment_status"]["label"], "why": p["payment_status"]["meaning"] or "", "meta": "PayPal capture status"})
    if p["seller_protection"]:
        items.append({"group": "paypal", "label": "Seller Protection status (observed)", "value": p["seller_protection"]["label"],
                      "why": "The value PayPal returned. Delivery Gate keeps it as an observed value and does not treat it as a Seller Protection decision.", "meta": "PayPal capture field"})
    if p["dispute"]:
        dp = p["dispute"]
        items.append({"group": "paypal", "label": "Dispute reason", "value": dp["reason"], "why": f"PayPal's recorded reason ({dp['reason_raw']}).", "meta": f"PayPal dispute {dp['id']}"})
        items.append({"group": "paypal", "label": "How it was filed", "value": dp["channel"], "why": "Taken from PayPal's dispute channel field only.", "meta": f"PayPal dispute {dp['id']}"})
    items.append({"group": "merchant", "label": "Where your business is based", "value": m["country"] or "Not provided", "why": "Entered by you.", "meta": "Provided by you"})
    items.append({"group": "merchant", "label": "Shipping address on your PayPal transaction details", "value": m["address"] or "Not entered", "why": "Entered by you from PayPal.", "meta": "Provided by you"})
    for a in m["answers"]:
        items.append({"group": "merchant", "label": a["label"], "value": a["value"], "why": "Your answer. It is recorded as your statement and is not corroborated.", "meta": "Provided by you"})
    for e in d["evidence"]:
        for f in e["facts"]:
            grp = {"carrier_reviewed": "reviewed", "merchant_statement": "merchant"}.get(f["state"], "extracted")
            items.append({"group": grp, "label": f["label"], "value": f["value"], "fact": f, "artifact": e})
    return items


def _tab_provenance(d: Dict[str, Any], extra: Dict[str, Any]) -> str:
    items = _prov_items(d)
    grp = extra.get("group") or "all"
    names = (("all", "All"), ("extracted", "Found in evidence"), ("reviewed", "Reviewed"), ("merchant", "Provided by you"), ("paypal", "Reported by PayPal"))
    counts = {k: sum(1 for i in items if k == "all" or i["group"] == k) for k, _ in names}
    gtabs = "".join(f'<a class="gt{" on" if grp == k else ""}" href="{esc(pay_url(d["ref"], "provenance", group=None if k == "all" else k))}" data-testid="group-{k}">{esc(l)} ({counts[k]})</a>' for k, l in names)
    rows = []
    for i in items:
        if grp != "all" and i["group"] != grp:
            continue
        if "fact" in i:
            f, e = i["fact"], i["artifact"]
            span = highlighted_text(e["text"], [f])
            why = (f'<div class="why"><h5>Why does Delivery Gate believe this?</h5><dl class="why-dl">'
                   f'{_row("Source", esc(f"Evidence {e["artifact_id"]} · {e["kind_label"]} · {e["source_label"]}"))}'
                   f'{_row("Who the text says it is from", esc(f["attribution"]), "<small class=hint>This describes the wording only. It does not show the document is genuine.</small>")}'
                   f'{_row("Source authenticity", chip(f["authenticity"]["label"], f["authenticity"]["tone"]), f"<small class=hint>{esc(f["authenticity"]["detail"])}</small>")}'
                   f'{_row("How it was stated", esc(f["modality"]))}</dl><h5>Supporting text</h5><pre class="doc small-doc">{span}</pre>'
                   + (f'<p class="muted small">{esc(f["state_note"])}</p>' if f["state_note"] else "")
                   + (f'<p class="warn small">{icon("alert", 14)} {esc(f["ambiguity_note"] or "The text is ambiguous here.")}</p>' if f["ambiguity"] else "")
                   + f'<details class="tech"><summary>Technical details</summary><pre>{esc(json.dumps(f["details"], indent=1))}</pre></details></div>')
            chipx = source_chip(SOURCE_KINDS, f["source_kind"])
            meta = f'Evidence {e["artifact_id"]}'
        else:
            why = f'<div class="why"><p>{esc(i["why"])}</p></div>'
            chipx, meta = source_chip(SOURCE_KINDS, i["group"]), i["meta"]
        rows.append(f'<details class="prov" data-group="{esc(i["group"])}"><summary><span class="pl"><strong>{esc(i["label"])}</strong><span class="pv">{esc(i["value"])}</span></span>'
                    f'<span class="pr">{chipx}<span class="muted small">{esc(meta)}</span>{icon("down", 16)}</span></summary>{why}</details>')
    ev = "".join(f'<li><time>{esc(x["at_text"])}</time><span>{esc(x["text"])}{" <em class=fx>fixture</em>" if x["fixture"] else ""}</span></li>' for x in d["events"])
    act = f'<section class="card"><h3>Activity</h3><ol class="timeline" data-testid="activity">{ev}</ol></section>'
    digest = (f'<p class="muted small">Assessment fingerprint: <code>{esc(d["digest"])}</code></p>' if d["digest"] else "")
    return (f'<section class="card"><div class="card-head"><div><h3>Evidence provenance</h3><p class="muted">See where each fact comes from. Information you provided, information from PayPal and evidence '
            f'that has been reviewed are kept apart.</p></div></div><div class="gtabs">{gtabs}</div><div class="provs" data-testid="prov-list">{"".join(rows) or "<p class=muted>Nothing in this group.</p>"}</div>{digest}</section>{act}')


# ---- evidence workspace ------------------------------------------------------------------------------------------------------------------------
def page_workspace(d: Dict[str, Any], samples: List[Dict[str, Any]], flash: Optional[Dict[str, str]], latest: Optional[str]) -> str:
    ref = d["ref"]
    kinds = "".join(f'<option value="{k}">{esc(l)}</option>' for k, l in KINDS)
    add = (f'<section class="card drop-card" data-testid="add-evidence"><form method="post" action="/payments/{quote(ref)}/evidence" id="evidence-form" enctype="application/x-www-form-urlencoded">'
           f'<div class="dropzone" id="dropzone" tabindex="0" role="button" aria-label="Drop a text file here or choose one">{icon("doc-up", 44)}<h3>Drop a text file here or <span class="link">choose a file</span></h3>'
           f'<p class="muted small">Text files only (.txt, .eml, .csv, .md). PDFs and images can\'t be read yet.</p><input type="file" id="fileinput" class="sr-only" tabindex="-1" aria-label="Choose a text file" accept=".txt,.eml,.csv,.md,.text,.log,text/plain">'
           f'<p class="filename" id="filename" data-testid="filename"></p></div>'
           f'<label class="field">Or paste the evidence<textarea name="text" id="evtext" rows="7" maxlength="20000" placeholder="Paste a tracking update, a carrier email, or a note about this order…" data-testid="evidence-text"></textarea></label>'
           f'<div class="row-fields"><label class="field">What is this?<select name="kind" id="evkind" data-testid="evidence-kind">{kinds}</select></label>'
           f'<label class="field">Source<input name="source_label" id="evsource" value="Pasted text" maxlength="80"></label></div>'
           f'<p class="muted small">You choose what type of evidence this is. The extraction step never decides that, and it can\'t make a document genuine.</p>'
           f'<div class="form-actions"><button type="submit" class="btn btn-primary" id="submit-evidence" data-testid="submit-evidence">{icon("upload", 16)}<span>Add and analyse</span></button>'
           f'<a class="btn btn-secondary" href="{esc(pay_url(ref))}">Cancel</a></div></form>'
           f'<details class="samples"><summary>{icon("list", 16)}Sample evidence library ({len(samples)})</summary><p class="muted small">Built-in demo texts that can be read without a live model.</p>'
           + "".join(f'<form method="post" action="/payments/{quote(ref)}/evidence/sample" class="sample-row"><input type="hidden" name="sample_id" value="{esc(s["id"])}">'
                     f'<span><strong>{esc(s["id"])}</strong> · {esc(s["category"])}</span><button class="btn btn-small" type="submit" data-testid="sample-{esc(s["id"])}">Add</button></form>' for s in samples)
           + '</details></section>')
    ev = next((e for e in d["evidence"] if e["artifact_id"] == latest), d["evidence"][-1] if d["evidence"] else None)
    if ev:
        steps = "".join(f'<li class="{"done" if s["done"] else "wait"}">{tone_icon("check" if s["done"] else "dash", "green" if s["done"] else "slate", 20)}<span>{esc(s["label"])}</span></li>' for s in ev["steps"])
        st = {"EXTRACTED": ("Analysis complete", f'{ev["fact_count"]} fact{"s" if ev["fact_count"] != 1 else ""} found.', "green"),
              "NO_FACTS": ("Analysis complete", "No usable facts were found in this evidence.", "slate"),
              "UNAVAILABLE": ("Not analysed", ev["extraction_message"] or "Extraction is unavailable.", "amber"),
              "FAILED": ("Analysis failed", ev["extraction_message"] or "Something went wrong.", "red")}[ev["extraction_status"]]
        prog = (f'<section class="card progress-card" data-testid="analysis-card" data-status="{esc(ev["extraction_status"])}"><div class="card-head"><h3>{icon("review", 20)} Analysis of evidence {esc(ev["artifact_id"])}</h3></div>'
                f'<p class="status-line tone-{st[2]}"><strong>{esc(st[0])}.</strong> {esc(st[1])}</p><ul class="steps-done">{steps}</ul>'
                + (f'<p class="muted small">{esc(ev["extractor_note"])}</p>' if ev["extractor_note"] else "") + '</section>')
    else:
        prog = f'<section class="card progress-card" data-testid="analysis-card" data-status="NONE"><h3>{icon("review", 20)} Analysis</h3><p class="muted">Nothing has been analysed yet. Add evidence to begin.</p></section>'
    nxt = (f'<section class="card side-card"><h3>{icon("shield", 20)} What\'s next?</h3><p class="muted small">Once evidence is added you will see:</p><ul class="ticks"><li>What each document shows</li>'
           f'<li>Missing or conflicting information</li><li>Your current assessment</li></ul>{button("View results", pay_url(ref, "assessment"), "primary")}</section>')
    facts = [(e, f) for e in d["evidence"] for f in e["facts"]]
    frows = "".join(f'<tr data-testid="fact-{esc(f["fact_id"])}"><td><strong>{esc(f["label"])}:</strong> {esc(f["value"])}</td><td><a href="/payments/{quote(ref)}/evidence/{quote(e["artifact_id"])}">{esc(e["artifact_id"])} · {esc(e["kind_label"])}</a></td>'
                    f'<td>{chip(f["authenticity"]["label"], f["authenticity"]["tone"])}</td><td>{chip("Unclear", "amber", "alert") if f["ambiguity"] else "<span class=muted>Clear</span>"}'
                    f'{chip("Conflict", "red", "x") if e["in_conflict"] and f["engine_evidence"] else ""}</td><td>{esc(f["confidence"])}</td></tr>' for e, f in facts)
    ftab = (f'<section class="card" data-testid="facts-card"><div class="card-head"><div><h3>{icon("file", 20)} Extracted facts</h3><p class="muted">What was found in your evidence.</p></div></div>'
            + (f'<table class="tbl"><thead><tr><th>Fact</th><th>Source</th><th>Review status</th><th>Ambiguity</th><th title="How sure the extraction was about reading the text. It is not used in the assessment.">Extraction confidence</th></tr></thead><tbody>{frows}</tbody></table>'
               f'<p class="muted small">Extraction confidence only describes how clearly the text was read. It is never used in the assessment.</p>' if frows else
               '<div class="empty" data-testid="empty-facts"><h4>No facts yet</h4><p>Facts appear here after evidence is analysed.</p></div>') + '</section>')
    erows = _evidence_rows(d)
    elist = (f'<section class="card"><div class="card-head"><h3>Evidence on this payment</h3></div>'
             + (f'<div class="ev-list">{erows}</div>' if erows else '<div class="empty"><h4>No evidence yet</h4></div>') + '</section>')
    body = (page_title("Add Evidence", "Upload or paste the evidence that supports this payment.", (pay_url(ref), "Back to payment"))
            + f'<div class="ws-grid"><div class="ws-left">{add}</div><div class="ws-right">{prog}</div></div>'
            + f'<div class="ws-grid2"><div>{elist}{ftab}</div><div>{nxt}</div></div>')
    return shell(f"Add evidence · {ref}", "evidence", body, flash=flash)


def page_artifact(d: Dict[str, Any], aid: str, flash: Optional[Dict[str, str]]) -> str:
    ref = d["ref"]
    e = next(x for x in d["evidence"] if x["artifact_id"] == aid)
    text = highlighted_text(e["text"], e["facts"])
    facts = []
    for f in e["facts"]:
        state = {"carrier_reviewed": chip("Reviewed carrier document", "green"), "merchant_statement": chip("Your statement", "slate"),
                 "unreviewed": chip("Not reviewed", "amber"), "rejected": chip("Rejected", "slate"), "not_used": chip("Not used", "slate"),
                 "unknown_value": chip("Unknown value", "slate"), "other_order": chip("Other order", "slate")}[f["state"]]
        rej = ""
        if f["state"] in ("unreviewed", "carrier_reviewed", "merchant_statement") and f["engine_evidence"]:
            rej = (f'<form method="post" action="/payments/{quote(ref)}/evidence/{quote(aid)}/review" class="inline-form"><input type="hidden" name="mode" value="reject_fact">'
                   f'<input type="hidden" name="fact_id" value="{esc(f["fact_id"])}"><input type="hidden" name="reviewer" class="reviewer-copy"><button class="linkbtn" type="submit">Reject this fact</button></form>')
        facts.append(f'<li class="fact" data-fact="{esc(f["fact_id"])}" data-testid="fact-{esc(f["fact_id"])}"><div class="f-top"><strong>{esc(f["label"])}:</strong> <span class="fv">{esc(f["value"])}</span> {state}'
                     f'{chip("Unclear", "amber", "alert") if f["ambiguity"] else ""}</div><div class="f-meta muted small">{esc(f["attribution"])} · {esc(f["modality"])} · extraction confidence {esc(f["confidence"])}</div>'
                     + (f'<div class="f-note small">{esc(f["ambiguity_note"])}</div>' if f["ambiguity"] and f["ambiguity_note"] else "")
                     + (f'<div class="f-note small muted">{esc(f["state_note"])}</div>' if f["state_note"] else "")
                     + f'<q class="span">{esc(f["span"])}</q>{rej}<details class="tech"><summary>Technical details</summary><pre>{esc(json.dumps(f["details"], indent=1))}</pre></details></li>')
    auth = e["authenticity"]
    history = "".join(f'<li>{esc(x["reviewer"])} · {esc(x["mode"].replace("_", " "))} · {esc(x["at_text"])}{" <em class=fx>fixture</em>" if x["fixture"] else ""}</li>' for x in e["reviews"])
    if e["can_attest"]:
        attest = (f'<button class="btn btn-primary" type="submit" name="mode" value="attest_carrier" data-testid="attest">{icon("shield", 16)}<span>I attest this is a genuine carrier document</span></button>')
    else:
        attest = f'<p class="muted small" data-testid="attest-unavailable">{icon("info", 14)} This evidence is typed as “{esc(e["kind_label"])}”, so it can\'t be recorded as a carrier document.</p>'
    review = (f'<section class="card" data-testid="review-panel"><h3>Review this evidence</h3><p class="muted small">Review is a person\'s decision. Attesting says the <em>document itself</em> is genuine, not only that the text was read correctly. '
              f'This demo has no sign-in, so the reviewer\'s name is simply recorded.</p>'
              f'<form method="post" action="/payments/{quote(ref)}/evidence/{quote(aid)}/review" id="review-form"><label class="field">Reviewer name<input name="reviewer" id="reviewer" maxlength="80" placeholder="Your name" data-testid="reviewer" required></label>'
              f'<label class="field">Note (optional)<input name="note" maxlength="200"></label><div class="review-actions">{attest}'
              f'<button class="btn btn-secondary" type="submit" name="mode" value="approve_merchant" data-testid="approve-merchant">Record as my own statement</button>'
              f'<button class="btn btn-secondary" type="submit" name="mode" value="reject_all" data-testid="reject-all">Reject these facts</button>'
              f'<button class="btn btn-ghost" type="submit" name="mode" value="undo" formnovalidate data-testid="undo-review">Undo review</button></div></form>'
              + (f'<h4>Review history</h4><ul class="bul">{history}</ul>' if history else "") + '</section>')
    stat = {"EXTRACTED": f'{e["fact_count"]} fact(s) found', "NO_FACTS": "No usable facts found", "UNAVAILABLE": "Not analysed", "FAILED": "Analysis failed"}[e["extraction_status"]]
    left = (f'<section class="card"><div class="card-head"><div><h3>Original evidence</h3><p class="muted small">Exactly as added. Highlighted text is what each fact was read from.</p></div>{chip(e["kind_label"], "navy")}</div>'
            f'<pre class="doc" data-testid="original-text">{text}</pre></section>')
    right = (f'<section class="card auth tone-{esc(auth["tone"])}" data-testid="authenticity"><small>Source authenticity</small><h3>{esc(auth["label"])}</h3><p>{esc(auth["detail"])}</p>'
             f'<p class="muted small">Delivery Gate cannot mark evidence as independently verified. Only a reviewer can record that they checked it.</p></section>'
             f'<section class="card"><h3>What was found</h3><p class="muted small">{esc(stat)}. {esc(e["extractor_note"] or "")} {esc(e["extraction_message"] or "")}</p>'
             + (f'<ul class="facts">{"".join(facts)}</ul>' if facts else "<p class=muted>Nothing usable was found in this evidence.</p>")
             + (f'<p class="muted small">{e["rejected_count"]} item(s) did not pass validation and were discarded.</p>' if e["rejected_count"] else "") + '</section>' + review)
    body = (page_title(f"{e['kind_label']} · {aid}", f"{e['source_label']} · added {e['added_at']}", (f"/payments/{quote(ref)}/evidence", "Back to evidence"))
            + f'<div class="art-grid"><div>{left}</div><div>{right}</div></div>')
    return shell(f"Evidence {aid} · {ref}", "evidence", body, flash=flash)


# ---- overview, evidence index, errors -----------------------------------------------------------------------------------------------------------
def page_overview(rows: List[Dict[str, Any]], counters: Dict[str, int], flash: Optional[Dict[str, str]] = None) -> str:
    scen = {1: "Clean carrier evidence", 2: "Missing delivery evidence", 3: "Conflicting addresses", 4: "Merchant assertion", 5: "Unknown PayPal status", 6: "Counterfactual"}
    lines = []
    for n, name in scen.items():
        r = next((x for x in rows if n in x["scenarios"]), None)
        if r:
            lines.append(f'<tr><td class="num">{n}</td><td><strong>{esc(name)}</strong></td><td><a class="ref" href="{pay_url(r["ref"])}" data-testid="scenario-{n}">{esc(r["ref"])}</a> · {esc(r["amount"])}</td>'
                         f'<td><span class="pill tone-{esc("red" if r["assessment"]["key"] == "REQUIREMENTS_NOT_DEMONSTRATED" else r["assessment"]["tone"])}">{esc(r["assessment"]["label"])}</span></td></tr>')
    cards = [("attention", "Needs attention", "alert", "red"), ("review", "Under review", "review", "amber"), ("ready", "Evidence ready", "check", "green"), ("unassessable", "Can't be assessed", "help", "slate")]
    kpi = "".join(f'<a class="kpi" href="/payments?filter={k}">{tone_icon(ic, tone, 30)}<div><span>{esc(lbl)}</span><strong>{counters[k]}</strong></div></a>' for k, lbl, ic, tone in cards)
    q4 = [("What is happening with this payment?", "PayPal's reported amount, status and dispute, shown apart from what you tell us."),
          ("What evidence do I have?", "Every document and fact, with the exact text it came from."),
          ("What am I missing?", "Requirements that aren't demonstrated, and records that disagree."),
          ("What changes if I add evidence?", "A hypothetical reassessment by the same engine. Nothing is guessed.")]
    qs = "".join(f'<li><strong>{esc(a)}</strong><span>{esc(b)}</span></li>' for a, b in q4)
    body = (page_title("Overview", "Understand your payment evidence in plain language.") + f'<div class="kpis">{kpi}</div>'
            f'<div class="two"><section class="card"><h3>What Delivery Gate helps you answer</h3><ol class="qs">{qs}</ol><p class="foot-note">{esc(POLICY_FOOTNOTE)}</p></section>'
            f'<section class="card"><h3>Demo scenarios</h3><p class="muted small">All payments are fixtures. Each scenario is computed by the same engine from the evidence on file.</p>'
            f'<table class="tbl compact"><tbody>{"".join(lines)}</tbody></table>'
            f'<form method="post" action="/reset" class="inline-form"><button class="btn btn-secondary" type="submit" data-testid="reset-demo">Reset demo data</button></form></section></div>')
    return shell("Overview", "overview", body, flash=flash)


def page_evidence_index(items: List[Dict[str, Any]]) -> str:
    rows = "".join(f'<tr data-testid="evrow-{esc(i["ref"])}-{esc(i["artifact"]["artifact_id"])}"><td><a class="ref" href="/payments/{quote(i["ref"])}/evidence/{quote(i["artifact"]["artifact_id"])}">{esc(i["artifact"]["artifact_id"])}</a></td>'
                   f'<td>{esc(i["artifact"]["kind_label"])}</td><td><a href="{pay_url(i["ref"])}">{esc(i["ref"])}</a> · {esc(i["order_ref"])}</td><td>{esc(i["artifact"]["source_label"])}</td>'
                   f'<td>{esc(i["artifact"]["extraction_status"].replace("_", " ").capitalize())}</td><td>{i["artifact"]["fact_count"]}</td><td>{chip(i["artifact"]["chip"]["label"], i["artifact"]["chip"]["tone"])}</td></tr>' for i in items)
    tbl = (f'<div class="card table-card"><table class="tbl" data-testid="evidence-table"><thead><tr><th>Evidence</th><th>Type</th><th>Payment</th><th>Source</th><th>Extraction</th><th>Facts</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></div>'
           if rows else f'<div class="card empty" data-testid="empty-evidence-index"><h3>No evidence yet</h3><p>Open a payment to add evidence.</p></div>')
    refs = sorted({i["ref"] for i in items})
    return shell("Evidence", "evidence", page_title("Evidence", "Everything that has been added, across your payments.") + tbl
                 + '<p class="muted small">To add evidence, open a payment and choose “Review evidence”.</p>')


def page_error(code: int, title: str, message: str) -> str:
    return shell(title, "", f'<div class="card empty err" data-testid="error-page" data-code="{code}">{icon("alert", 36)}<h1 class="h2">{esc(title)}</h1><p>{esc(message)}</p>'
                 f'<p>{button("Back to Payments", "/payments", "primary")}</p></div>')


def page_live(configured: bool, history: List[Dict[str, Any]], flash: Optional[Dict[str, str]] = None, error: Optional[Dict[str, Any]] = None, checkout_configured: bool = False, orders: Optional[List[Dict[str, Any]]] = None) -> str:
    """Read-only live PayPal SANDBOX observations. Separate from the fixture payments; never assessed here."""
    cfg = ('<span class="pill tone-green" data-testid="live-configured">Sandbox credentials present in the server environment</span>' if configured else
           '<span class="pill tone-slate" data-testid="live-not-configured">No sandbox credentials in the server environment. Nothing can be fetched.</span>')
    orders = orders or []
    checkout_badge = ('<span class="pill tone-green">Sandbox checkout ready</span>' if checkout_configured else '<span class="pill tone-slate">Sandbox checkout credentials unavailable</span>')
    checkout = (f'<section class="card"><h3>Create a PayPal Sandbox order</h3>{checkout_badge}'
                '<p class="muted small">Creates a real Sandbox order only when submitted. Approval opens on PayPal; capture is a separate, explicit action.</p>'
                '<form method="post" action="/live/orders"><label>Amount <input name="amount" type="number" min="0.01" step="0.01" value="10.00" required></label> '
                '<label>Currency <input name="currency" value="USD" maxlength="3" required></label> '
                '<label>Description <input name="description" maxlength="127" value="Delivery Gate demo order"></label> '
                f'<button class="btn btn-primary" type="submit"{"" if checkout_configured else " disabled"}>Create Sandbox order</button></form></section>')
    order_cards = []
    for rec in orders:
        oid = esc(rec.get("order_id", "")); approval = rec.get("approval_url")
        link = f'<p><a class="btn btn-primary" href="{esc(approval)}" target="_blank" rel="noopener">Approve on PayPal</a></p>' if approval else '<p class="muted small">PayPal did not return an approval link.</p>'
        case_link = f'<p><a href="/payments/{esc(rec.get("case_id"))}">Open Delivery Gate assessment {esc(rec.get("case_id"))}</a></p>' if rec.get("case_id") and rec.get("capture") else ''
        order_cards.append(f'<section class="card"><h3><span class="pill tone-amber">LIVE_SANDBOX</span> Order {oid}</h3><p>Status: <strong>{esc(rec.get("status"))}</strong> · {esc(rec.get("amount"))} {esc(rec.get("currency"))}</p>{case_link}{link}'
                           f'<form method="post" action="/live/orders/retrieve"><input type="hidden" name="order_id" value="{oid}"><button class="btn" type="submit">Retrieve order</button></form> '
                           f'<form method="post" action="/live/orders/capture"><input type="hidden" name="order_id" value="{oid}"><button class="btn btn-primary" type="submit">Capture approved order</button></form>'
                           + (''.join(f'<p>Capture ID: {esc(c.get("id"))} · Status: {esc(c.get("status"))} · Amount: {esc(c.get("amount",{}).get("value"))} {esc(c.get("amount",{}).get("currency_code"))} · Seller protection: {esc(c.get("seller_protection",{}).get("status","not returned"))}</p>' for c in rec.get('capture',{}).get('captures',[])) + f'<details><summary>Actual PayPal capture response</summary><pre>{esc(json.dumps(rec.get("capture",{}).get("capture_response",{}), indent=2))}</pre></details>' if rec.get('capture') else '')
                           + f'<details><summary>PayPal order response</summary><pre>{esc(json.dumps(rec.get("order",{}), indent=2))}</pre></details></section>')
    form = (f'<form method="post" action="/live/observe" class="card" data-testid="live-form"><h3>Retrieve from the PayPal sandbox</h3>{cfg}'
            '<p class="muted small">A read-only GET to api-m.sandbox.paypal.com. Nothing is created, captured or changed. The result is shown exactly as PayPal returned it.</p>'
            '<label>Resource <select name="kind"><option value="capture">Capture</option><option value="order">Order</option></select></label> '
            '<label>ID <input name="resource_id" required maxlength="64" data-testid="live-id"></label> '
            '<label>Capture to observe (orders with several captures) <input name="select" maxlength="64"></label> '
            f'<button class="btn btn-primary" type="submit" data-testid="live-submit"{"" if configured else " disabled"}>Retrieve</button></form>')
    err = ""
    if error:
        err = (f'<div class="flash flash-error" role="alert" data-testid="live-error"><strong>Retrieval failed ({esc(error["code"])}).</strong> {esc(error["message"])}'
               + (f' HTTP {esc(error["status"])}.' if error.get("status") else "") + (f' PayPal debug id: {esc(error["debug_id"])}.' if error.get("debug_id") else "") + '</div>')
    cards = []
    for h in history:
        o = h["observation"]
        rows = "".join(f'<tr><td>{esc(x["local_path"])}</td><td><code>{esc(x["raw_value"])}</code></td><td>{esc(x.get("enum_state") or "")}</td></tr>' for x in o["observations"])
        absent = ", ".join(esc(a.get("local_path", "?")) for a in o["absent"]) or "none"
        cards.append(f'<section class="card" data-testid="live-observation" data-origin="{esc(h["origin"])}"><h3><span class="pill tone-amber">LIVE_SANDBOX</span> {esc(h["resource"])} {esc(h["resource_id"])}</h3>'
                     f'<ul class="plain"><li>Request: GET https://{esc(h["host"])}{esc(h["request_path"])}</li><li>HTTP status: {esc(h["http_status"])}</li><li>PayPal debug id: {esc(h["paypal_debug_id"])}</li>'
                     f'<li>Retrieved at: {esc(h["observed_at"])}</li><li>Response SHA-256 (canonical JSON): <code>{esc(h["response_sha256"])}</code></li></ul>'
                     f'<table class="tbl compact"><thead><tr><th>Field</th><th>Value as received</th><th>Enum state</th></tr></thead><tbody>{rows}</tbody></table>'
                     f'<p class="muted small">Absent from the response (unknown, not assumed): {absent}.</p>'
                     '<p class="muted small">This is an observation, not an assessment. PayPal status values are opaque. A sandbox response is not evidence of Seller Protection eligibility.</p></section>')
    empty = '' if cards else '<div class="card empty" data-testid="live-empty"><h3>No live observations yet</h3><p>Nothing has been retrieved in this session. Fixture payments elsewhere in the app are not live data.</p></div>'
    return shell("Live sandbox", "live", page_title("Live sandbox", "Real PayPal sandbox responses, kept apart from fixture payments.") + checkout + "".join(order_cards) + form + err + empty + "".join(cards))
