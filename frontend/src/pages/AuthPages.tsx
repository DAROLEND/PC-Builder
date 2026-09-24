import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/useAuth";
import { ErrorMessage } from "../components/ui";
import { useI18n } from "../i18n/context";

function useRedirectBack() {
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/builds";
  return () => navigate(from, { replace: true });
}

export function LoginPage() {
  const { login } = useAuth();
  const { t } = useI18n();
  const done = useRedirectBack();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  return (
    <form
      className="panel auth"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          await login(username, password);
          done();
        } catch (err) {
          setError(err);
        } finally {
          setBusy(false);
        }
      }}
    >
      <h1>{t("auth.login")}</h1>
      <label>
        {t("auth.username")}
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
        />
      </label>
      <label>
        {t("auth.password")}
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
      </label>
      <button type="submit" disabled={busy}>
        {busy ? t("auth.loggingIn") : t("auth.login")}
      </button>
      <ErrorMessage error={error} />
      <p className="muted small">
        {t("auth.demo")} {t("auth.noAccount")} <Link to="/register">{t("auth.signup")}</Link>
      </p>
    </form>
  );
}

export function RegisterPage() {
  const { register } = useAuth();
  const { t } = useI18n();
  const done = useRedirectBack();
  const [form, setForm] = useState({ username: "", email: "", password: "" });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const field = (key: keyof typeof form) => ({
    value: form[key],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm({ ...form, [key]: e.target.value }),
  });

  return (
    <form
      className="panel auth"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          await register(form.username, form.email, form.password);
          done();
        } catch (err) {
          setError(err);
        } finally {
          setBusy(false);
        }
      }}
    >
      <h1>{t("auth.signup")}</h1>
      <label>
        {t("auth.username")}
        <input {...field("username")} autoComplete="username" required />
      </label>
      <label>
        {t("auth.email")}
        <input type="email" {...field("email")} autoComplete="email" required />
      </label>
      <label>
        {t("auth.password")}
        <input
          type="password"
          {...field("password")}
          autoComplete="new-password"
          minLength={8}
          required
        />
      </label>
      <button type="submit" disabled={busy}>
        {busy ? t("auth.creating") : t("auth.create")}
      </button>
      <ErrorMessage error={error} />
      <p className="muted small">
        {t("auth.haveAccount")} <Link to="/login">{t("auth.login")}</Link>
      </p>
    </form>
  );
}
