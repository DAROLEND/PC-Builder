import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/useAuth";
import type { MessageKey } from "../i18n/en";
import { LANGS, useI18n } from "../i18n/context";

const NAV: [string, MessageKey][] = [
  ["/configurator", "nav.configurator"],
  ["/catalog", "nav.catalog"],
  ["/builds", "nav.builds"],
  ["/advisor", "nav.advisor"],
  ["/stats", "nav.stats"],
];

/**
 * Floating, centred header. The highlighted "pill" is a single element that
 * slides to the active link (measured after layout), instead of every link
 * getting its own background.
 */
export function Layout() {
  const { user, logout } = useAuth();
  const { t, lang, setLang } = useI18n();
  const location = useLocation();
  const [scrolled, setScrolled] = useState(false);
  const navRef = useRef<HTMLElement>(null);
  const [box, setBox] = useState<{ left: number; width: number } | null>(null);

  // Re-measure when the active link, its text (language) or the link set changes.
  useLayoutEffect(() => {
    const measure = () => {
      const active = navRef.current?.querySelector<HTMLElement>("a.active");
      setBox(active ? { left: active.offsetLeft, width: active.offsetWidth } : null);
    };
    measure();
    window.addEventListener("resize", measure);
    document.fonts?.ready.then(measure).catch(() => undefined);
    return () => window.removeEventListener("resize", measure);
  }, [location.pathname, lang, user]);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const links: [string, MessageKey][] = user ? [...NAV, ["/orders", "nav.orders"]] : NAV;

  return (
    <div className="app">
      <div className="backdrop" aria-hidden="true" />
      <header className={`header ${scrolled ? "scrolled" : ""}`}>
        <div className="header-bar">
          <NavLink to="/" className="brand" aria-label="PC Builder">
            <span className="brand-mark" aria-hidden="true">
              <span />
            </span>
            <span className="brand-text">
              PC<b>Builder</b>
            </span>
          </NavLink>

          <nav className="capsule" ref={navRef} aria-label="Main">
            {box && (
              <span
                className="capsule-indicator"
                style={{ transform: `translateX(${box.left}px)`, width: box.width }}
                aria-hidden="true"
              />
            )}
            {links.map(([to, key]) => (
              <NavLink key={to} to={to} className="capsule-link">
                {t(key)}
              </NavLink>
            ))}
          </nav>

          <div className="header-actions">
            <div className="lang-switch" role="group" aria-label="Language">
              {LANGS.map((code) => (
                <button
                  key={code}
                  className={code === lang ? "active" : ""}
                  aria-pressed={code === lang}
                  onClick={() => setLang(code)}
                >
                  {code.toUpperCase()}
                </button>
              ))}
            </div>
            {user ? (
              <>
                <NavLink
                  to="/profile"
                  className="avatar"
                  title={t("nav.profile")}
                  aria-label={t("nav.profile")}
                >
                  {user.username.slice(0, 1).toUpperCase()}
                </NavLink>
                <button className="ghost small" onClick={logout}>
                  {t("nav.logout")}
                </button>
              </>
            ) : (
              <>
                <NavLink to="/login" className="header-link">
                  {t("nav.login")}
                </NavLink>
                <NavLink to="/register" className="button small">
                  {t("nav.signup")}
                </NavLink>
              </>
            )}
          </div>
        </div>
      </header>

      {/* key → the enter animation replays on every navigation */}
      <main className="container page" key={location.pathname}>
        <Outlet />
      </main>
      <footer className="footer muted small">
        PC Builder · Django + DRF · React + TanStack Query · {t("footer.prices")} ·{" "}
        <a href="/api/docs/">API docs</a>
      </footer>
    </div>
  );
}
