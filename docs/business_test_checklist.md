# Business Test Checklist

Single-device end-to-end checklist for the current ParcelBox prototype.

## Scope

This checklist is for the integrated app, not low-level hardware-only smoke tests.

Use it after:

- wiring changes
- configuration changes
- frontend changes
- service logic changes
- before recording a demo

## Preconditions

- Raspberry Pi is powered and all hardware is connected
- `pigpiod` is already enabled and running
- app is running with:

```bash
./.venv/bin/python main.py
```

- browser opens the frontend successfully
- at least:
  - one authorized RFID card is available
  - one unauthorized / unknown RFID card is available
  - one working email delivery scheme is enabled

## Quick Pass

Run these first. If any fail, stop before the full checklist.

- [ ] Frontend opens and the live stream appears without repeated manual refresh
- [ ] Face box updates in the live stream
- [ ] `Overview` shows runtime summary and Raspberry Pi stats
- [ ] Manual `Capture Photo` creates a snapshot and it opens in viewer
- [ ] Authorized RFID scan opens the door
- [ ] Unauthorized RFID scan creates a denied event and red bell alert
- [ ] Hardware button press creates a button event and sends email

## Full End-to-End Checklist

### 1. Startup And Overview

- [ ] Open the frontend home page
- [ ] Confirm MJPEG video appears
- [ ] Confirm face box tracks when a face is visible
- [ ] Confirm `Runtime Summary` and Raspberry Pi status cards populate
- [ ] Confirm no blocking modal or broken overlay appears on load

Expected:

- live video is visible
- overlay box moves with face
- no console-like errors in UI

### 2. Theme, Profile, And Settings Persistence

- [ ] Switch light / dark theme
- [ ] Refresh page and confirm theme persists
- [ ] Update display name / subtitle in profile settings and save
- [ ] Upload avatar and refresh
- [ ] Reset avatar back to initials and refresh

Expected:

- saved profile data persists across refresh and backend restart

### 3. Email Scheme Baseline

- [ ] Open `Settings -> Notifications`
- [ ] Select the enabled email scheme
- [ ] Confirm scheme details and recipient list are loaded
- [ ] Send a test email

Expected:

- test email succeeds
- current scheme is the only enabled one

### 4. Manual Snapshot Flow

- [ ] Click `Capture Photo`
- [ ] Check `Events & Snapshots` for the new snapshot
- [ ] Open the snapshot viewer from the snapshot list
- [ ] Open the same snapshot from an event card if available

Expected:

- snapshot file exists
- viewer shows image, timestamp, trigger, and relation tag

### 5. Authorized RFID Flow

- [ ] Present a known authorized card
- [ ] Confirm door opens
- [ ] Confirm event feed shows `door_opened`
- [ ] Confirm related snapshot is attached
- [ ] Wait for or trigger door close

Expected:

- one allowed access attempt
- one door session
- snapshot linked to the access attempt

### 6. Unauthorized RFID Flow

- [ ] Move out of frame so no face is visible
- [ ] Present an unknown / unauthorized card once
- [ ] Listen for unauthorized-card sound
- [ ] Open the top-right notification bell
- [ ] Confirm a red alarm entry is present

Expected:

- normal card-detected chirp plus a single unauthorized-card alarm beep
- `access_denied` is logged
- one extra red in-app alarm appears
- if no face is present, one search sweep starts
- opening the bell marks alerts as read and silences active alarm playback

### 7. Repeated Unauthorized RFID Flow

- [ ] With no face in frame, present unauthorized card repeatedly within the burst window
- [ ] Confirm severe alarm pattern triggers
- [ ] Confirm bell shows extra red alarm entry for repeated denials

Expected:

- repeated denial alarm escalates
- search does not stack if one is already in progress

### 8. Hardware Button Single Press

- [ ] Press the hardware button once
- [ ] Confirm a button event appears
- [ ] Confirm email is sent
- [ ] Confirm snapshot is captured if snapshot cooldown is clear

Expected:

- one button event
- one email send result
- one snapshot, unless suppressed by cooldown

### 9. Hardware Button Spam Alarm

- [ ] Rapidly press the hardware button 5 times within the burst window
- [ ] Confirm medium alarm pattern triggers
- [ ] Confirm bell shows a red alarm entry
- [ ] Confirm normal button notifications do not flood the bell

Expected:

- button burst alarm triggers once per burst cycle
- normal button snapshot / bell notifications are cooled down
- burst counting is not cooled down
- if no face is visible, only one search sweep starts

### 10. Snapshot Retention And Viewer

- [ ] Open several recent snapshots in the viewer
- [ ] Confirm `Previous / Next` works
- [ ] Confirm keyboard left / right works
- [ ] Confirm missing-file snapshots show fallback text instead of breaking the UI

Expected:

- viewer is stable
- no broken page state after closing modal

### 11. Debug / Data Verification

- [ ] Open `Debug / Data`
- [ ] Change the row-limit filter
- [ ] Confirm these tables look sane:
  - `rfid_card`
  - `access_attempt`
  - `door_session`
  - `button_request`
  - `snapshot`
  - `email_subscription_scheme`
  - `email_subscription_recipient`

Expected:

- recent operations are reflected in the raw tables

### 12. Alarm Silence Behavior

- [ ] Trigger any active alarm
- [ ] While buzzer is still sounding, open the notification bell

Expected:

- current alarm playback stops immediately
- bell state becomes read

## Optional Reliability Pass

- [ ] Leave frontend open for 10 to 15 minutes
- [ ] Confirm video stream still updates
- [ ] Trigger one manual snapshot
- [ ] Trigger one authorized RFID scan
- [ ] Trigger one button press

Expected:

- no manual page refresh needed

## Post-Test Review

Record these before ending the session:

- [ ] any failed checklist item
- [ ] exact timestamp of the failure
- [ ] relevant snapshot filename if one was created
- [ ] relevant event row in `Debug / Data`
- [ ] whether recovery required a page refresh or app restart
