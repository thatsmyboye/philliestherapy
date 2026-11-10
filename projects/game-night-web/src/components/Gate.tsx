import { env } from "@/lib/env";
import { discordReady, type User } from "@/lib/users";

/**
 * Sign-in and Discord prompts shared by the gated pages. Returns null when the
 * user is signed in with Discord linked and in the server.
 */
export function AccessGate({ user, next, what }: { user: User | null; next: string; what: string }) {
  if (!user) {
    return (
      <div className="card stack">
        <h2>Sign in to {what}</h2>
        <p className="muted">Game Night uses your Patreon account to check your membership. We only read your name and your Phillies Therapy tier.</p>
        <div className="row">
          <a className="btn" href={`/auth/patreon?next=${encodeURIComponent(next)}`}>
            Sign in with Patreon
          </a>
        </div>
      </div>
    );
  }
  if (!user.discord_user_id) {
    return (
      <div className="card stack">
        <h2>Link your Discord</h2>
        <p className="muted">One more step to {what}. Linking Discord confirms you&apos;re in the Phillies Therapy server and gives us the name to show on the board.</p>
        <div className="row">
          <a className="btn btn-blue" href={`/auth/discord?next=${encodeURIComponent(next)}`}>
            Link Discord
          </a>
        </div>
      </div>
    );
  }
  if (!discordReady(user)) {
    const invite = env.discordInviteUrl();
    return (
      <div className="card stack">
        <h2>Join the server</h2>
        <p className="muted">
          Your Discord account ({user.discord_username}) is linked but isn&apos;t in the Phillies Therapy server yet. Join, then check again.
        </p>
        <div className="row">
          {invite && (
            <a className="btn" href={invite} target="_blank" rel="noreferrer">
              Join the Discord
            </a>
          )}
          <a className="btn btn-ghost" href={`/auth/discord?next=${encodeURIComponent(next)}`}>
            Check again
          </a>
        </div>
      </div>
    );
  }
  return null;
}

export function needsGate(user: User | null): boolean {
  return !user || !discordReady(user);
}
