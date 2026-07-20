import { createContext, useContext } from 'react';
import { message } from 'antd';

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
    const [messageApi, contextHolder] = message.useMessage();

    const toast = {
        error: (content) => messageApi.error(content, 3),
        success: (content) => messageApi.success(content, 3),
        warning: (content) => messageApi.warning(content, 3),
    };

    return (
        <ToastContext.Provider value={toast}>
            {contextHolder}
            {children}
        </ToastContext.Provider>
    );
}

export function useToast() {
    return useContext(ToastContext);
}