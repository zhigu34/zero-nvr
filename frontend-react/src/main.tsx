import React from "react"
import ReactDOM from "react-dom/client"
import { AuthGate } from "./components/AuthGate"
import "./styles/index.css"

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthGate />
  </React.StrictMode>,
)
