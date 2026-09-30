# Fix at the right layer

Pillar: repairability

**Rule.** Trace each symptom to its root cause and fix it once, at the layer that owns it (the shared hook, the primitive, the config), not at each call site. It is still the smallest change that removes the cause.

**Applies when.** Debugging, or when the same fix is about to go into a second place.

**Changes.** You reproduce first, ask why until you reach the cause, and fix there. When the durable fix is much larger than a patch, you name the trade-off and let the operator choose.

**Counter-example.** A null check added at the crash site that silences the crash while the value stays wrong upstream.
