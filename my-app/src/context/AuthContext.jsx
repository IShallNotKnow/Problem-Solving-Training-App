import { createContext, useContext, useState, useEffect } from 'react';
import { supabase } from '../utils/supabase.js';

const AuthContext = createContext();

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        // get session on mount
        supabase.auth.getSession().then(({ data: { session } }) => {
            setUser(session?.user ?? null);
            setLoading(false);
        });

        // keep in sync across tabs and session expiry
        const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
            setUser(session?.user ?? null);
        });

        return () => subscription.unsubscribe();
    }, []);

    const signUp = async(email, password) => {
        const { data, error } = await supabase.auth.signUp({ email, password });
        if (error) throw error;
        return data;
    }

    const signIn = async(email, password) => {
        const { data, error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
        return data;
    }

    const signInWithGoogle = async(redirect) => {
        const { data, error } = await supabase.auth.signInWithOAuth({
            provider: 'google',
            options: {
                redirectTo: `${window.location.origin}${redirect}`, // where to land after Google auth
            },
        })
        if (error) throw error;
        return data;
    }

    const signOut = async () => {
        await supabase.auth.signOut();
        setUser(null);
    };

    return (
        <AuthContext.Provider value={{ user, loading, signOut, signIn, signInWithGoogle, signUp }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    return useContext(AuthContext);
}