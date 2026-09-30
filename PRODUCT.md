# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The current user prepares tracks on this machine for their own DJ sets. A later, more seamless integration of the program is a stated plan and is not specified yet.

## Product Purpose

StemLab separates a local WAV or MP3 into vocals, drums, bass, and other instruments, or into a chosen mix of those sources, so the user can preview and download the result. Success is a finished job the user can hear and take with them, with the original file still available.

## Positioning

Separation runs on the user's own hardware. Audio does not leave the machine, and the app does not depend on a paid API. Cue points already stored in Mixxx or Rekordbox can mark the section to process.

## Operating Context

The user works at one computer, often with a DJ library already in Mixxx or Rekordbox. They drop a track, choose an output, optionally mark a section from the waveform or from hot cues, start separation, then preview and download from the job history. Jobs persist across reloads and restarts. Processing can take minutes and shows real stages.

## Capabilities and Constraints

Confirmed workflows that a visual change must keep:

- Output modes: vocals only, no vocals, all four stems, and a custom mix of vocals, drums, bass, and other.
- Optional section of a track, with waveform, cue markers, stretch selection, typed times, section preview, and whole-track reset. Cues come from WAV markers, a Rekordbox XML export, and the local Mixxx library.
- Per-job separation quality: vocal model, drums/bass/other model, instrument source, shifts, and overlap.
- Upload of mono or stereo WAV or MP3, progress, cancellation, retry, deletion, history, original playback, result playback, and ZIP download.
- Single machine, bound to localhost, no accounts. English interface. Svelte modules, built to static files the local server serves.

Open: what "a more seamless implementation" means, and when it should be built. Do not invent that product.

## Brand Commitments

The name is StemLab. The interface should read as DJ software: clean and minimal. Current marketing copy that sounds like a generic AI product may be rewritten. Functional labels and workflow copy stay accurate.

## Evidence on Hand

The working app, its README, and the local job history are the evidence. Do not invent testimonials, benchmarks, customers, or pricing.

## Product Principles

- The track and the job are the interface. Marketing language does not compete with the work.
- Every existing separation workflow stays reachable.
- Processing state is honest: real stages, not a fake sense of completion.
- Audio stays on this machine.
- Future integration is out of scope until it is specified.
