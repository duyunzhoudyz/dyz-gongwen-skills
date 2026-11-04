/* dyz-gongwen-skills 落地页脚本：进场渐显、安装方式切换、命令一键复制。
   没有脚本时页面内容完整可读，所有安装方式依次展开。 */
(function () {
  'use strict';

  var doc = document;
  var root = doc.documentElement;
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // 主脚本已就绪，取消 head 里的兜底显示
  window.__gwReady = true;

  /* ---------- 进场渐显：每个区块的子元素错开 60 到 90ms ---------- */
  function initReveal() {
    var items = [].slice.call(doc.querySelectorAll('[data-reveal]'));
    if (!items.length) return;

    if (reduceMotion || !('IntersectionObserver' in window)) {
      items.forEach(function (el) { el.classList.add('in'); });
      return;
    }

    // 同一个父节点下的多个待显示元素，没有手写延迟的按顺序补延迟
    var counters = new Map();
    items.forEach(function (el) {
      if (el.style.getPropertyValue('--d')) return;
      var parent = el.parentElement;
      var n = counters.get(parent) || 0;
      counters.set(parent, n + 1);
      if (n > 0) el.style.setProperty('--d', Math.min(n, 6) * 70 + 'ms');
    });

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('in');
          io.unobserve(entry.target);
        }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });

    items.forEach(function (el) { io.observe(el); });
  }

  /* ---------- 顶栏滚动后换一档底色 ---------- */
  function initHeader() {
    var header = doc.querySelector('.site-header');
    if (!header) return;
    var ticking = false;
    function update() {
      header.classList.toggle('is-scrolled', window.scrollY > 24);
      ticking = false;
    }
    window.addEventListener('scroll', function () {
      if (!ticking) {
        ticking = true;
        window.requestAnimationFrame(update);
      }
    }, { passive: true });
    update();
  }

  /* ---------- 安装方式切换（WAI-ARIA tabs，支持方向键、Home、End） ---------- */
  function initTabs() {
    var group = doc.querySelector('[data-tabs]');
    if (!group) return;
    var tabs = [].slice.call(group.querySelectorAll('[role="tab"]'));
    var panels = tabs.map(function (t) { return doc.getElementById(t.getAttribute('aria-controls')); });

    function select(index, focus) {
      tabs.forEach(function (tab, i) {
        var on = i === index;
        tab.setAttribute('aria-selected', on ? 'true' : 'false');
        tab.tabIndex = on ? 0 : -1;
        if (panels[i]) {
          panels[i].hidden = !on;
          panels[i].classList.remove('is-entering');
          if (on && !reduceMotion) {
            // 触发一次进入动画
            void panels[i].offsetWidth;
            panels[i].classList.add('is-entering');
          }
        }
      });
      if (focus) tabs[index].focus();
    }

    tabs.forEach(function (tab, i) {
      tab.addEventListener('click', function () { select(i, false); });
      tab.addEventListener('keydown', function (e) {
        var next = null;
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (i + 1) % tabs.length;
        else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (i - 1 + tabs.length) % tabs.length;
        else if (e.key === 'Home') next = 0;
        else if (e.key === 'End') next = tabs.length - 1;
        if (next !== null) {
          e.preventDefault();
          select(next, true);
        }
      });
    });

    // 从带 hash 的外链进来时，不改变默认选中项
    select(0, false);
  }

  /* ---------- 命令一键复制 ---------- */
  function fallbackCopy(text) {
    var ta = doc.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    doc.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = doc.execCommand('copy'); } catch (e) { ok = false; }
    doc.body.removeChild(ta);
    return ok;
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return fallbackCopy(text); });
    }
    return Promise.resolve(fallbackCopy(text));
  }

  function initCopy() {
    var live = doc.createElement('div');
    live.className = 'sr-only';
    live.setAttribute('role', 'status');
    live.setAttribute('aria-live', 'polite');
    doc.body.appendChild(live);

    [].forEach.call(doc.querySelectorAll('[data-copy]'), function (btn) {
      var original = btn.textContent;
      var timer = null;
      btn.addEventListener('click', function () {
        var target = doc.getElementById(btn.getAttribute('data-copy'));
        if (!target) return;
        copyText(target.textContent.replace(/\s+$/, '')).then(function (ok) {
          if (!ok && window.getSelection) {
            // 复制失败时选中命令，方便用户直接按 Ctrl+C
            var range = doc.createRange();
            range.selectNodeContents(target);
            var sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
          }
          btn.textContent = ok ? '已复制' : '请手动复制';
          btn.classList.toggle('is-done', ok);
          live.textContent = ok ? '命令已复制到剪贴板' : '复制失败，请手动选中后复制';
          clearTimeout(timer);
          timer = setTimeout(function () {
            btn.textContent = original;
            btn.classList.remove('is-done');
          }, 1800);
        });
      });
    });
  }

  function init() {
    initReveal();
    initHeader();
    initTabs();
    initCopy();
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', init);
  else init();
})();
