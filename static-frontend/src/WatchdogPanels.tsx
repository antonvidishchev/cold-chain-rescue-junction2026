import { dateTime, getDeviceInventory, getList, temperature, words, type Clinic, type Incident, type WatchdogEvent } from './api';
import { usePoll } from './usePoll';

export function DeviceIncidentReport({ incident }: { incident: Incident }) {
  return <>
    {incident.assessment_source === 'device_unverified' && <p className="notice">Device assessment is unverified{incident.device_reported_protocol != null ? ` · device protocol ${incident.device_reported_protocol}` : ''}. Not clinical safety certification.</p>}
    {incident.device_acknowledged_at && <p>Device knob acknowledgment reported {dateTime(incident.device_acknowledged_at)}.</p>}
    {incident.device_resolved_at && <p className="notice">Device knob completion reported {dateTime(incident.device_resolved_at)}. Operator-reported completion only; this does not establish power or temperature recovery.</p>}
  </>;
}

function EventDetail({ event }: { event: WatchdogEvent }) {
  const data = event.data || {};
  const kind = event.event || event.event_type;
  return <>
    {data.code != null && <p>Code {data.code}</p>}
    {kind === 'fridge_tamper' && <>
      <p>Fridge display mismatch · device report, not verified</p>
      <dl>
        <div><dt>Sensor temperature</dt><dd>{temperature(data.sensor_temp_c)} C</dd></div>
        <div><dt>Fridge display</dt><dd>{temperature(data.fridge_display_temp_c)} C</dd></div>
        <div><dt>Reported mismatch</dt><dd>{temperature(data.mismatch_c)} C</dd></div>
        <div><dt>Fridge mode</dt><dd>{data.fridge_mode || 'Not reported'}</dd></div>
        <div><dt>Fridge power</dt><dd>{data.fridge_power_w == null ? 'Not reported' : `${data.fridge_power_w} W`}</dd></div>
      </dl>
      {data.stocked_items && <p>Device-reported stocked items: {data.stocked_items.length ? data.stocked_items.join(', ') : 'None'}</p>}
    </>}
    {(kind === 'alarm_acknowledged' || kind === 'alarm_resolved') && <>
      <p>Alarm kind: {data.alarm_kind == null ? 'Not reported' : words(data.alarm_kind)}</p>
      {kind === 'alarm_acknowledged' && <p>Acknowledgment reported{data.acknowledged_by ? ` via ${data.acknowledged_by}` : ''}.{data.doors != null ? ` Doors: ${data.doors ? 'open' : 'closed'}.` : ''}</p>}
      {kind === 'alarm_resolved' && <>
        <p>Completion reported{data.resolved_by ? ` via ${data.resolved_by}` : ''}.</p>
        <p>Acknowledged: {data.acknowledged_at == null ? 'Not reported' : dateTime(new Date(data.acknowledged_at * 1000).toISOString())}</p>
        <p className="notice">Operator-reported completion only; this does not establish power or temperature recovery.</p>
      </>}
    </>}
  </>;
}

export function WatchdogEvents({ clinic }: { clinic: Clinic }) {
  const events = usePoll(`events:${clinic.id}`, signal => getList<WatchdogEvent>(`/events?location_id=${encodeURIComponent(clinic.id)}&limit=50`, signal), 5_000);
  return <section className="panel watchdog-panel" aria-labelledby="watchdog-heading">
    <div className="section-top"><h2 id="watchdog-heading">Device event reports</h2><span className="badge neutral">READ ONLY</span></div>
    <p className="muted">Latest 50 clinic events. Device reports are not independent recovery or clinical evidence. Late reports do not update current state.</p>
    {events.loading && <p role="status">Loading device events…</p>}
    {events.error && <p className="error" role="alert">{events.error} Last available events may be outdated.</p>}
    {events.data?.length === 0 && <p className="empty">No device events recorded for this clinic.</p>}
    <ol className="watchdog-events">{events.data?.map(event => <li key={event.id}>
      <article><h3>{words(event.event || event.event_type || 'device event')}</h3>
        <p className="muted">{event.device_id || 'Unknown device'} · {dateTime(event.ts)}</p>
        {event.result?.stale && <p className="badge warning">Late report · not current state</p>}
        <EventDetail event={event} />
      </article>
    </li>)}</ol>
  </section>;
}

export function ObservedInventory({ clinic }: { clinic: Clinic }) {
  const deviceKey = clinic.devices.map(device => device.id).sort().join(',');
  const snapshots = usePoll(`inventory:${clinic.id}:${deviceKey}`, async signal => Promise.all(clinic.devices.map(async device => ({ deviceId: device.id, snapshot: await getDeviceInventory(device.id, signal) }))));
  return <section className="panel watchdog-panel" aria-labelledby="inventory-heading">
    <div className="section-top"><h2 id="inventory-heading">Inventory observations</h2><span className="badge neutral">READ ONLY</span></div>
    <h3>Canonical inventory capacity</h3>
    <p>{clinic.used_units} units used · {clinic.free_units} units free</p>
    <p className="notice">Device-observed quantities and transfers below are separate from canonical stock. They do not update canonical totals, capacity or approved transfers.</p>
    {snapshots.loading && <p role="status">Loading device inventory…</p>}
    {snapshots.error && <p className="error" role="alert">{snapshots.error} Last available snapshots may be outdated.</p>}
    {snapshots.data?.length === 0 && <p className="empty">No devices registered for this clinic.</p>}
    {snapshots.data?.map(({ deviceId, snapshot }) => <article className="inventory-snapshot" key={deviceId}>
      <h3>Device-observed stock · {deviceId}</h3>
      {!snapshot ? <p className="empty">No inventory sync received for this device.</p> : <>
        <p>Snapshot observed {dateTime(snapshot.ts)} · stock {snapshot.stock_present ? 'present' : 'absent'} (device report)</p>
        {snapshot.inventory.length ? <div className="table-scroll" tabIndex={0} role="region" aria-label={`Observed stock for ${deviceId}`}><table><caption>Device-observed quantities (not canonical stock)</caption><thead><tr><th scope="col">Product ID</th><th scope="col">Quantity</th></tr></thead><tbody>{snapshot.inventory.map(item => <tr key={item.id}><td>{item.id}</td><td>{item.quantity}</td></tr>)}</tbody></table></div> : <p>Empty device inventory snapshot.</p>}
        {snapshot.transferred && <><h4>Device-reported transferred items</h4>{snapshot.transferred.length ? <ul>{snapshot.transferred.map(item => <li key={item.id}>{item.id} × {item.quantity}</li>)}</ul> : <p>No transferred items reported in this snapshot.</p>}</>}
      </>}
    </article>)}
  </section>;
}
