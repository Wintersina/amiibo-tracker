/*
 * AmiiboDex marketplace price chart.
 *
 * Renders the snapshot series emitted by tracker.pricing.build_price_chart_data
 * into an SVG line chart using the vendored d3 subset (see
 * static/js/vendor/d3-price-chart-subset.js).
 *
 * Why the client owns layout:
 *  - Snapshots arrive on an irregular cadence (scheduled refresh + one after
 *    every deploy), so the x axis has to be a real time scale. The previous
 *    server-rendered chart spaced points evenly by index, which made a 1-day
 *    gap and an 8-day gap the same width and turned slow drifts into cliffs.
 *  - curveMonotoneX cannot overshoot between points. The old Catmull-Rom did,
 *    drawing dips below prices that never occurred.
 *
 * Colours, type and chrome all come from CSS custom properties so the stylesheet
 * stays the single source of truth; nothing here hard-codes a hex.
 */
(function () {
    "use strict";

    var MARGIN = { top: 18, right: 62, bottom: 28, left: 52 };
    var PLOT_HEIGHT = 232;
    var MIN_DOT_R = 4;      // marker spec: >= 8px across
    var MAX_DOT_R = 9;
    var RING = 2;           // surface ring, in px
    var SVG_NS = "http://www.w3.org/2000/svg";

    function el(name, attrs) {
        var node = document.createElementNS(SVG_NS, name);
        for (var key in attrs) {
            if (attrs[key] !== null && attrs[key] !== undefined) {
                node.setAttribute(key, attrs[key]);
            }
        }
        return node;
    }

    function readTokens(root) {
        var s = getComputedStyle(root);
        return {
            loose: s.getPropertyValue("--pc-loose").trim(),
            nib: s.getPropertyValue("--pc-nib").trim(),
            surface: s.getPropertyValue("--pc-surface").trim(),
            grid: s.getPropertyValue("--pc-grid").trim(),
            axis: s.getPropertyValue("--pc-axis").trim(),
            muted: s.getPropertyValue("--pc-muted").trim(),
            ink: s.getPropertyValue("--pc-ink").trim(),
            band: s.getPropertyValue("--pc-band").trim()
        };
    }

    function centsToDollars(cents) {
        return cents === null || cents === undefined ? null : cents / 100;
    }

    function init(root) {
        var payload = document.getElementById(root.dataset.source);
        if (!payload) return;

        var raw;
        try {
            raw = JSON.parse(payload.textContent);
        } catch (err) {
            return;
        }
        if (!Array.isArray(raw) || raw.length === 0) return;

        var data = raw.map(function (d) {
            return {
                date: new Date(d.date + "T00:00:00"),
                label: d.label,
                loose: centsToDollars(d.loose),
                nib: centsToDollars(d.new),
                looseDisplay: d.looseDisplay,
                nibDisplay: d.newDisplay,
                looseSamples: d.looseSamples || 0,
                nibSamples: d.newSamples || 0,
                confidence: d.confidence || ""
            };
        }).filter(function (d) {
            return !isNaN(d.date.getTime());
        });

        if (!data.length) return;

        var plot = document.createElement("div");
        plot.className = "pc-plot";
        var tooltip = document.createElement("div");
        tooltip.className = "pc-tooltip";
        tooltip.setAttribute("role", "status");
        tooltip.setAttribute("aria-live", "polite");
        plot.appendChild(tooltip);
        root.appendChild(plot);

        var activeIndex = -1;
        var geometry = null;
        var lastWidth = 0;

        function render() {
            var width = plot.clientWidth || root.clientWidth;
            if (!width) return;
            lastWidth = width;

            var t = readTokens(root);
            var height = PLOT_HEIGHT + MARGIN.top + MARGIN.bottom;
            var innerW = Math.max(10, width - MARGIN.left - MARGIN.right);
            var innerH = PLOT_HEIGHT;

            var existing = plot.querySelector("svg");
            if (existing) existing.remove();

            var svg = el("svg", {
                class: "pc-svg",
                width: width,
                height: height,
                viewBox: "0 0 " + width + " " + height,
                role: "img",
                tabindex: "0",
                "aria-label": root.dataset.label || "Price history chart"
            });

            var g = el("g", {
                transform: "translate(" + MARGIN.left + "," + MARGIN.top + ")"
            });
            svg.appendChild(g);

            // ── scales ───────────────────────────────────────────────────────
            var x = d3.scaleTime()
                .domain(d3.extent(data, function (d) { return d.date; }))
                .range([0, innerW]);

            // A single snapshot has no extent; give it a day of room so the dot
            // lands mid-plot instead of collapsing onto the left edge.
            if (+x.domain()[0] === +x.domain()[1]) {
                var only = x.domain()[0];
                x.domain([
                    new Date(+only - 86400000),
                    new Date(+only + 86400000)
                ]);
            }

            var vals = [];
            data.forEach(function (d) {
                if (d.loose !== null) vals.push(d.loose);
                if (d.nib !== null) vals.push(d.nib);
            });
            var lo = d3.min(vals);
            var hi = d3.max(vals);
            // Pad so a flat series never rides the axis floor (the old chart's
            // loose line sat exactly on the baseline with nowhere to breathe).
            var pad = (hi - lo) * 0.18 || Math.max(1, hi * 0.1);
            var y = d3.scaleLinear()
                .domain([Math.max(0, lo - pad), hi + pad])
                .nice(5)
                .range([innerH, 0]);

            var maxSamples = d3.max(data, function (d) {
                return Math.max(d.looseSamples, d.nibSamples);
            }) || 0;
            // Area-proportional: sqrt keeps a 4x sample count 2x the radius.
            var rScale = d3.scaleSqrt()
                .domain([0, Math.max(1, maxSamples)])
                .range([MIN_DOT_R, MAX_DOT_R])
                .clamp(true);
            function radius(samples) {
                return samples > 0 ? rScale(samples) : MIN_DOT_R;
            }

            // ── grid + y ticks ───────────────────────────────────────────────
            var yTicks = y.ticks(5);
            yTicks.forEach(function (v) {
                g.appendChild(el("line", {
                    class: "pc-grid",
                    x1: 0, x2: innerW, y1: y(v), y2: y(v), stroke: t.grid
                }));
                var label = el("text", {
                    class: "pc-tick pc-tick-y",
                    x: -10, y: y(v), fill: t.muted,
                    "text-anchor": "end", "dominant-baseline": "middle"
                });
                label.textContent = "$" + d3.format(",")(Math.round(v));
                g.appendChild(label);
            });

            // ── x axis ───────────────────────────────────────────────────────
            g.appendChild(el("line", {
                class: "pc-axis",
                x1: 0, x2: innerW, y1: innerH, y2: innerH, stroke: t.axis
            }));

            var span = x.domain()[1] - x.domain()[0];
            var fmt = d3.timeFormat(span > 1000 * 60 * 60 * 24 * 120 ? "%b %Y" : "%b %-d");
            var xTickCount = Math.max(2, Math.min(6, Math.floor(innerW / 92)));
            x.ticks(xTickCount).forEach(function (d) {
                var label = el("text", {
                    class: "pc-tick",
                    x: x(d), y: innerH + 18, fill: t.muted, "text-anchor": "middle"
                });
                label.textContent = fmt(d);
                g.appendChild(label);
            });

            // ── sealed premium band (NIB above loose) ────────────────────────
            var bothDefined = function (d) {
                return d.loose !== null && d.nib !== null;
            };
            var bandArea = d3.area()
                .defined(bothDefined)
                .x(function (d) { return x(d.date); })
                .y0(function (d) { return y(d.loose); })
                .y1(function (d) { return y(d.nib); })
                .curve(d3.curveMonotoneX);

            var bandPath = bandArea(data);
            if (bandPath) {
                g.appendChild(el("path", {
                    class: "pc-band", d: bandPath, fill: t.band
                }));
            }

            // ── lines ────────────────────────────────────────────────────────
            function lineFor(key) {
                return d3.line()
                    .defined(function (d) { return d[key] !== null; })
                    .x(function (d) { return x(d.date); })
                    .y(function (d) { return y(d[key]); })
                    .curve(d3.curveMonotoneX)(data);
            }

            var seriesDefs = [
                { key: "loose", color: t.loose, name: "Loose", samples: "looseSamples", display: "looseDisplay" },
                { key: "nib", color: t.nib, name: "NIB", samples: "nibSamples", display: "nibDisplay" }
            ];

            seriesDefs.forEach(function (s) {
                var path = lineFor(s.key);
                if (!path) return;
                g.appendChild(el("path", {
                    class: "pc-line", d: path, stroke: s.color, fill: "none"
                }));
            });

            // ── crosshair (behind the dots, above the lines) ─────────────────
            var crosshair = el("line", {
                class: "pc-crosshair", y1: 0, y2: innerH,
                stroke: t.axis, opacity: 0
            });
            g.appendChild(crosshair);

            // ── dots ─────────────────────────────────────────────────────────
            seriesDefs.forEach(function (s) {
                data.forEach(function (d) {
                    if (d[s.key] === null) return;
                    g.appendChild(el("circle", {
                        class: "pc-dot",
                        cx: x(d.date), cy: y(d[s.key]),
                        r: radius(d[s.samples]),
                        fill: s.color, stroke: t.surface, "stroke-width": RING
                    }));
                });
            });

            // ── direct end labels (selective: last point only) ───────────────
            var endLabels = [];
            seriesDefs.forEach(function (s) {
                for (var i = data.length - 1; i >= 0; i--) {
                    if (data[i][s.key] !== null) {
                        endLabels.push({
                            y: y(data[i][s.key]),
                            text: data[i][s.display],
                            color: s.color
                        });
                        break;
                    }
                }
            });
            // Nudge apart only if they would physically collide.
            if (endLabels.length === 2 && Math.abs(endLabels[0].y - endLabels[1].y) < 14) {
                var lower = endLabels[0].y > endLabels[1].y ? 0 : 1;
                endLabels[lower].y += 7;
                endLabels[1 - lower].y -= 7;
            }
            endLabels.forEach(function (lab) {
                var node = el("text", {
                    class: "pc-endlabel",
                    x: innerW + 10, y: lab.y,
                    fill: t.ink, "dominant-baseline": "middle"
                });
                node.textContent = lab.text;
                g.appendChild(node);
            });

            plot.insertBefore(svg, tooltip);

            geometry = {
                svg: svg, g: g, x: x, y: y, innerW: innerW, innerH: innerH,
                crosshair: crosshair, tokens: t, seriesDefs: seriesDefs,
                highlights: []
            };

            attachInteraction();
            if (activeIndex >= 0) showAt(activeIndex);
        }

        function nearestIndex(px) {
            var x = geometry.x;
            var bisect = d3.bisector(function (d) { return d.date; }).left;
            var date = x.invert(px);
            var i = bisect(data, date);
            if (i <= 0) return 0;
            if (i >= data.length) return data.length - 1;
            return (date - data[i - 1].date) < (data[i].date - date) ? i - 1 : i;
        }

        function clearHighlights() {
            geometry.highlights.forEach(function (n) { n.remove(); });
            geometry.highlights = [];
        }

        function showAt(index) {
            if (!geometry || index < 0 || index >= data.length) return;
            activeIndex = index;
            var d = data[index];
            var px = geometry.x(d.date);

            geometry.crosshair.setAttribute("x1", px);
            geometry.crosshair.setAttribute("x2", px);
            geometry.crosshair.setAttribute("opacity", 1);

            clearHighlights();
            geometry.seriesDefs.forEach(function (s) {
                if (d[s.key] === null) return;
                var ring = el("circle", {
                    class: "pc-dot-active",
                    cx: px, cy: geometry.y(d[s.key]), r: MAX_DOT_R + 2,
                    fill: "none", stroke: s.color, "stroke-width": 2
                });
                geometry.g.appendChild(ring);
                geometry.highlights.push(ring);
            });

            renderTooltip(d, px);
        }

        function hide() {
            if (!geometry) return;
            activeIndex = -1;
            geometry.crosshair.setAttribute("opacity", 0);
            clearHighlights();
            tooltip.classList.remove("is-visible");
        }

        // Every string here is server data; build with textContent only.
        function renderTooltip(d, px) {
            tooltip.textContent = "";

            var head = document.createElement("div");
            head.className = "pc-tt-date";
            head.textContent = d.label;
            tooltip.appendChild(head);

            geometry.seriesDefs.forEach(function (s) {
                var row = document.createElement("div");
                row.className = "pc-tt-row";

                var key = document.createElement("span");
                key.className = "pc-tt-key";
                key.style.background = s.color;
                row.appendChild(key);

                var name = document.createElement("span");
                name.className = "pc-tt-name";
                name.textContent = s.name;
                row.appendChild(name);

                var value = document.createElement("span");
                value.className = "pc-tt-value";
                value.textContent = d[s.display] || "Pending";
                row.appendChild(value);

                var samples = d[s.samples];
                var note = document.createElement("span");
                note.className = "pc-tt-note";
                note.textContent = samples
                    ? samples + " listing" + (samples === 1 ? "" : "s")
                    : "no match";
                row.appendChild(note);

                tooltip.appendChild(row);
            });

            if (d.loose !== null && d.nib !== null) {
                var premium = document.createElement("div");
                premium.className = "pc-tt-premium";
                premium.textContent =
                    "Sealed premium $" + Math.round(d.nib - d.loose);
                tooltip.appendChild(premium);
            }

            tooltip.classList.add("is-visible");

            // Flip the tooltip to whichever side has room.
            var plotW = plot.clientWidth;
            var ttW = tooltip.offsetWidth;
            var left = MARGIN.left + px + 14;
            if (left + ttW > plotW) left = MARGIN.left + px - ttW - 14;
            tooltip.style.left = Math.max(0, left) + "px";
        }

        function attachInteraction() {
            var svg = geometry.svg;

            svg.addEventListener("pointermove", function (event) {
                var rect = svg.getBoundingClientRect();
                var px = event.clientX - rect.left - MARGIN.left;
                if (px < -MARGIN.left / 2 || px > geometry.innerW + MARGIN.right / 2) {
                    hide();
                    return;
                }
                showAt(nearestIndex(Math.max(0, Math.min(geometry.innerW, px))));
            });

            svg.addEventListener("pointerleave", hide);

            svg.addEventListener("focus", function () {
                showAt(activeIndex >= 0 ? activeIndex : data.length - 1);
            });
            svg.addEventListener("blur", hide);

            svg.addEventListener("keydown", function (event) {
                var handled = true;
                switch (event.key) {
                    case "ArrowRight":
                        showAt(Math.min(data.length - 1, (activeIndex < 0 ? -1 : activeIndex) + 1));
                        break;
                    case "ArrowLeft":
                        showAt(Math.max(0, (activeIndex < 0 ? data.length : activeIndex) - 1));
                        break;
                    case "Home":
                        showAt(0);
                        break;
                    case "End":
                        showAt(data.length - 1);
                        break;
                    case "Escape":
                        hide();
                        break;
                    default:
                        handled = false;
                }
                if (handled) event.preventDefault();
            });
        }

        render();

        /*
         * Only width matters, and only a *changed* width. Rendering inserts the
         * SVG into the observed element, so its height changes every pass —
         * reacting to that would re-render forever.
         */
        var frame = null;
        function scheduleResize() {
            if ((plot.clientWidth || 0) === lastWidth) return;
            if (frame) cancelAnimationFrame(frame);
            frame = requestAnimationFrame(function () {
                frame = null;
                render();
            });
        }

        if (typeof ResizeObserver === "function") {
            new ResizeObserver(scheduleResize).observe(plot);
        } else {
            window.addEventListener("resize", scheduleResize);
        }
    }

    function boot() {
        if (typeof d3 === "undefined") return;
        Array.prototype.forEach.call(
            document.querySelectorAll("[data-price-chart]"),
            init
        );
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", boot, { once: true });
    } else {
        boot();
    }
})();
