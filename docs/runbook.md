# ColdChain Watchdog — Operator Runbook

**Site:** Espoonlahti Clinic (main site), Vanha Jorvaksentie 3, 02320 Espoo
**Fridge:** Pharmacy Fridge A (2–8 °C), watched by the ColdChain Watchdog (Arduino Uno Q)

Print this page and keep it next to the fridge. When the watchdog shows a
protocol number (LED matrix shows a warning sign, then `P1`…`P4`, or the
hack code `H1`; the dashboard shows the same code), follow that section
**exactly**.

**Acknowledge at the fridge first:** turn the **knob** on the watchdog
clockwise (about 5 clicks). The siren stops, two short rising beeps confirm,
the matrix scrolls `ALARM ACK` and then `ACK P1` (or your code), and the
dashboard shows "Alarm acknowledged at the fridge". The alarm stays open,
with its countdown, while you follow the protocol.

**When the protocol is done:** turn the knob clockwise again (about 5 clicks,
after `ALARM ACK` has finished). Two beeps, the matrix shows `DONE` and then
the temperature, and the alarm disappears from the dashboard. **Reset** on the
dashboard does the same.

> Demo document for the Junction 2026 prototype. Storage limits are demo
> values. In a real clinic, the product SmPC and the responsible pharmacist
> decide on use, quarantine or disposal.

---

## How the watchdog picks a protocol

1. **Safe window** = the shortest `max time out of fridge` among the medicines
   in the fridge right now (the dashboard names the limiting medicine).
2. **Reachable clinic** = drive time + **15 min** for packing and loading is
   within the safe window.
3. Protocol:

| Protocol | Condition | Meaning |
| --- | --- | --- |
| **P1** | window ≤ 60 min, at least one clinic reachable | Critical: transfer now |
| **P2** | window 61–240 min, at least one clinic reachable | Urgent: arrange transfer |
| **P3** | window > 240 min | Watch: keep closed, prepare |
| **P4** | no clinic reachable within the window | Pack on site, quarantine |

The dashboard's countdown shows the time left in the safe window, starting
from the moment the outage was detected.

---

## P1 — Critical: transfer immediately

1. Silence nothing yet. Keep the fridge door **closed**.
2. Call the **first reachable clinic** in the dashboard list (sorted by drive
   time). Say: *"Power outage at Espoonlahti Clinic, we need cold storage
   for N units of 2–8 °C medicines within the next X minutes."*
3. If they have no space, call the next reachable clinic. Stop at the first
   "yes".
4. Fetch the validated cool boxes and conditioned (not frozen) packs from
   the storeroom.
5. Pack fast: the most sensitive medicines first (the limiting medicine on
   the dashboard), freeze-sensitive items **never** in direct contact with
   packs.
6. Order a taxi or use the clinic car. Driver takes the printed transfer
   sheet (medicine list from the dashboard).
7. Record: start time, clinic name, contact person, departure time.
8. When the stock has left, press **Reset** on the dashboard.

## P2 — Urgent: arrange transfer

1. Keep the door **closed**. Check with facilities whether power will be
   back within half of the safe window.
2. Call reachable clinics **in the listed order** until one confirms space.
3. Order a courier with a cold-chain service for the confirmed clinic.
4. Prepare cool boxes; start packing 30 min before the courier arrives.
5. If power comes back before departure: cancel the courier, keep the door
   closed for 30 min, check the temperature on the dashboard, inform the
   pharmacist.
6. Record times and contacts; press **Reset** when done.

## P3 — Watch: keep closed, prepare

1. Keep the door **closed**. A closed fridge holds its temperature for a
   long time.
2. Ask facilities for the expected repair time.
3. Check the dashboard every 30 minutes.
4. If power is **not** back by half of the safe window → switch to **P2**.
5. Inform the pharmacist at the end of the shift.

## P4 — No clinic reachable in time

1. Keep the door **closed** until the cool boxes are ready.
2. Pack all medicines into validated cool boxes with conditioned packs and a
   data-logger thermometer.
3. Label the boxes **QUARANTINE — DO NOT USE** with date and time.
4. Call the **pharmacist on duty** immediately; they decide on use,
   quarantine or disposal.
5. If a clinic becomes reachable (e.g. the courier is nearby), continue
   with **P2** from step 2.

