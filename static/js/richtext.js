// Renders Markdown (code, tables, math, mermaid) safely into an element.
window.NovaRender = function (el, text) {
  var html = window.marked ? marked.parse(text) : text;
  el.innerHTML = window.DOMPurify ? DOMPurify.sanitize(html) : html;
  el.querySelectorAll('pre code.language-mermaid').forEach(function (code) {
    var d = document.createElement('div'); d.className = 'mermaid';
    d.textContent = code.textContent; code.closest('pre').replaceWith(d);
  });
  if (window.mermaid) { try { mermaid.run({ nodes: el.querySelectorAll('.mermaid') }); } catch (e) {} }
  if (window.hljs) el.querySelectorAll('pre code').forEach(function (c) { try { hljs.highlightElement(c); } catch (e) {} });
  if (window.renderMathInElement) {
    try {
      renderMathInElement(el, {
        delimiters: [{ left: '$$', right: '$$', display: true },
                     { left: '\\(', right: '\\)', display: false },
                     { left: '\\[', right: '\\]', display: true }],
        throwOnError: false,
      });
    } catch (e) {}
  }
};
(function () {
  if (window.marked) marked.setOptions({ breaks: true, gfm: true });
  if (window.mermaid) mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'neutral' });
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-md]').forEach(function (el) {
      window.NovaRender(el, el.textContent.trim());
    });
  });
})();
