import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { YinbanProvider } from './app/runtime'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <YinbanProvider><App /></YinbanProvider>
  </React.StrictMode>,
)