---

## H1 — Fridge data mismatch (suspected hacked fridge)

**When:** siren, matrix shows a warning sign and `H1`. The smart fridge reports
a temperature that differs by more than 2 °C from the Arduino sensor. In the
2026 supermarket-fridge attacks the controllers were set to defrost while the
screens kept showing normal values, so **the fridge screen and its app cannot
be trusted. The Arduino sensor and a handheld thermometer can.**

1. Do **not** rely on the fridge display or app. Keep the door **closed**.
2. Measure the real temperature with a handheld or data-logger thermometer
   inside the fridge. Compare with the Arduino value on the dashboard.
3. **Isolate the fridge:** unplug its network cable or Wi-Fi/gateway. Do not
   power it off yet unless the pharmacist says so.
4. Call **IT security** and report "suspected hacked refrigeration
   controller". Do not reset the controller or change its password yourself;
   it may be needed for investigation.
5. If the real temperature is **inside 2–8 °C**: keep monitoring with the
   handheld thermometer every 15 min until IT security clears the fridge.
6. If the real temperature is **outside 2–8 °C or rising**: treat it as a
   failed fridge. Use the safe window and clinic list on the dashboard, and
   follow **P1 / P2 / P4** as if the power were out (call the first reachable
   clinic, pack into validated cool boxes).
7. Call the **pharmacist on duty**; they decide on use, quarantine or disposal
   of everything that was in the fridge. Label affected boxes
   **QUARANTINE — DO NOT USE**.
8. Record: time of alarm, both temperatures, who was called. Press **Reset**
   only after steps 2–4 are done.

---

## Other watchdog alarms

| Signal | Meaning | What to do |
| --- | --- | --- |
| Matrix: warning sign + `CHECK`, 2× three short beeps | Someone sent an **unfreeze / defrost** command to a fridge that is not empty. It was blocked. | Check whether anyone at the clinic requested a defrost. If not, treat it as a possible fridge hack: call IT security. Press **Reset** after checking. |
| Matrix: warning sign + `H1`, two-tone siren for 10 s, then a chirp every 5 s | Smart fridge and Arduino sensor disagree by more than 2 °C: possible **hacked fridge**. | Follow section **H1** above. |
| Matrix: scrolling `CLOSE THE DOORS`, seatbelt-style chime for 15 s | Fridge door left open. | Close the door. Check the temperature on the dashboard after 10 min. |
| Matrix: scrolling `ACK P1` / `ACK H1` / `ACK CHECK` | The alarm was acknowledged with the knob and is still being handled. | Continue the protocol; when done, turn the knob clockwise again (or press **Reset**). |
| Matrix: temperature only | Normal. | — |

Unfreeze with an **empty** fridge is allowed and is only logged.
Power outage with an **empty** fridge needs no action.

---

## Nearby clinics (from the main site)

| # | Clinic | City | Switchboard | Drive (min) | Cold storage (units) | After hours |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Jorvi Hospital (HUS) | Espoo | +358 9 4711 | 16 | 60 | yes |
| 2 | Meilahti Tower Hospital (HUS) | Helsinki | +358 9 4711 | 25 | 80 | yes |
| 3 | Peijas Hospital (HUS) | Vantaa | +358 9 4711 | 36 | 45 | yes |
| 4 | Lohja Hospital (HUS) | Lohja | +358 9 4711 | 40 | 30 | no |
| 5 | Porvoo Hospital (HUS) | Porvoo | +358 9 4711 | 55 | 25 | no |
| 6 | Raasepori Hospital | Raasepori | +358 29 151 2000 | 65 | 15 | yes |
| 7 | Kanta-Häme Central Hospital | Hämeenlinna | +358 3 6291 | 80 | 50 | yes |
| 8 | Päijät-Häme Central Hospital | Lahti | +358 3 819 11 | 90 | 55 | no |
| 9 | Turku University Hospital (TYKS) | Turku | +358 2 313 0000 | 105 | 75 | yes |
| 10 | Tampere University Hospital (TAYS) | Tampere | +358 3 311 611 | 120 | 70 | yes |

Drive times are estimates. Cold-storage capacity and after-hours acceptance
are demo values. Switchboard numbers for HUS and Raasepori were checked
online; the others must be verified before real use.
