/**
 * SquidCode browser runtime.
 * Reads session ID from <meta>, connects SSE, updates DOM.
 * Injected into pages by the ICAP server.
 */
(function() {
    var meta = document.querySelector('meta[name="squidcode-session"]');
    if (!meta) return;

    var sid = meta.getAttribute('content');
    if (!sid) return;

    var origin = '{{SSE_ORIGIN}}';
    var url = origin + '/squidcode/sse/' + sid;

    var es = new EventSource(url);

    es.onopen = function() {
        console.log('[squidcode] SSE connected, session=' + sid);
    };

    es.onmessage = function(e) {
        try {
            var d = JSON.parse(e.data);
        } catch (err) {
            return;
        }

        var el = document.querySelector('[data-ai-id="' + d.id + '"]');
        if (!el) return;

        // Update text
        el.textContent = d.text;

        // Brief highlight animation
        el.style.transition = 'background-color 0.3s ease';
        el.style.backgroundColor = 'rgba(100, 200, 255, 0.2)';
        setTimeout(function() {
            el.style.backgroundColor = '';
        }, 600);
    };

    es.onerror = function() {
        console.warn('[squidcode] SSE connection error, will retry');
    };
})();
