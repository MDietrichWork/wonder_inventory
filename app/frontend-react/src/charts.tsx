import type { Bootstrap } from "./types";
import { SYS_PAL } from "./lib";

// Clickable horizontal-bar list. entries: [label, value, drillValue]
export function HBars({ entries, onDrill }: { entries: [string, number, string][]; onDrill?: (v: string) => void }) {
  const mx = Math.max(...entries.map((e) => e[1]), 1);
  return (
    <>
      {entries.map((e, i) => (
        <div key={i} className={"hbar" + (onDrill ? " clickable" : "")} title={e[0]} onClick={() => onDrill?.(e[2])}>
          <div className="hlabel">{e[0]}</div>
          <div className="track"><div className="fill" style={{ width: Math.round((100 * e[1]) / mx) + "%" }} /></div>
          <div className="hval">{e[1]}</div>
        </div>
      ))}
    </>
  );
}

export function Trend({ data }: { data: Bootstrap["trend"] }) {
  if (data.length < 2) {
    return <div className="tip" style={{ padding: "24px 4px" }}>
      {data.length ? "Only one validation run so far — the trend builds as daily runs accumulate." : "No runs yet."}
    </div>;
  }
  const W = 600, H = 190, padL = 26, padB = 22, padT = 10, padR = 8;
  const iw = W - padL - padR, ih = H - padB - padT;
  const maxV = Math.max(...data.map((d) => d.count)) || 1;
  const stepX = iw / (data.length - 1);
  const x = (i: number) => padL + i * stepX;
  const y = (v: number) => padT + ih - (v / maxV) * ih;
  const pts = data.map((d, i) => `${x(i)},${y(d.count)}`).join(" ");
  const autoPts = data.map((d, i) => `${x(i)},${y(d.autoClosed)}`).join(" ");
  const area = `M${x(0)},${padT + ih} L${pts.replace(/ /g, " L")} L${x(data.length - 1)},${padT + ih} Z`;
  const grid = [0, 1, 2, 3, 4].map((g) => Math.round((maxV * g) / 4));
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label="Error trend">
      <defs><linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="var(--accent)" /><stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
      </linearGradient></defs>
      {grid.map((gv, i) => (
        <g key={i}>
          <line className="gridline" x1={padL} y1={y(gv)} x2={W - padR} y2={y(gv)} />
          <text x={padL - 5} y={y(gv) + 3} textAnchor="end">{gv}</text>
        </g>
      ))}
      <path className="area" d={area} />
      <polyline className="line" points={pts} />
      <polyline className="line auto-line" points={autoPts} />
      {data.map((d, i) => (
        <g key={i}>
          <circle className="pt" cx={x(i)} cy={y(d.count)} r="2.4"><title>{d.date}: {d.count} flagged</title></circle>
          {(i % 3 === 0 || i === data.length - 1) && (
            <text x={x(i)} y={H - 6} textAnchor="middle">{d.date.slice(5)}</text>
          )}
        </g>
      ))}
    </svg>
  );
}

export function SystemDonut({ counts, onDrill }: { counts: Record<string, number>; onDrill: (s: string) => void }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const color = (i: number) => SYS_PAL[i % SYS_PAL.length];
  const total = entries.reduce((a, b) => a + b[1], 0) || 1;
  const r = 54, cx = 66, cy = 66, sw = 20, circ = 2 * Math.PI * r;
  let offset = 0;
  const arcs = entries.map((en, i) => {
    const len = circ * (en[1] / total);
    const arc = (
      <circle key={i} cx={cx} cy={cy} r={r} fill="none" stroke={color(i)} strokeWidth={sw}
        strokeDasharray={`${len} ${circ - len}`} strokeDashoffset={-offset} transform={`rotate(-90 ${cx} ${cy})`}>
        <title>{en[0]}: {en[1]}</title>
      </circle>
    );
    offset += len;
    return arc;
  });
  return (
    <div className="donut-wrap">
      <div>
        <svg width="132" height="132" viewBox="0 0 132 132" role="img" aria-label="Errors by system">
          {arcs}
          <text x={cx} y={cy - 1} textAnchor="middle" fill="var(--text)" fontSize="21" fontWeight="800">{total}</text>
          <text x={cx} y={cy + 15} textAnchor="middle" fill="var(--text-faint)" fontSize="10">errors</text>
        </svg>
      </div>
      <div className="donut-legend">
        {entries.map((en, i) => (
          <div key={i} className="row clickable" onClick={() => onDrill(en[0])}>
            <span className="sw" style={{ background: color(i) }} />
            {en[0]}
            <span className="lv">{en[1]} · {Math.round((100 * en[1]) / total)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
