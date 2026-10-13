import { heartbeatPoints, type ActivityLane, type ActivityStripData } from '../../api/chartMath'

const LANES: Array<{ lane: ActivityLane; label: string; y: number }> = [
  { lane: 'request', label: '요청', y: 14 },
  { lane: 'process', label: '프로세스', y: 38 },
  { lane: 'file', label: '파일', y: 62 },
]
const LANE_TITLE: Record<ActivityLane, string> = { request: '실행 요청', process: '프로세스', file: '파일 변화' }
const PLOT_LEFT = 52
const PLOT_WIDTH = 204
const PULSE_Y = 92

function clock(at: number): string {
  return new Date(at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

/**
 * Recent five minutes on its side: one dot per record in its lane, a red
 * diamond for each block decision, and AIA's heartbeat underneath -- a small
 * steady beat while quiet, taller where work happened, pulsing at "now"
 * while the run is live. Display only.
 */
export function ActivityStrip({ data, live }: { data: ActivityStripData; live: boolean }) {
  const x = (position: number) => PLOT_LEFT + position * PLOT_WIDTH
  const count = (lane: ActivityLane) => data.marks.filter(mark => mark.lane === lane).length
  const label = `최근 5분 실행 요청 ${count('request')}건, 프로세스 ${count('process')}건, 파일 변화 ${count('file')}건, 차단 판정 ${data.blocks.length}건`
  return (
    <svg className={`activity-strip${live ? ' is-live' : ''}`} viewBox="0 0 260 124" role="img" aria-label={label}>
      {[1, 2, 3, 4].map(minute => <line key={minute} className="strip-grid" x1={x(minute / 5)} x2={x(minute / 5)} y1="4" y2="104" />)}
      {LANES.map(({ lane, label: name, y }) => (
        <g key={lane}>
          <text className="strip-label" x="0" y={y + 4}>{name}</text>
          <line className="strip-lane" x1={PLOT_LEFT} x2={PLOT_LEFT + PLOT_WIDTH} y1={y} y2={y} />
        </g>
      ))}
      {data.marks.map((mark, index) => (
        <circle key={`${mark.lane}:${mark.at}:${index}`} className={`strip-dot is-${mark.lane}`} cx={x(mark.position)} cy={LANES.find(item => item.lane === mark.lane)?.y} r="3.6">
          <title>{`${LANE_TITLE[mark.lane]} · ${clock(mark.at)}`}</title>
        </circle>
      ))}
      {data.blocks.map((block, index) => (
        <rect key={`block:${block.at}:${index}`} className="strip-block" x={x(block.position) - 4} y={10} width="8" height="8" transform={`rotate(45 ${x(block.position)} 14)`}>
          <title>{`차단 판정 · ${clock(block.at)}`}</title>
        </rect>
      ))}
      <text className="strip-label" x="0" y={PULSE_Y + 4}>감시</text>
      <polyline className="strip-pulse" points={heartbeatPoints(data.pulse, PLOT_LEFT, PLOT_WIDTH, PULSE_Y)} />
      {live && <circle className="strip-now" cx={PLOT_LEFT + PLOT_WIDTH} cy={PULSE_Y} r="3.5" />}
      <text className="strip-axis" x={PLOT_LEFT} y="120">5분 전</text>
      <text className="strip-axis" x={PLOT_LEFT + PLOT_WIDTH} y="120" textAnchor="end">지금</text>
    </svg>
  )
}
