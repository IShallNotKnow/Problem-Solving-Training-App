import { ThemeProvider } from './context/ThemeContext'

ReactDOM.createRoot(document.getElementById('root')).render(
    <ThemeProvider>
        <App />
    </ThemeProvider>
)