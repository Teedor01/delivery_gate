/* Progressive enhancement only. Every page works as plain HTML forms and links; this adds convenience, never logic.
   No assessment, status or authenticity value is computed or stored here. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  // Whole table rows open their payment panel.
  $$("tr.row[data-href]").forEach(function (tr) {
    tr.addEventListener("click", function (e) { if (!e.target.closest("a")) window.location.href = tr.getAttribute("data-href"); });
  });

  // Copy buttons.
  $$("[data-copy]").forEach(function (b) {
    b.addEventListener("click", function () {
      var v = b.getAttribute("data-copy");
      if (navigator.clipboard) { navigator.clipboard.writeText(v).catch(function () {}); }
      b.setAttribute("aria-label", "Copied"); setTimeout(function () { b.setAttribute("aria-label", "Copy order reference"); }, 1500);
    });
  });

  // Expand / collapse all requirements.
  var exp = $("[data-expand-all]");
  if (exp) {
    exp.addEventListener("click", function () {
      var items = $$("details.req"); var open = items.some(function (d) { return !d.open; });
      items.forEach(function (d) { d.open = open; }); exp.textContent = open ? "Collapse all" : "Expand all";
    });
  }

  // Loading state on every form submit: the button shows it is working, and a second submit of the same form is ignored.
  // (The button is not disabled: a disabled submitter would drop its name/value, which the review forms rely on.)
  $$("form").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (f.getAttribute("data-busy") === "1") { e.preventDefault(); return; }
      f.setAttribute("data-busy", "1");
      var b = e.submitter || f.querySelector("button[type=submit]");
      if (b && !b.hasAttribute("formnovalidate")) { setTimeout(function () { b.classList.add("loading"); b.setAttribute("aria-busy", "true"); }, 0); }
    });
  });
  window.addEventListener("pageshow", function (e) {            // coming back via the browser's back button must not leave forms stuck
    if (e.persisted) { $$("form[data-busy]").forEach(function (f) { f.removeAttribute("data-busy"); }); $$(".btn.loading").forEach(function (b) { b.classList.remove("loading"); b.removeAttribute("aria-busy"); }); }
  });

  // File drop / choose: text files only. The text is put in the textarea so it can be seen before it is submitted.
  var dz = $("#dropzone"), fi = $("#fileinput"), ta = $("#evtext"), fn = $("#filename"), src = $("#evsource");
  var TEXT = /\.(txt|eml|csv|md|text|log)$/i, MAX = 200000;
  function load(file) {
    if (!file) return;
    if (!TEXT.test(file.name) && file.type.indexOf("text/") !== 0) {
      fn.textContent = "“" + file.name + "” can’t be read yet. Only text files are supported; PDFs and images are not.";
      fn.className = "filename error"; return;
    }
    if (file.size > MAX) { fn.textContent = "That file is larger than 200 KB, which is the limit in this demo."; return; }
    var r = new FileReader();
    r.onload = function () { ta.value = String(r.result); fn.textContent = "Loaded " + file.name + " (" + file.size + " bytes). Check it, then choose Add and analyse."; if (src) src.value = "Uploaded file: " + file.name; };
    r.onerror = function () { fn.textContent = "That file could not be read."; };
    r.readAsText(file);
  }
  if (dz && fi) {
    fi.addEventListener("click", function (e) { e.stopPropagation(); });          // the input lives inside the dropzone: don't re-trigger it
    dz.addEventListener("click", function () { fi.click(); });
    dz.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fi.click(); } });
    fi.addEventListener("change", function () { load(fi.files[0]); });
    ["dragenter", "dragover"].forEach(function (ev) { dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.add("over"); }); });
    ["dragleave", "drop"].forEach(function (ev) { dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.remove("over"); }); });
    dz.addEventListener("drop", function (e) { load(e.dataTransfer.files[0]); });
  }

  // Reviewer name is remembered for this browser tab only, and copied into per-fact reject forms.
  var rv = $("#reviewer");
  if (rv) {
    try { if (!rv.value) rv.value = sessionStorage.getItem("dg-reviewer") || ""; } catch (e) {}
    var sync = function () { try { sessionStorage.setItem("dg-reviewer", rv.value); } catch (e) {} $$(".reviewer-copy").forEach(function (h) { h.value = rv.value; }); };
    rv.addEventListener("input", sync); sync();
    $$("form").forEach(function (f) { if (f.querySelector(".reviewer-copy")) f.addEventListener("submit", function () { sync(); }); });
  }

  // Clicking a fact highlights where it was read from.
  $$(".fact").forEach(function (li) {
    li.addEventListener("click", function (e) {
      if (e.target.closest("button,summary,a")) return;
      var id = li.getAttribute("data-fact");
      $$(".fact.active,mark.hl.active").forEach(function (x) { x.classList.remove("active"); });
      li.classList.add("active");
      $$("mark.hl").forEach(function (m) {
        if ((m.getAttribute("data-facts") || "").split(" ").indexOf(id) >= 0) { m.classList.add("active"); m.scrollIntoView({ block: "center", behavior: "smooth" }); }
      });
    });
  });
})();
