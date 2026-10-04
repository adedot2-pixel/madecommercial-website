// Mobile menu + contact form handling. No tracking, no cookies.
(function () {
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

  var form = document.getElementById('contact-form');
  if (!form) return;
  var status = document.getElementById('form-status');
  var endpoint = form.getAttribute('data-endpoint');
  var email = form.getAttribute('data-email');

  function show(kind, msg) {
    status.className = 'form-status show ' + kind;
    status.textContent = msg;
  }

  // Prefill the subject from ?topic=
  var topic = new URLSearchParams(location.search).get('topic');
  var select = form.querySelector('select[name="topic"]');
  if (topic && select) {
    Array.prototype.forEach.call(select.options, function (o) {
      if (o.value === topic) select.value = topic;
    });
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var data = new FormData(form);
    if (data.get('website')) return; // honeypot
    if (!form.checkValidity()) { form.reportValidity(); return; }

    if (endpoint) {
      show('ok', 'Sending...');
      fetch(endpoint, { method: 'POST', body: data, headers: { Accept: 'application/json' } })
        .then(function (r) {
          if (!r.ok) throw new Error('bad status');
          form.reset();
          show('ok', 'Thank you. Your message has been sent and we will reply shortly.');
        })
        .catch(function () {
          show('err', 'Sorry, that did not send. Please email ' + email + ' instead.');
        });
    } else {
      // No form service configured: open the visitor's email app with the message filled in.
      var body = 'Name: ' + data.get('name') + '\nCompany: ' + (data.get('company') || '') + '\nEmail: ' + data.get('email') + '\n\n' + data.get('message');
      location.href = 'mailto:' + email + '?subject=' + encodeURIComponent('Website enquiry: ' + data.get('topic')) + '&body=' + encodeURIComponent(body);
      show('ok', 'Your email app should now open with your message ready to send.');
    }
  });
})();
