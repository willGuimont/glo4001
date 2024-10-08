import ast
import base64
from io import BytesIO

import depthai as dai
import numpy as np
from PIL import Image

from robmob.sensors import Sensor


class RobotEspSensor(Sensor):
    TOPIC = '/rover/state'
    MESSAGE_TYPE = 'std_msgs/msg/String'
    SAMPLE_RATE = 10

    def __init__(self, buffer_size=100000):
        super().__init__(buffer_size)

    def parse_message(self, message):
        data = message['msg']['data']
        return ast.literal_eval(data)


class SharpSensor(Sensor):
    TOPIC = '/range'
    MESSAGE_TYPE = 'std_msgs/msg/Float32'
    SAMPLE_RATE = 100

    # Calibration table of the high range sharp sensor, for 15+ cm.
    HIGH_RANGE_CALIB_TABLE = np.asarray([
        [15, 2.76],
        [20, 2.53],
        [30, 1.99],
        [40, 1.53],
        [50, 1.23],
        [60, 1.04],
        [70, 0.91],
        [80, 0.82],
        [90, 0.72],
        [100, 0.66],
        [110, 0.6],
        [120, 0.55],
        [130, 0.50],
        [140, 0.46],
        [150, 0.435],
        [200, 0],
        [np.inf, 0]
    ])

    def __init__(self, buffer_size=100):
        """
        There are two Sharp sensors on the robot. The analog_input_id 0 is the long range sensor
        and the analog_input_id 1 is the short range sensor.
        """
        super().__init__(buffer_size)

    def parse_message(self, message):
        return float(message['msg']['data'])


class CameraRGBSensor(Sensor):
    # TODO bypass ROS and use the camera directly
    TOPIC = '/color/video/image/compressed'
    MESSAGE_TYPE = 'sensor_msgs/msg/CompressedImage'
    SAMPLE_RATE = 30

    def __init__(self, buffer_size=5):
        super().__init__(buffer_size)

    def parse_message(self, message):
        image_data = message['msg']['data']
        decompressed_image = Image.open(BytesIO(base64.b64decode(image_data)))
        return np.array(decompressed_image)


class CameraDepthSensor(Sensor):
    # TODO bypass ROS and use the camera directly
    TOPIC = '/stereo/depth'
    MESSAGE_TYPE = ('sensor_msgs/msg/Image')
    # TOPIC = '/stereo/depth/compressedDepth'
    # MESSAGE_TYPE = ('sensor_msgs/msg/CompressedImage')
    SAMPLE_RATE = 30

    def __init__(self, buffer_size=5):
        super().__init__(buffer_size)

    def parse_message(self, message):
        msg = message['msg']
        base64_bytes = msg['data'].encode('ascii')
        image_bytes = base64.b64decode(base64_bytes)
        image = np.frombuffer(image_bytes, dtype=np.uint16)
        image = image.reshape((msg['height'], msg['width'], 1))
        return image


class OakLiteCamera:
    RESOLUTION = (1920, 1080)

    def __init__(self):
        self.pipeline = dai.Pipeline()

        # RGB
        cam_rgb = self.pipeline.create(dai.node.ColorCamera)
        cam_rgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
        cam_rgb.setInterleaved(False)
        cam_rgb.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)
        # Right
        cam_right = self.pipeline.create(dai.node.MonoCamera)
        cam_right.setCamera('right')
        cam_right.setResolution(dai.MonoCameraProperties.SensorResolution.THE_480_P)
        # Left
        cam_left = self.pipeline.create(dai.node.MonoCamera)
        cam_left.setCamera('left')
        cam_left.setResolution(dai.MonoCameraProperties.SensorResolution.THE_480_P)
        # Depth
        cam_stereo = self.pipeline.create(dai.node.StereoDepth)
        cam_stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.HIGH_DENSITY)
        cam_stereo.initialConfig.setMedianFilter(dai.MedianFilter.KERNEL_7x7)
        cam_stereo.setRectifyEdgeFillColor(0)
        cam_stereo.setLeftRightCheck(True)
        cam_stereo.setSubpixel(True)

        # Links
        xout_rgb = self.pipeline.create(dai.node.XLinkOut)
        cam_right.out.link(cam_stereo.right)
        cam_left.out.link(cam_stereo.left)
        xout_rgb.setStreamName('rgb')
        cam_rgb.video.link(xout_rgb.input)
        xout_depth = self.pipeline.create(dai.node.XLinkOut)
        xout_depth.setStreamName('depth')
        cam_stereo.depth.link(xout_depth.input)

        self.device = dai.Device(self.pipeline)
        self.queue_rgb = self.device.getOutputQueue(name='rgb', maxSize=4, blocking=False)
        self.queue_depth = self.device.getOutputQueue(name='depth', maxSize=4, blocking=False)

    def __del__(self):
        self.device.close()

    def get_rgb_image(self):
        in_rgb = self.queue_rgb.get()
        return in_rgb.getCvFrame()[:, :, ::-1]

    def get_depth_image(self):
        in_depth = self.queue_depth.get()
        return in_depth.getFrame()
