#pragma once

class AudioService;

namespace air {

// Application-task only. The caller checks the current alert generation, sound
// preference, live volume, idle device state and shutdown state before calling.
// False consumes this attempt too: never retry this cue later in the episode.
bool TryPlayAirAlertTone(AudioService& audio);

}  // namespace air
