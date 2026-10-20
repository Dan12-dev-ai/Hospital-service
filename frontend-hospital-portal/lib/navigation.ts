/**
 * A full page load, on purpose: after signing in or out (or when the
 * session is gone) every piece of client state must be dropped and the
 * proxy must see the new cookie, which a client-side transition would not do.
 */
export function hardNavigate(path: string) {
  window.location.assign(path);
}
