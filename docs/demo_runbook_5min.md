# 5-Minute Demo Runbook

This is the shortest useful demo path for the current ParcelBox prototype.

Goal: show only the most important integrated behaviors in about 5 minutes.

## Before Recording

- Start the app:

```bash
./.venv/bin/python main.py
```

- Open the frontend and make sure the live stream is already working
- Prepare:
  - one authorized card
  - one unauthorized card
  - access to the hardware button
- Optional but recommended:
  - start in dark mode
  - keep one face briefly available for the tracking section
  - hide or avoid lingering on email password fields

## Demo Flow

### 0:00 - 0:30 Intro

Show:

- `Overview` page
- live stream
- runtime summary
- Raspberry Pi metrics

Say:

- this is a single-device ParcelBox prototype on Raspberry Pi
- the page is an operations console for testing the full stack

### 0:30 - 1:00 Live Vision

Show:

- face entering frame
- face box tracking
- mount status changing on the page

Say:

- the frontend receives the live MJPEG stream and face boxes separately
- the system can track faces and drive the camera mount

### 1:00 - 1:25 Manual Snapshot

Do:

- click `Capture Photo`
- switch to `Events & Snapshots`
- open the new snapshot in the viewer

Say:

- snapshots are stored locally and linked into the event history

### 1:25 - 2:05 Authorized RFID

Do:

- present an authorized card
- show that the door opens
- briefly show the new allowed event in `Events & Snapshots`

Say:

- authorized RFID opens the locker and records the attempt, session, and snapshot

### 2:05 - 2:45 Unauthorized RFID

Do:

- move out of frame so no face is visible
- present an unauthorized card
- let the buzzer sound
- open the bell

Show:

- denied event
- extra red alarm entry
- bell opening silences the alarm

Say:

- unauthorized access creates both the normal denial event and a higher-priority alarm
- if no face is present, the camera mount starts one recovery search sweep

### 2:45 - 3:30 Hardware Button

Do:

- press the hardware button once

Show:

- button event appears
- snapshot / email result appears in event flow

Say:

- this simulates a delivery-side open request with photo capture and email notification

### 3:30 - 4:10 Button Spam Alarm

Do:

- rapidly press the hardware button 5 times
- open the bell again

Show:

- medium alarm behavior
- extra red alarm entry
- normal bell notifications do not flood uncontrollably

Say:

- repeated button presses are treated as a separate alert condition

### 4:10 - 4:40 Settings

Show quickly:

- theme toggle
- profile settings with persistent avatar
- notification settings with email scheme selector

Say:

- device profile and email delivery schemes are persisted on the box

### 4:40 - 5:00 Debug / Data

Show:

- `Debug / Data`
- one or two raw tables
- row-limit filter

Say:

- every important operation is visible both in the user-facing event feed and in the raw SQLite-backed tables

## Demo Shortcuts

If time is tight, do not show:

- card enrollment
- long email configuration edits
- table-by-table walkthrough
- profile avatar upload flow

## Demo Recovery Notes

If something goes wrong during recording:

- if the bell is sounding too long, open the notification bell to silence it
- if the stream is blank on first load, wait a moment for reconnect before refreshing
- if a button spam sequence accidentally starts too early, let it finish and continue with the bell-silence step
