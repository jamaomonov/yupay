const API = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** Mint a short-lived guest token for an email (freely mintable; carries the
 *  email hash). Used by guest checkout and guest review submit. */
export async function mintGuestToken(email: string): Promise<string> {
  const r = await fetch(`${API}/api/v1/auth/guest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email.trim().toLowerCase() }),
  });
  if (!r.ok) throw new Error("guest-token");
  const { access_token } = (await r.json()) as { access_token: string };
  return access_token;
}
