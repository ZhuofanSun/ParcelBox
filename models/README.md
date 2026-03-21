# Vision Models

The current Phase 2 baseline uses the `opencv` vision backend, so this folder is not
required for the first working person / face detection loop.

This folder is reserved for future detector backends such as:

- `tflite`
- `yolo`
- `yunet`
- `mp_persondet`

Current reserved paths from [config.py](/Users/sunzhuofan/IOT-project/config.py):

- `models/person_detection_mediapipe_2023mar_int8bq.onnx`
- `models/face_detection_yunet_2023mar.onnx`
- `models/yolo26n.pt`

Current recommended person model path:

- `models/person_detection_mediapipe_2023mar_int8bq.onnx`

Optional heavier fallback:

- `models/person_detection_mediapipe_2023mar.onnx`

Current recommended face model path:

- `models/face_detection_yunet_2023mar.onnx`

If the YuNet model is not present, the OpenCV vision backend falls back to Haar cascade.



reference link:

https://huggingface.co/opencv

https://huggingface.co/opencv/face_detection_yunet/tree/main

https://huggingface.co/opencv/opencv_zoo






