/* NDC Contact Form: proves a real browser with a real person is filling in the form. */
(function () {
	document.querySelectorAll('form.ndc-form').forEach(function (form) {
		var token = form.querySelector('[name="ndc_token"]');
		var proof = form.querySelector('[name="ndc_js"]');
		if (!token || !proof) return;

		// Only mark the form as human after genuine interaction.
		var arm = function () { proof.value = 'ok:' + token.value; };
		['keydown', 'pointerdown', 'touchstart', 'input'].forEach(function (evt) {
			form.addEventListener(evt, arm, { once: true, passive: true });
		});

		form.addEventListener('submit', function (e) {
			// Instant feedback for empty or malformed fields; the server validates again.
			if (typeof form.reportValidity === 'function' && !form.reportValidity()) {
				e.preventDefault();
				return;
			}
			var button = form.querySelector('.ndc-form__submit');
			if (button) {
				button.disabled = true;
				button.textContent = button.getAttribute('data-sending') || 'Sending…';
			}
		});
	});
})();
