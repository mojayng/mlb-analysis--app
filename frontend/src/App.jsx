import { useEffect, useState } from "react";
import "./App.css";

// Formatting helpers. They check `== null` (null OR undefined) rather than
// using `||`, because a real value of 0 is falsy in JavaScript and would be
// wrongly shown as "No data" by `||`.
const fixed = (v) => (v == null ? "No data" : Number(v).toFixed(2));
const percent = (v) => (v == null ? "No data" : `${(Number(v) * 100).toFixed(0)}%`);

// Two different kinds of "missing", shown differently on purpose:
//   TBD     -> the team hasn't announced a starter yet
//   No data -> starter is known, but he has no first-inning history in our DB
function PitcherCells({ row }) {
  if (row.pitcher_name == null) {
    return (
      <td colSpan={5} className="tbd">
        TBD
      </td>
    );
  }
  return (
    <>
      <td>{row.pitcher_name}</td>
      <td>{row.fi_starts ?? "No data"}</td>
      <td>{percent(row.shrunk_nrfi_rate)}</td>
      <td>{fixed(row.raw_1st_inn_era)}</td>
      <td>{fixed(row.shrunk_1st_inn_era)}</td>
    </>
  );
}

export default function App() {
  // State = data that, when it changes, makes React re-render the page.
  const [rows, setRows] = useState([]);
  const [postseason, setPostseason] = useState(true);
  const [status, setStatus] = useState("loading"); // loading | ready | error

  // useEffect runs after render. The dependency array [postseason] means
  // "re-fetch whenever the checkbox changes".
  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");

    fetch(`/api/probables?postseason=${postseason}`, { signal: controller.signal })
      .then((res) => {
        // fetch() only rejects on network failure; HTTP errors (like 500)
        // still "succeed", so we check res.ok ourselves.
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        if (!Array.isArray(data)) throw new Error("Unexpected response shape");
        setRows(data);
        setStatus("ready");
      })
      .catch((err) => {
        if (err.name !== "AbortError") setStatus("error");
      });

    // Cleanup: cancel the in-flight request if the user toggles again quickly,
    // so an old slow response can't overwrite a newer one (a race condition).
    return () => controller.abort();
  }, [postseason]);

  return (
    <main>
      <h1>MLB First-Inning Analysis</h1>
      <p className="sub">
        Probable starters with regular-season first-inning stats. Shrunk values
        pull small samples toward the league average.
      </p>

      <label>
        <input
          type="checkbox"
          checked={postseason}
          onChange={(e) => setPostseason(e.target.checked)}
        />{" "}
        Postseason only
      </label>

      {status === "loading" && <p>Loading...</p>}
      {status === "error" && (
        <p className="error">Couldn't reach the API. Is `python app.py` running?</p>
      )}
      {status === "ready" && rows.length === 0 && <p>No games found.</p>}

      {status === "ready" && rows.length > 0 && (
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Team</th>
                <th>Opponent</th>
                <th>Starter</th>
                <th>1st-inn starts</th>
                <th>NRFI % (shrunk)</th>
                <th>1st-inn ERA (raw)</th>
                <th>1st-inn ERA (shrunk)</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                // key helps React track which row is which between renders.
                <tr key={`${row.game_pk ?? row.date}-${row.team}`}>
                  <td>{row.date}</td>
                  <td>{row.team}</td>
                  <td>{row.opponent}</td>
                  <PitcherCells row={row} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
