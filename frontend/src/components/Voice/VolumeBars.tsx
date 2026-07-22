import { useRef, useEffect } from 'react';

interface VolumeBarsProps {
  analyser: AnalyserNode | null;
  barCount?: number;
  maxHeight?: number;
  className?: string;
}

/**
 * Simple single-bar volume indicator.
 * Green at rest, lights up blue/red proportional to audio level.
 */
export function VolumeBars({ analyser, maxHeight = 12, className = '' }: VolumeBarsProps) {
  const barRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    if (!analyser) return;

    const dataArray = new Uint8Array(analyser.frequencyBinCount);

    const tick = () => {
      analyser.getByteFrequencyData(dataArray);
      let sum = 0;
      for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
      const pct = Math.min(sum / dataArray.length / 200, 1); // 0..1

      if (barRef.current) {
        barRef.current.style.transform = `scaleX(${Math.max(0.04, pct)})`;
      }
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [analyser]);

  return (
    <div
      className={className}
      style={{ width: 24, height: maxHeight, display: 'flex', alignItems: 'center' }}
    >
      <div
        style={{
          width: '100%',
          height: 3,
          borderRadius: 2,
          background: '#e2e8f0', // slate-200 — track
          overflow: 'hidden',
        }}
      >
        <div
          ref={barRef}
          style={{
            width: '100%',
            height: '100%',
            borderRadius: 2,
            background: '#22c55e', // green-500
            transformOrigin: 'left center',
            transform: 'scaleX(0.04)',
            transition: 'transform 80ms linear',
          }}
        />
      </div>
    </div>
  );
}
