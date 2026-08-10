/*
 * Bottom filter dock for tracker/_collection_controls.html.
 *
 * The dock only exists visually below 720px (see collection-controls.css); above
 * that the sheet is always laid out inline, so toggling the class is harmless.
 * Loaded with defer by both the tracker and demo pages.
 */
(function () {
    var controls = document.getElementById('collectionControls');
    var toggle = document.getElementById('hamburgerToggle');
    var backdrop = document.getElementById('dockBackdrop');

    if (!controls || !toggle) {
        return;
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
