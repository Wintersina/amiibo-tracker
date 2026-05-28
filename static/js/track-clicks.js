(function () {
    var MAX_WAIT_MS = 10000;
    var POLL_MS = 250;

    function getFaro() {
        return (window.GrafanaFaroWebSdk && window.GrafanaFaroWebSdk.faro) || null;
    }

    function pushEvent(action, target) {
        var faro = getFaro();
        if (!faro || !faro.api || typeof faro.api.pushEvent !== 'function') {
            return;
        }
        try {
            faro.api.pushEvent('ui-click', {
                action: String(action || '').slice(0, 64),
                path: window.location.pathname,
                tag: (target && target.tagName) ? target.tagName.toLowerCase() : '',
                text: (target && target.innerText ? target.innerText.trim().slice(0, 64) : '')
            });
        } catch (e) {
            // Observability must never break the page.
        }
    }

    function onClick(event) {
        var node = event.target;
        // Walk up to find the nearest [data-track] ancestor (handles clicks on
        // child spans/icons inside a tagged button).
        while (node && node !== document.body) {
            if (node.dataset && node.dataset.track) {
                pushEvent(node.dataset.track, node);
                return;
            }
            node = node.parentElement;
        }
    }

    function attach() {
        document.addEventListener('click', onClick, { capture: true, passive: true });
    }

    // Faro is loaded async after the SDK bundle resolves. Start listening
    // immediately; events queued before Faro is ready are silently dropped,
    // which is the right behavior (no Faro means no transport).
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', attach, { once: true });
    } else {
        attach();
    }

    // Surface a warning in dev when Faro never shows up so misconfiguration
    // is obvious during local testing.
    var waited = 0;
    var poll = setInterval(function () {
        if (getFaro()) {
            clearInterval(poll);
            return;
        }
        waited += POLL_MS;
        if (waited >= MAX_WAIT_MS) {
            clearInterval(poll);
            if (window.console && console.warn) {
                console.warn('[track-clicks] Faro SDK did not initialize within ' + MAX_WAIT_MS + 'ms; ui-click events will be dropped.');
            }
        }
    }, POLL_MS);
})();
