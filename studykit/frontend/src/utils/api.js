import { supabase } from './supabase.js';

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const apiFetch = async (path, options = {}) => {
    const { data: { session } } = await supabase.auth.getSession();

    const res = await fetch(`${BASE_URL}${path}`, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            ...(session?.access_token && {
                'Authorization': `Bearer ${session.access_token}`,
            }),
            ...options.headers,
        },
    });

    if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: 'Request failed' }));
        const error = new Error(body.detail || 'Request failed');
        error.status = res.status;
        throw error;
    }

    const contentType = res.headers.get('content-type');
    if (!contentType || !contentType.includes('application/json')) {
        return null;
    }

    return res.json();
};

export const apiUpload = async (path, formData) => {
    const { data: { session } } = await supabase.auth.getSession();

    const res = await fetch(`${BASE_URL}${path}`, {
        method: 'POST',
        headers: {
            ...(session?.access_token && {
                'Authorization': `Bearer ${session.access_token}`,
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