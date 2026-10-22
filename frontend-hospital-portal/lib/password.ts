/** The backend's password rule (app/security.py), checked here for quick feedback. */
export function passwordProblem(password: string): string | null {
  if (password.length < 10) return "Password must be at least 10 characters.";
  if (password.length > 200) return "Password must be at most 200 characters.";
  if (!/[a-z]/.test(password) || !/[A-Z]/.test(password)) {
    return "Password must include both upper and lower case letters.";
  }
  return null;
}
