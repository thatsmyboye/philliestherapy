import type { Metadata } from "next";
import { listStandings } from "@/lib/episodes";

export const metadata: Metadata = { title: "Standings" };
export const dynamic = "force-dynamic";

export default async function Standings() {
  const rows = await listStandings();
  return (
    <div className="stack">
      <p className="light">Hot Stove League</p>
      <h1 style={{ fontSize: "clamp(2rem, 7vw, 3.5rem)" }}>Standings</h1>
      <p className="muted">Three points for a win, one per run scored, two for Player of the Game. The top three after Episode 3 play the Championship.</p>

      {rows.length === 0 ? (
        <div className="card">
          <h2>No games yet</h2>
          <p className="muted" style={{ marginTop: 8 }}>The table fills in after the first episode.</p>
        </div>
      ) : (
        <div className="card table-scroll">
          <table>
            <thead>
              <tr>
                <th>Contestant</th>
                <th>W</th>
                <th>Runs</th>
                <th>POTG</th>
                <th>Pts</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.name} className={i < 3 ? "lead" : undefined}>
                  <td className="name">{r.name}</td>
                  <td>{r.wins}</td>
                  <td>{r.runs}</td>
                  <td>{r.potg}</td>
                  <td className="pts">{r.points}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
