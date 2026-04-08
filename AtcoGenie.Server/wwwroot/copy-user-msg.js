(function () {
  var SVG_COPY = '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
  var SVG_CHECK = '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 18 4 13"/></svg>';

  function attachCopy(wrapper) {
    if (wrapper.dataset.ucopy) return;
    var bubble = wrapper.firstElementChild;
    var p = wrapper.querySelector('p');
    if (!bubble || !p) return;
    wrapper.dataset.ucopy = '1';

    // Container to sit beside the bubble
    var btnContainer = document.createElement('div');
    btnContainer.className = 'flex items-end mb-2'; // aligns it near bottom of bubble
    btnContainer.style.opacity = '0';
    btnContainer.style.transition = 'opacity 0.15s ease';

    var btn = document.createElement('button');
    btn.innerHTML = SVG_COPY;
    btn.title = 'Copy prompt';
    btn.style.cssText = [
      'width:24px',
      'height:24px',
      'display:flex',
      'align-items:center',
      'justify-content:center',
      'border:none',
      'border-radius:5px',
      'background:transparent',
      'color:#94a3b8',
      'cursor:pointer',
    ].join(';');

    // Show/hide on hover over the entire wrapper
    wrapper.addEventListener('mouseenter', function () { btnContainer.style.opacity = '1'; });
    wrapper.addEventListener('mouseleave', function () { btnContainer.style.opacity = '0'; });

    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      navigator.clipboard.writeText(p.textContent || '').then(function () {
        btn.innerHTML = SVG_CHECK;
        btn.style.color = '#22c55e';
        setTimeout(function () {
          btn.innerHTML = SVG_COPY;
          btn.style.color = '#94a3b8';
        }, 1500);
      }).catch(function (err) { console.warn('Copy failed:', err); });
    });

    btnContainer.appendChild(btn);
    // Insert the button container BEFORE the bubble so it sits on the left side
    wrapper.insertBefore(btnContainer, bubble);
  }

  function scan() {
    var wrappers = document.querySelectorAll('div.mb-6.justify-end');
    for (var i = 0; i < wrappers.length; i++) {
        attachCopy(wrappers[i]);
    }
  }

  // Start polling immediately and every 300ms
  scan();
  setInterval(scan, 300);
})();
