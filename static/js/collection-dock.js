/*
 * Bottom dock for tracker/_collection_controls.html.
 *
 * Two jobs: publishing the dock's height as --dock-height so the page can leave
 * room for it, and the hamburger sheet. The sheet only exists visually below
 * 720px (see collection-controls.css); above that the controls are always laid
 * out inline, so toggling the class is harmless.
 * Loaded with defer by both the tracker and demo pages.
 */
(function () {
    var controls = document.getElementById('collectionControls');
    var toggle = document.getElementById('hamburgerToggle');
    var backdrop = document.getElementById('dockBackdrop');

    if (!controls || !toggle) {
        return;
    }

    /*
     * The dock is fixed, so the page's bottom padding has to match its height,
     * which moves as the control row wraps. Measured rather than hard-coded;
     * the CSS carries a fallback for the first paint.
     */
    function publishHeight() {
        document.documentElement.style.setProperty(
            '--dock-height', controls.offsetHeight + 'px');
    }

    if (typeof ResizeObserver === 'function') {
        new ResizeObserver(publishHeight).observe(controls);
    } else {
        window.addEventListener('resize', publishHeight);
        publishHeight();
    }

    function setOpen(open) {
        controls.classList.toggle('sheet-open', open);
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        toggle.setAttribute('aria-label', open ? 'Close filters' : 'Open filters');
        toggle.textContent = open ? '✕' : '☰';
        if (backdrop) {
            backdrop.classList.toggle('active', open);
        }
    }

    function isOpen() {
        return controls.classList.contains('sheet-open');
    }

    toggle.addEventListener('click', function () {
        setOpen(!isOpen());
    });

    if (backdrop) {
        backdrop.addEventListener('click', function () {
            setOpen(false);
        });
    }

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && isOpen()) {
            setOpen(false);
            toggle.focus();
        }
    });
})();
