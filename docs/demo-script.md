# Demo script (≈3 minutes)

**Setup:** backend + dashboard running on the laptop; Uno Q on the same WiFi
with the Thermo and Buzzer attached; dashboard open on the projector.

1. **The scene.** "This is Pharmacy Fridge A. It holds insulin and vaccines,
   both 2–8 °C. We also know two other places with free space: the backup
   fridge in the back room and the partner clinic across town."
2. **Warm the sensor.** Hold the Modulino Thermo in your hand. The curve rises,
   the card turns amber (WARNING), and after the grace period red (EXCURSION).
   **The buzzer sounds.**
3. **Acknowledge.** Click *Acknowledge* as "Pharmacist on duty". The buzzer
   stops; the alert shows who owns it.
4. **Power loss.** In the simulator, toggle *Fridge A power* off. The state
   becomes POWER_LOSS. Click *Propose transfer*: the plan shows which items go
   to which location, with capacity before and after.
5. **Approve.** "A human signs off. The AI never moves medicine on its own."
6. **The hack.** On the watchdog tab press *Simulate hacked fridge*. The
   fridge screen keeps showing 4.0 °C while it defrosts, but the Arduino sensor
   disagrees: the board sirens, the matrix shows `H1` and the dashboard shows
   the mismatch. Turn the **knob** clockwise: the siren stops, the matrix
   scrolls `ALARM ACK` then `ACK H1`, and the dashboard turns green with
   "Alarm acknowledged at the fridge". Open runbook section H1. When the
   protocol is done, turn the knob clockwise again: the matrix shows `DONE`
   and the alarm clears. (Legacy dashboard alternative: set
   the *fridge self-report* slider for a TAMPER alert.)
7. **Close.** "Monitoring is familiar. ColdChain Rescue coordinates the response."

**No board?** Use the simulator's *temperature* slider to post readings.
