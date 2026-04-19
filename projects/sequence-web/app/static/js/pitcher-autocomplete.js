(function () {
  function initAutocomplete(input) {
    const wrap = document.createElement('div');
    wrap.className = 'ac-wrap';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    const dropdown = document.createElement('div');
    dropdown.className = 'ac-dropdown';
    dropdown.hidden = true;
    wrap.appendChild(dropdown);

    let timer;
    let items = [];
    let activeIdx = -1;

    function render(results) {
      items = results;
      activeIdx = -1;
      dropdown.innerHTML = '';
      if (!results.length) { dropdown.hidden = true; return; }
      results.forEach(function (r) {
        const div = document.createElement('div');
        div.className = 'ac-item';
        div.textContent = r.name;
        div.addEventListener('mousedown', function (e) {
          e.preventDefault();
          pick(r);
        });
        dropdown.appendChild(div);
      });
      dropdown.hidden = false;
    }

    function pick(r) {
      input.value = r.name;
      dropdown.hidden = true;
    }

    function highlight(idx) {
      const divs = dropdown.querySelectorAll('.ac-item');
      divs.forEach(function (d, i) { d.classList.toggle('active', i === idx); });
    }

    input.addEventListener('input', function () {
      clearTimeout(timer);
      const q = input.value.trim();
      if (q.length < 2) { dropdown.hidden = true; return; }
      timer = setTimeout(function () {
        fetch('/api/pitcher-search?q=' + encodeURIComponent(q))
          .then(function (r) { return r.json(); })
          .then(render)
          .catch(function () { dropdown.hidden = true; });
      }, 280);
    });

    input.addEventListener('keydown', function (e) {
      if (dropdown.hidden) return;
      const divs = dropdown.querySelectorAll('.ac-item');
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        activeIdx = Math.min(activeIdx + 1, divs.length - 1);
        highlight(activeIdx);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        activeIdx = Math.max(activeIdx - 1, -1);
        highlight(activeIdx);
      } else if (e.key === 'Enter' && activeIdx >= 0) {
        e.preventDefault();
        pick(items[activeIdx]);
      } else if (e.key === 'Escape') {
        dropdown.hidden = true;
      }
    });

    input.addEventListener('blur', function () {
      setTimeout(function () { dropdown.hidden = true; }, 150);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('input[name="pitcher_name"]').forEach(initAutocomplete);
  });
})();
