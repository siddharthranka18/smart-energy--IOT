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

const demoLoads = [
  { target: 'light', label: 'light', led: 'yellow' },
  { target: 'fan', label: 'fan', led: 'blue' },
  { target: 'ac', label: 'AC', led: 'orange' },
];

function EquipmentDemo({ room, ready, allTargets }) {
  const [sending, setSending] = useState(null);
  const [message, setMessage] = useState('');
  const allOff = !room.light_on && !room.fan_on && !room.ac_on;

  async function start({ target, led }) {
    setSending(target);
    setMessage('');
    try {
      const intent = `${target}-demo`;
      const response = await fetch('/api/rooms/' + encodeURIComponent(room.device_id) + '/' + intent, {
        method: 'POST',
        headers: { 'X-Demo-Intent': intent },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not start the equipment demo.');
      }
      setMessage(`Demo requested. Watch the ${led} LED, then look for a new Confirmed action below.`);
    } catch (failure) {
      setMessage(failure.message);
    } finally {
      setSending(null);
    }
  }

  return <div className="demo">
    <div className="demo-buttons">
      {(allTargets ? demoLoads : demoLoads.slice(0, 1)).map(load =>
        <button key={load.target} type="button" onClick={() => start(load)}
          disabled={sending !== null || !ready || room.occupied || !allOff}>
          {sending === load.target ? 'Sending…' : `Simulate ${load.label} left on`}
        </button>)}
    </div>
    <p role="status">{message || 'Start Wokwi and leave the room empty with all equipment off.'}</p>
  </div>;
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
        const [room, history, control] = id ? await Promise.all([
          get(path, controller.signal),
          get(path + '/telemetry?limit=60', controller.signal),
          'auto_light_off' in health ? get(path + '/control-actions', controller.signal) : null,
        ]) : [];
        setData({ health, rooms, room, history, control, totals: rooms.find(item => item.device_id === id) });
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

  const { health, rooms = [], room, history, control, totals } = data ?? {};
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
      {control && <section className="panel control">
        <h2>Automatic equipment shutoff</h2>
        <p>{(health.auto_load_off ?? health.auto_light_off) ? 'Enabled' : 'Disabled'} · Acts when an unoccupied room reports equipment still on.</p>
        {(health.equipment_demo_available || health.light_demo_available) &&
          <EquipmentDemo key={room.device_id} room={room} allTargets={health.equipment_demo_available}
            ready={health.mqtt_connected && !stale && !error} />}
        {control.actions.length === 0 && <p>No shutoff actions recorded.</p>}
        {control.actions.map(action => <article key={action.command_id} className="action">
          <div className="axis">
            <strong>{action.reason}</strong>
            <span className="action-status" data-ok={action.status === 'confirmed'}>
              {{ pending: 'Pending', confirmed: 'Confirmed', failed: 'Failed', timed_out: 'Timed out' }[action.status]}
            </span>
          </div>
          <p>{time(action.started_at)} · {({ light: 'Light', fan: 'Fan', ac: 'AC', all: 'Light, fan and AC' })[action.target ?? 'light']} off · Before {number(action.before_w)} W
            {action.after_w != null && ` → After ${number(action.after_w)} W`}
            {action.finished_at && ` · Result at ${time(action.finished_at)}`}
          </p>
          {action.detail && <p>{action.detail}</p>}
        </article>)}
      </section>}
    </>}
  </main>;
}

createRoot(document.getElementById('root')).render(<App />);
