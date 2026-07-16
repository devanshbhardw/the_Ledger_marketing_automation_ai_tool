"use client";

export default function Sparkline({
  points,
  height = 30,
}: {
  points: number[];
  height?: number;
}) {
  if (points.length < 2) return <div className="ledger-spark-empty" style={{ height }} />;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const coords = points
    .map((v, i) => {
      const x = (i / (points.length - 1)) * 100;
      const y = 27 - ((v - min) / span) * 24;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      className="ledger-spark"
      style={{ height }}
      viewBox="0 0 100 30"
      preserveAspectRatio="none"
      aria-hidden
    >
      <polyline points={coords} />
    </svg>
  );
}
