import { supabase } from './supabase.js';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

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

    if (res.status === 204) return null;

    const data = await res.json().catch(() => null);

    if (!res.ok) {
        const error = new Error(data?.detail || 'Request failed');
        error.status = res.status;
        throw error;
    }

    return data;
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