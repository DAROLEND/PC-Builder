const ACCESS = "pcb.access";
const REFRESH = "pcb.refresh";

type Listener = () => void;
const listeners = new Set<Listener>();

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // Storage may be unavailable (private mode); the session then lasts one tab.
  }
}

export const tokenStore = {
  get access() {
    return read(ACCESS);
  },
  get refresh() {
    return read(REFRESH);
  },
  set(access: string, refresh: string) {
    write(ACCESS, access);
    write(REFRESH, refresh);
    listeners.forEach((fn) => fn());
  },
  clear() {
    write(ACCESS, null);
    write(REFRESH, null);
    listeners.forEach((fn) => fn());
  },
  subscribe(fn: Listener) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
};
