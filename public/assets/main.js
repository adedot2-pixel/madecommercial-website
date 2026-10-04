// Mobile menu, scroll reveals, pointer-follow highlights, contact form. No tracking, no cookies.
(function () {
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Mobile menu
  var toggle = document.querySelector('.nav-toggle');
  var nav = document.getElementById('site-nav');
  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      var open = nav.classList.toggle('open');
      toggle.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && nav.classList.contains('open')) {
        nav.classList.remove('open');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.focus();
      }
    });
  }

  // Scroll reveals (also drives the mock's bar animation)
  var targets = document.querySelectorAll('.reveal, .mock');
  if ('IntersectionObserver' in window && !reduce) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); }
      });
    }, { threshold: 0.15, rootMargin: '0px 0px -6% 0px' });
    targets.forEach(function (t) { io.observe(t); });
  } else {
    targets.forEach(function (t) { t.classList.add('in'); });
  }

  // Micro-reflection: a soft highlight follows the pointer over tiles and the hero image
  if (!reduce) {
    document.querySelectorAll('.tile, .hero-art, .spot').forEach(function (el) {
      el.addEventListener('pointermove', function (e) {
        var r = el.getBoundingClientRect();
        el.style.setProperty('--mx', (e.clientX - r.left) + 'px');
        el.style.setProperty('--my', (e.clientY - r.top) + 'px');
      });
    });
  }

  // Contact form
  var form = document.getElementById('contact-form');
  if (!form) return;
  var status = document.getElementById('form-status');
  var endpoint = form.getAttribute('data-endpoint');
  var email = form.getAttribute('data-email');
  function show(kind, msg) { status.className = 'form-status show ' + kind; status.textContent = msg; }

  var topic = new URLSearchParams(location.search).get('topic');
  var select = form.querySelector('select[name="topic"]');
  if (topic && select) {
    Array.prototype.forEach.call(select.options, function (o) { if (o.value === topic) select.value = topic; });
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var data = new FormData(form);
    if (data.get('website')) return; // honeypot
    if (!form.checkValidity()) { form.reportValidity(); return; }
    if (endpoint) {
      show('ok', 'Sending...');
      fetch(endpoint, { method: 'POST', body: data, headers: { Accept: 'application/json' } })
        .then(function (r) { if (!r.ok) throw new Error('bad status'); form.reset(); show('ok', 'Thank you. We will reply shortly.'); })
        .catch(function () { show('err', 'Sorry, that did not send. Please email ' + email + ' instead.'); });
    } else {
      var body = 'Name: ' + data.get('name') + '\nCompany: ' + (data.get('company') || '') + '\nEmail: ' + data.get('email') + '\n\n' + data.get('message');
      location.href = 'mailto:' + email + '?subject=' + encodeURIComponent('Website enquiry: ' + data.get('topic')) + '&body=' + encodeURIComponent(body);
      show('ok', 'Your email app should now open with your message ready to send.');
    }
  });
})();
