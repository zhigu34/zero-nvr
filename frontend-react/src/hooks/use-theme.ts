import { useEffect, useState } from "react"

const STORAGE_KEY = "zero-nvr-theme"
type Theme = "light" | "dark"

function readInitial(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === "light" || stored === "dark") return stored
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light"
}

/**
 * Applies the theme to <html>, never to a wrapper element — see the note in
 * styles/index.css for why a nested `.dark` div silently breaks the sidebar
 * aliases declared in theme.css.
 */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readInitial)

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark")
    localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  return {
    theme,
    isDark: theme === "dark",
    toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
  }
}
