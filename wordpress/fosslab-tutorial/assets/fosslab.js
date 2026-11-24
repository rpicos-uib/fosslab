/* FOSSLab tutorial: a Copy button on every command block. */
(function () {
  'use strict';
  var t = window.fosslabTut || { copy: 'Copy', copied: 'Copied' };

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) { /* ignore */ }
    document.body.removeChild(ta);
    return Promise.resolve();
  }

  function init() {
    var blocks = document.querySelectorAll('.fosslab pre');
    Array.prototype.forEach.call(blocks, function (pre) {
      if (pre.querySelector('.fl-copy') || pre.classList.contains('fl-nocopy')) { return; }
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'fl-copy';
      btn.textContent = t.copy;
      btn.addEventListener('click', function () {
        // Copy the commands only: drop "$ " prompts and lines of output (marked with class fl-out).
        var code = pre.querySelector('code') || pre;
        var clone = code.cloneNode(true);
        Array.prototype.forEach.call(clone.querySelectorAll('.fl-out'), function (n) { n.remove(); });
        var text = clone.textContent.split('\n').map(function (l) { return l.replace(/^\$ /, ''); }).join('\n').trim();
        copyText(text).then(function () {
          btn.textContent = t.copied;
          setTimeout(function () { btn.textContent = t.copy; }, 1500);
        });
      });
      pre.appendChild(btn);
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}());
