import { BrowserRouter, Routes, Route } from 'react-router-dom'
import App from './pages/StudyPage.jsx'
import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'


function App() {
    return (
        <BrowserRouter>
            <Routes>
                <Route path="/" element={<HomePage />} />
                <Route path="/login" element={<LoginPage />} />
                <Route path="/study" element={<StudyPage />} />
            </Routes>
        </BrowserRouter>
    )
}