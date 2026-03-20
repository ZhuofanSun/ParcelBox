# Vision Models

Place local MediaPipe model files in this directory.

Current default paths from [config.py](/Users/sunzhuofan/IOT-project/config.py):

- `models/person_detector.tflite`
- `models/face_detector.task`

The code expects:

- `person_detector.tflite` for MediaPipe Object Detector, filtered to the `person` class
- `face_detector.task` for MediaPipe Face Detector

You can rename downloaded model files to match these defaults, or change the paths in
`config.py`.
