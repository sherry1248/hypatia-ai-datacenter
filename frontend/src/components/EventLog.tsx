import type { EventEntry } from '../types';

export function EventLog({ events }: { events: EventEntry[] }) {
  return <section className="event-log"><div className="event-heading"><strong>이벤트 로그</strong><span>최근 활동</span></div><div className="event-items">{events.map((event) => <div className="event" key={event.id}><time>{event.time}</time><span className={`event-level ${event.level}`} /> <p>{event.message}</p></div>)}</div></section>;
}
