# Vision Models

The current Phase 2 baseline uses the `opencv` vision backend, so this folder is not
required for the first working person / face detection loop.

This folder currently holds the active OpenCV vision models used by the project.

Current reserved paths from [config.py](/Users/sunzhuofan/IOT-project/config.py):

- `models/object_detection_nanodet_2022nov.onnx`
- `models/face_detection_yunet_2023mar.onnx`

Current recommended person model path:

- `models/object_detection_nanodet_2022nov.onnx`

Optional lighter fallback:

- `models/object_detection_nanodet_2022nov_int8bq.onnx`

Current recommended face model path:

- `models/face_detection_yunet_2023mar.onnx`

If the YuNet model is not present, the OpenCV vision backend falls back to Haar cascade.



reference link:

https://huggingface.co/opencv

https://huggingface.co/opencv/face_detection_yunet/tree/main

https://huggingface.co/opencv/opencv_zoo




