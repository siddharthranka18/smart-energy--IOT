import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

async function get(path, signal) {
  const response = await fetch('/api' + path, { signal });
  if (!response.ok) throw new Error(`${path} returned HTTP ${response.status}`);
  return response.json();
}

const number = (value, digits = 1) => Number.isFinite(value)
  ? value.toLocaleString(undefined, { maximumFractionDigits: digits })
  : '—';
const time = value => new Date(value).toLocaleTimeString();

function Metric({ label, value, unit }) {
  return <div className="metric"><span>{label}</span><strong>{value} <small>{unit}</small></strong></div>;
}

function PowerHistory({ samples }) {
  const history = [...samples].reverse();
  const maximum = Math.max(1, ...history.map(sample => sample.power_w));
  return <section className="panel">
    <h2>Power history</h2>
    {history.length ? <>
      <p>Latest {history.length} readings · peak {number(maximum === 1 ? Math.max(...history.map(s => s.power_w)) : maximum)} W</p>
      <div className="bars" aria-label="Power readings from oldest to newest">
        {history.map((sample, index) => <div key={index}
          style={{ height: `${Math.max(1, sample.power_w / maximum * 100)}%` }}
          title={`${time(sample.received_at)} · ${number(sample.power_w)} W`} />)}
      </div>
      <div className="axis"><span>{time(history[0].received_at)}</span><span>{time(history.at(-1).received_at)}</span></div>
    </> : <p>Waiting for readings.</p>}
  </section>;
}

function App() {
  const [selection, select] = useState('');
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    let timer;
    async function poll() {
      try {
        const health = await get('/health', controller.signal);
        if (health.database !== 'ok') {
          setData({ health, rooms: [] });
          throw new Error('PostgreSQL is unavailable. Check DATABASE_URL and restart the backend.');
        }
        const { rooms } = await get('/rooms', controller.signal);
        const id = rooms.some(room => room.device_id === selection) ? selection : rooms[0]?.device_id;
        const path = '/rooms/' + encodeURIComponent(id ?? '');
        const [room, history] = id ? await Promise.all([
          get(path, controller.signal),
          get(path + '/telemetry?limit=60', controller.signal),
        ]) : [];
        setData({ health, rooms, room, history, totals: rooms.find(item => item.device_id === id) });
        setError('');
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure.message);
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(poll, 2500);
      }
    }
    poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [selection]);

  const { health, rooms = [], room, history, totals } = data ?? {};
  const stale = room && Date.now() - Date.parse(room.received_at) > 30000;
  return <main>
    <header>
      <div><p className="eyebrow">SMART BUILDING · WOKWI SIMULATION</p><h1>Energy monitor</h1></div>
      <div className="connections">
        <span data-ok={!error && health?.database === 'ok'}>Database {error && health?.database === 'ok' ? 'unverified' : health?.database ?? 'checking'}</span>
        <span data-ok={!error && health?.mqtt_connected}>MQTT {error && health?.mqtt_connected ? 'unverified' : health?.mqtt_connected ? 'connected' : 'offline'}</span>
      </div>
    </header>
    {error && <p className="warning" role="status">{error}</p>}
    {!room && <section className="panel"><h2>{error ? 'Telemetry unavailable' : data ? 'Waiting for room telemetry' : 'Connecting to backend'}</h2>
      <p>Start the backend and run the Wokwi simulation. Rooms appear when their first reading is stored.</p></section>}
    {room && <>
      <div className="room-header">
        <label>Room <select value={room.device_id} onChange={event => select(event.target.value)}>
          {rooms.map(item => <option key={item.device_id}>{item.device_id}</option>)}
        </select></label>
        <p>{stale || error ? 'Last known reading' : 'Latest reading'} · {time(room.received_at)}</p>
      </div>
      <div className="metrics">
        <Metric label="Simulated power" value={number(room.power_w)} unit="W" />
        <Metric label="Stored energy" value={number(totals.server_energy_kwh, 4)} unit="kWh" />
        <Metric label="Estimated cost" value={number(totals.server_cost_inr, 4)} unit="INR" />
        <Metric label="Temperature" value={number(room.temperature_c)} unit="°C" />
      </div>
      <div className="details">
        <PowerHistory samples={history.samples} />
        <section className="panel">
          <h2>Room conditions</h2>
          <p>{room.occupied ? 'Occupied' : 'Unoccupied'} · {room.is_dark ? 'Dark' : 'Bright'} · {room.control_mode.replaceAll('_', ' ')}</p>
          <dl>{[['Light', room.light_on], ['Fan', room.fan_on], ['AC', room.ac_on]].map(([name, on]) =>
            <div key={name}><dt>{name}</dt><dd data-on={on}>{on ? 'On' : 'Off'}</dd></div>)}</dl>
        </section>
      </div>
      <section className="panel">
        <h2>{stale || error ? 'Alerts at last reading' : 'Current alerts'}</h2>
        {room.high_power_alert && <p className="warning">High power consumption</p>}
        {room.unoccupied_power_alert && <p className="warning">Power draw in an unoccupied room</p>}
        {!room.high_power_alert && !room.unoccupied_power_alert && <p>No alerts on this reading.</p>}
      </section>
    </>}
  </main>;
}

createRoot(document.getElementById('root')).render(<App />);
