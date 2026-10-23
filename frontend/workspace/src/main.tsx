import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/inter/wght.css'
import '../../src/design.css'
import './workspace.css'
import Workspace from './Workspace'

createRoot(document.getElementById('root')!).render(<StrictMode><Workspace /></StrictMode>)
