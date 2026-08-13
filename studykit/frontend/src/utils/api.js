import { supabase } from './supabase.js';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

// Exported so every caller (including the SSE stream) targets the same origin.
// Hardcoding a URL anywhere else silently breaks when VITE_API_BASE_URL is
// missing at build time: the hardcoded call keeps working while every other
// request goes to localhost and is blocked by CSP/mixed-content.
export const apiBaseUrl = BASE_URL;

if (import.meta.env.PROD && !import.meta.env.VITE_API_BASE_URL) {
    // Fail loudly at boot instead of surfacing as an opaque "Generation failed".
    console.error(
        '[config] VITE_API_BASE_URL is not set in this production build — ' +
        'API calls will target http://localhost:8000 and be blocked by CSP.'
    );
}

export const getAccessToken = async () => {
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) throw new Error('No active session');
    return session.access_token;
};

export const apiFetch = async (path, options = {}) => {
    const accessToken = await getAccessToken();

    let res;
    try {
        res = await fetch(`${BASE_URL}${path}`, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...(accessToken && {
                    'Authorization': `Bearer ${accessToken}`,
                }),
                ...options.headers,
            },
        });
    } catch (cause) {
        // fetch() only rejects for transport-level failures (DNS, CORS, CSP,
        // mixed content, offline). These carry no status, so without this the
        // UI reports a misleading generic error and the request never appears
        // in server logs — making it look like a backend bug.
        const error = new Error(
            `Could not reach the server at ${BASE_URL}. Check VITE_API_BASE_URL, CORS and CSP settings.`
        );
        error.status = 0;
        error.isNetworkError = true;
        error.cause = cause;
        throw error;
    }

    if (res.status === 204) return null;

    const data = await res.json().catch(() => null);

    if (!res.ok) {
        const error = new Error(data?.detail || data?.error || `Request failed (${res.status})`);
        error.status = res.status;
        throw error;
    }

    return data;
};

export const apiUpload = async (path, formData) => {
    const accessToken = await getAccessToken();

    const res = await fetch(`${BASE_URL}${path}`, {
        method: 'POST',
        headers: {
            ...(accessToken && {
                'Authorization': `Bearer ${accessToken}`,
            }),
        },
        body: formData,
    });

    if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: 'Upload failed' }));
        const error = new Error(body.detail || 'Upload failed');
        error.status = res.status;
        throw error;
    }

    return res.json();
};