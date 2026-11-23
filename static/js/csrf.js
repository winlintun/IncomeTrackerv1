(function () {
    const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
    const nativeFetch = window.fetch.bind(window);

    function getCsrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') || '' : '';
    }

    function setCsrfToken(token) {
        let meta = document.querySelector('meta[name="csrf-token"]');
        if (!meta) {
            meta = document.createElement('meta');
            meta.name = 'csrf-token';
            document.head.appendChild(meta);
        }
        meta.setAttribute('content', token || '');
    }

    async function refreshCsrfToken() {
        try {
            const res = await nativeFetch('/api/auth/csrf-token', { credentials: 'same-origin' });
            if (res.ok) {
                const data = await res.json();
                if (data && data.csrf_token) {
                    setCsrfToken(data.csrf_token);
                    return data.csrf_token;
                }
            }
        } catch (e) {
            return '';
        }
        return getCsrfToken();
    }

    window.getCsrfToken = getCsrfToken;
    window.refreshCsrfToken = refreshCsrfToken;

    window.fetch = function (input, init) {
        const options = init ? { ...init } : {};
        const method = (options.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
        const url = typeof input === 'string' ? input : (input && input.url ? input.url : '');
        const isApiPath = url.startsWith('/api/') || url.startsWith(window.location.origin + '/api/');

        if (isApiPath && MUTATING_METHODS.has(method)) {
            const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
            const token = getCsrfToken();
            if (token && !headers.has('X-CSRF-Token')) {
                headers.set('X-CSRF-Token', token);
            }
            options.headers = headers;
            if (!options.credentials) {
                options.credentials = 'same-origin';
            }
        }
        return nativeFetch(input, options);
    };
})();
